import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTask,
    AlistTaskCollection,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.websites import ResourceInfo

from ..utils import Singleton
from .notification_sender import NotificationSender
from .renamer import AnimeRenamer


@dataclass
class AnimeDownloadTaskInfo:
    resource: ResourceInfo
    download_path: str
    download_task: AlistDownloadTask
    transfer_task: Optional[AlistTransferTask] = None


class TaskMonitor:
    NORMAL_STATUSES = [
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
        reraise=True,
    )
    async def _refresh(self):
        task_list = await self.alist.get_task_list(self.task.task_type)
        task = task_list[self.task.tid]
        if not task:
            logger.warning(f"Can't find the task {self.task.tid}")
            raise RuntimeError("Task not found")
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

        Returns:
            AlistTask: The finished task
        """
        while True:
            await self._refresh()
            logger.debug(
                f"Checking {self.task} status: {self.task.status} progress: {self.task.progress:.2f}%"
            )
            if self.task.status not in self.NORMAL_STATUSES:
                return self.task

            if self._is_progress_stalled():
                raise TimeoutError("Progress is too slow")

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
        self.uuid_set = set()
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

    async def _find_transfer_task(self, resource: ResourceInfo) -> AlistTransferTask:
        def is_video(file_name: str) -> bool:
            return file_name.lower().endswith(
                (".mp4", ".mkv", ".avi", ".rmvb", ".wmv", ".flv")
            )

        async with asyncio.timeout(10):
            while True:
                try:
                    transfer_task_list = await self.alist_client.get_task_list(
                        AlistTaskType.TRANSFER
                    )
                    for transfer_task in transfer_task_list:
                        # 查找第一个，未被标记过的番剧名相同的视频文件传输任务作为下载任务对应的传输任务
                        if (
                            transfer_task.uuid not in self.uuid_set
                            and is_video(transfer_task.file_name)
                            and transfer_task.status
                            in [AlistTaskStatus.Pending, AlistTaskStatus.Running]
                            and resource.anime_name in transfer_task.description
                        ):

                            self.uuid_set.add(transfer_task.uuid)
                            logger.debug(
                                f"Linked {resource.resource_title} to {transfer_task.uuid}"
                            )
                            return transfer_task

                    logger.warning(
                        f"Can't find the transfer task of {resource.resource_title}"
                    )
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error when getting transfer task list: {e}")
                    await asyncio.sleep(1)

    async def _wait_finished(
        self, task: AnimeDownloadTaskInfo
    ) -> Optional[AnimeDownloadTaskInfo]:
        """monitor one task until it finished

        Args:
            task (AnimeDownloadTaskInfo): Task which need to be monitored

        Returns:
            AnimeDownloadTaskInfo | None: return the task info if download and transfer finished, else return None
        """

        async def wait_task(task_obj):
            monitor = TaskMonitor(self.alist_client, task_obj)
            try:
                finished_task = await monitor.wait_finished()
                if finished_task.status != AlistTaskStatus.Succeeded:
                    raise ValueError(
                        f"Error in {type(task_obj)}: {finished_task.error_msg}"
                    )
                return finished_task
            except TimeoutError:
                await self.alist_client.cancel_task(task_obj)
                raise ValueError(
                    f"Timeout waiting for {type(task_obj)} of {task.resource.resource_title}"
                )
            except RuntimeError:
                raise ValueError(
                    f"Task not found: {type(task_obj)} of {task.resource.resource_title}"
                )

        try:
            task.download_task = await wait_task(task.download_task)
            transfer_task = await self._find_transfer_task(task.resource)
            task.transfer_task = await wait_task(transfer_task)
            return task
        except ValueError as e:
            logger.error(str(e))
            return None

    def _post_process(self, task: AnimeDownloadTaskInfo):
        "Something to do after download task success"
        if self.use_renamer:
            filepath = os.path.join(task.download_path, task.transfer_task.file_name)
            asyncio.create_task(AnimeRenamer.rename(filepath, task.resource))
        if self.need_notification:
            asyncio.create_task(NotificationSender.add_resource(task.resource))

    async def monitor(self, task_info: AnimeDownloadTaskInfo):
        success_task = await self._wait_finished(task_info)
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
        resource_path_map = {}  # mapping of {ResourceInfo: download_path}
        for resource in new_resources:
            download_path = self._build_download_path(resource)
            path_urls.setdefault(download_path, []).append(resource.torrent_url)
            resource_path_map[resource] = download_path
        # start to request the Alist Download API
        task_list = AlistTaskCollection()
        for download_path, urls in path_urls.items():
            try:
                task_list += await self.alist_client.add_offline_download_task(
                    download_path, urls
                )
            except Exception as e:
                logger.error(f"Error when add offline download task: {e}")
                continue
        # Patch the download task with the resource information
        anime_task_list = [
            AnimeDownloadTaskInfo(
                resource=resource,
                download_task=task,
                download_path=resource_path_map[resource],
            )
            for task in task_list
            for resource in new_resources
            if resource.torrent_url == task.url
        ]
        return anime_task_list
