import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTaskList,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.websites import ResourceInfo

from .notification_sender import NotificationSender
from .renamer import AnimeRenamer


@dataclass
class AnimeDownloadTaskInfo:
    resource: ResourceInfo
    download_path: str
    download_task: Optional[AlistDownloadTask] = None
    transfer_task: Optional[AlistTransferTask] = None


class TaskMonitor:
    normal_status = [
        AlistTaskStatus.Pending,
        AlistTaskStatus.Running,
        AlistTaskStatus.StateBeforeRetry,
        AlistTaskStatus.StateWaitingRetry,
    ]

    def __init__(
        self,
        alist: Alist,
        task: AlistTransferTask | AlistDownloadTask,
    ):
        self.alist = alist
        self.task = task

    async def __refresh(self):
        task_list = await self.alist.get_task_list(self.task.task_type)
        task = task_list[self.task.tid]
        if not task:
            raise RuntimeError(f"Can't find the task {self.task.tid}")
        self.task = task

    async def wait_finished(self):
        last_progress = 0
        last_progress_time = time.time()
        stall_threshold = 300  # 5分钟
        progress_threshold = 0.01  # 1%
        while True:
            try:
                await self.__refresh()
                current_progress = self.task.progress
            except Exception as e:
                logger.warning(f"Error when refresh {self.task} status: {e}")
                await asyncio.sleep(1)
                continue
            logger.debug(
                f"Checking {self.task} status: {self.task.status} progress: {current_progress:.2f}%"
            )
            if self.task.status not in self.normal_status:
                return self.task

            # 若长时间下载进度没有变化，则抛出异常
            current_time = time.time()
            time_elapsed = current_time - last_progress_time
            progress_change = current_progress - last_progress
            if time_elapsed > stall_threshold and progress_change < progress_threshold:
                raise RuntimeError(
                    f"Progress is too slow: {progress_change:.2%} in {time_elapsed:.2f} seconds"
                )
            if progress_change >= progress_threshold:
                last_progress = current_progress
                last_progress_time = current_time

            await asyncio.sleep(1)


class DownloadManager:
    _instance = None
    alist_client: Alist
    base_download_path: str
    use_renamer: bool = False
    need_notification: bool = False
    uuid_set: set[str] = set()
    db = SubscribeDatabase()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DownloadManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def initialize(
        cls,
        alist_client: Alist,
        base_download_path: str,
        use_renamer: bool = False,
        need_notification: bool = False,
    ) -> None:
        cls._instance = cls()
        cls.alist_client = alist_client
        cls.base_download_path = base_download_path
        cls.use_renamer = use_renamer
        cls.need_notification = need_notification

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            raise RuntimeError("DownloadManager is not initialized")
        return cls._instance

    @classmethod
    async def add_download_tasks(cls, resources: list[ResourceInfo]):
        instance = cls.get_instance()
        info_list: list[AnimeDownloadTaskInfo] = await instance.download(resources)
        for task_info in info_list:
            instance.db.insert_resource_info(task_info.resource)
            asyncio.create_task(instance.monitor(task_info))

    async def _find_transfer_task(self, resource: ResourceInfo) -> AlistTransferTask:
        def is_video(file_name: str) -> bool:
            video_suffix = [".mp4", ".mkv", ".avi", ".rmvb", ".wmv", ".flv"]
            for suffix in video_suffix:
                if file_name.endswith(suffix):
                    return True
            return False

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
        """monitor one task until it succeed

        Args:
            resource (MikanAnimeResource): resource need to be monitored

        Returns:
            MikanAnimeResource | None: return the resource if download succeed, else return None
        """
        download_task = task.download_task
        download_task_monitor = TaskMonitor(self.alist_client, download_task)
        try:
            download_task = await download_task_monitor.wait_finished()
        except RuntimeError:
            self.alist_client.cancel_task(download_task)
            logger.error(
                f"Timeout to wait the download task of {task.resource.resource_title} succeed"
            )
            return None
        if download_task.status != AlistTaskStatus.Succeeded:
            logger.error(f"Error when download {task.resource.resource_title}")
            return None

        try:
            transfer_task = await self._find_transfer_task(task.resource)
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout to find the transfer task of {task.resource.resource_title}"
            )
            return None
        transfer_task_monitor = TaskMonitor(self.alist_client, transfer_task)
        try:
            transfer_task = await transfer_task_monitor.wait_finished()
        except RuntimeError:
            self.alist_client.cancel_task(transfer_task)
            logger.error(
                f"Timeout to wait the transfer task of {task.resource.resource_title} succeed"
            )
            return None
        if transfer_task.status != AlistTaskStatus.Succeeded:
            logger.error(f"Error when transfer {task.resource.resource_title}")
            return None
        task.transfer_task = transfer_task
        return task

    def _post_process(self, task: AnimeDownloadTaskInfo):
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
            self.db.delete_by_id(task_info.resource.torrent_url)

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
            if resource.season:
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
        task_list = AlistTaskList()
        for download_path, urls in path_urls.items():
            try:
                tmp_task_list = await self.alist_client.add_offline_download_task(
                    download_path, urls
                )
            except Exception as e:
                logger.error(f"Error when add offline download task: {e}")
                continue
            task_list = task_list + tmp_task_list
        # Patch the download task with the resource information
        anime_task_list = []
        for task in task_list:
            for resource in new_resources:
                if resource.torrent_url == task.url:
                    anime_task = AnimeDownloadTaskInfo(
                        resource=resource,
                        download_task=task,
                        download_path=resource_path_map[resource],
                    )
                    logger.info(
                        f"Start to download {resource.resource_title} to {anime_task.download_path}"
                    )
                    anime_task_list.append(anime_task)
                    break
        return anime_task_list
