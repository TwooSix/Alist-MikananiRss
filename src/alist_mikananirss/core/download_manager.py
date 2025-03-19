import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from alist_mikananirss import utils
from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTask,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.websites.models import ResourceInfo

from ..utils import FixedSizeSet, Singleton
from .notification_sender import NotificationSender
from .renamer import AnimeRenamer


@dataclass
class AnimeDownloadTaskInfo:
    resource: ResourceInfo
    download_task: AlistDownloadTask
    transfer_task: Optional[AlistTransferTask] = None


class TaskMonitor:
    NORMAL_STATUS = [
        AlistTaskStatus.Pending,
        AlistTaskStatus.Running,
        AlistTaskStatus.StateBeforeRetry,
        AlistTaskStatus.StateWaitingRetry,
    ]
    STALL_THRESHOLD = 300  # 5min
    PROGRESS_THRESHOLD = 0.01  # 1%

    def __init__(
        self,
        alist: Alist,
        task: AlistTransferTask | AlistDownloadTask,
    ):
        self.alist = alist
        self.task = task
        self.last_progress = 0
        self.last_progress_time = time.time()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=15),
    )
    async def _refresh(self):
        task_list = await self.alist.get_task_list(self.task.task_type)
        task = task_list.get_by_id(self.task.tid)
        if not task:
            raise RuntimeError("Can't find the task {self.task.tid}")
        self.task = task

    def _is_progress_stalled(self) -> bool:
        current_progress = self.task.progress
        current_time = time.time()

        time_elapsed = current_time - self.last_progress_time
        progress_change = current_progress - self.last_progress

        if (
            time_elapsed > self.STALL_THRESHOLD
            and progress_change < self.PROGRESS_THRESHOLD
            and self.task.status is AlistTaskStatus.Running
        ):
            return True

        if progress_change >= self.PROGRESS_THRESHOLD:
            self.last_progress = current_progress
            self.last_progress_time = current_time

        return False

    async def wait_finished(self) -> AlistTask:
        """Loop check task tatus until it finished or error

        Raises:
            TimeoutError: If the download progress remains unchanged for a long time, throw an exception
            RetryError: If the task status can't be refreshed, throw an exception

        Returns:
            AlistTask: The finished task
        """
        while True:
            await self._refresh()
            logger.debug(
                f"Checking {self.task} status: {self.task.status} progress: {self.task.progress:.2f}%"
            )
            if self.task.status not in self.NORMAL_STATUS:
                return self.task

            if self._is_progress_stalled():
                logger.warning(f"Progress is too slow of Task[{self.task.url}].")
                await asyncio.sleep(60)
                # raise TimeoutError("Progress is too slow")

            await asyncio.sleep(1)


class DownloadManager(metaclass=Singleton):
    def __init__(
        self,
        alist_client: Alist,
        base_download_path: str,
        use_renamer: bool = False,
        need_notification: bool = False,
        db: SubscribeDatabase = None,
    ):
        self.alist_client = alist_client
        self.base_download_path = base_download_path
        self.use_renamer = use_renamer
        self.need_notification = need_notification
        self.uuid_set = FixedSizeSet()
        self.db = db

    @classmethod
    def initialize(
        cls,
        alist_client: Alist,
        base_download_path: str,
        use_renamer: bool = False,
        need_notification: bool = False,
        db: SubscribeDatabase = None,
    ) -> None:
        cls(
            alist_client=alist_client,
            base_download_path=base_download_path,
            use_renamer=use_renamer,
            need_notification=need_notification,
            db=db,
        )

    @classmethod
    async def add_download_tasks(cls, resources: list[ResourceInfo]):
        instance = cls()
        info_list: list[AnimeDownloadTaskInfo] = await instance.download(resources)
        for task_info in info_list:
            await instance.db.insert_resource_info(task_info.resource)
            asyncio.create_task(instance.monitor(task_info))

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=0.5, min=1, max=15),
        retry_error_callback=lambda _: None,
    )
    async def _find_transfer_task(
        self, download_task: AlistDownloadTask
    ) -> AlistTransferTask:
        try:
            transfer_task_list: list[AlistTransferTask] = (
                await self.alist_client.get_task_list(AlistTaskType.TRANSFER)
            )
        except Exception as e:
            logger.error(f"Error when getting transfer task list: {e}")
            raise
        for transfer_task in transfer_task_list:
            # 查找第一个，未被标记过的与下载任务的目标路径相同的视频文件传输任务作为下载任务对应的传输任务
            if (
                transfer_task.uuid not in self.uuid_set
                and utils.is_video(transfer_task.target_path)
                and transfer_task.status
                in [AlistTaskStatus.Pending, AlistTaskStatus.Running]
                and download_task.download_path in transfer_task.target_path
            ):
                self.uuid_set.add(transfer_task.uuid)
                logger.debug(f"Linked [{download_task.url}] to {transfer_task.uuid}")
                return transfer_task
        logger.warning(
            f"Can't find the transfer task of [{download_task.url}], retrying..."
        )
        raise TimeoutError("Transfer task not found")

    async def _wait_success(
        self, task: AnimeDownloadTaskInfo
    ) -> Optional[AnimeDownloadTaskInfo]:
        """monitor one task until it finished

        Args:
            task (AnimeDownloadTaskInfo): Task which need to be monitored

        Returns:
            AnimeDownloadTaskInfo | None: return the task info if download and transfer success, else return None
        """

        async def wait_task(task_obj: AlistTask):
            monitor = TaskMonitor(self.alist_client, task_obj)
            try:
                finished_task = await monitor.wait_finished()
                if finished_task.status == AlistTaskStatus.Succeeded:
                    return finished_task
                else:
                    logger.error(
                        f"Task {task_obj.tid} failed: {finished_task.error_msg}"
                    )
            except TimeoutError:
                # await self.alist_client.cancel_task(task_obj)
                logger.error(f"TimeoutError when wait {task_obj} finished.")
            except RetryError as e:
                logger.error(
                    f"Error to refresh task status: {e.last_attempt.exception()}"
                )
            return None

        success_download_task = await wait_task(task.download_task)
        if not success_download_task:
            return None

        transfer_task = await self._find_transfer_task(success_download_task)
        if not transfer_task:
            logger.error(
                f"Timeout to find the transfer task of {task.resource.resource_title}"
            )
            return None

        success_transfer_task = await wait_task(transfer_task)
        if not success_transfer_task:
            return None
        success_task_info = AnimeDownloadTaskInfo(
            resource=task.resource,
            download_task=success_download_task,
            transfer_task=success_transfer_task,
        )
        return success_task_info

    def _post_process(self, task: AnimeDownloadTaskInfo):
        "Something to do after download task success"
        logger.info(f"Download {task.resource.resource_title} success")
        if self.use_renamer:
            remote_filepath = task.transfer_task.target_path
            asyncio.create_task(AnimeRenamer.rename(remote_filepath, task.resource))
        if self.need_notification:
            asyncio.create_task(NotificationSender.add_resource(task.resource))

    async def monitor(self, task_info: AnimeDownloadTaskInfo):
        success_task = await self._wait_success(task_info)
        if success_task is not None:
            self._post_process(success_task)
        else:
            # 下载失败，删除数据库记录
            await self.db.delete_by_resource_title(task_info.resource.resource_title)

    def _build_download_path(self, resource: ResourceInfo) -> str:
        """build the download path based on the anime name and season
        The result looks like this: base_download_path/AnimeName/Season {season} \n
        if the anime name is not available, use the base download path

        Args:
            resource (ResourceInfo)

        Returns:
            str: new download path
        """
        download_path = self.base_download_path
        if resource.anime_name:
            # Replace illegal characters in the anime_name
            illegal_chars = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]
            anime_name = resource.anime_name
            for char in illegal_chars:
                anime_name = anime_name.replace(char, " ")
            download_path = os.path.join(download_path, anime_name)
            # Need to compare with None, or when seaon=0 will be ignored
            if resource.season is not None:
                download_path = os.path.join(download_path, f"Season {resource.season}")
        return download_path

    async def download(
        self, new_resources: list[ResourceInfo]
    ) -> list[AnimeDownloadTaskInfo]:
        """Create alist offline download task

        Args:
            new_resources (list[MikanAnimeResource]): resources list
            base_download_path (str): remote dir path

        Returns:
            list[AnimeDownloadTaskInfo]: Successful download task's info
        """
        # Generate a mapping of download paths to resources
        # facilitating batch creation of download tasks and reducing requests to the Alist API
        ## mapping of {download_path: [torrent_url]}
        path_urls: dict[str, list[str]] = {}
        for resource in new_resources:
            download_path = self._build_download_path(resource)
            path_urls.setdefault(download_path, []).append(resource.torrent_url)
        # start to request the Alist Download API
        task_list = []
        for download_path, urls in path_urls.items():
            try:
                task_list += await self.alist_client.add_offline_download_task(
                    download_path, urls
                )
                logger.info(
                    f"Start to download {len(urls)} resources to [{download_path}]"
                )
            except Exception as e:
                logger.error(f"Error when add offline download task: {e}")
                continue
        # Patch the download task with the resource information
        anime_task_list = [
            AnimeDownloadTaskInfo(
                resource=resource,
                download_task=task,
            )
            for task in task_list
            for resource in new_resources
            if resource.torrent_url == task.url
        ]
        return anime_task_list
