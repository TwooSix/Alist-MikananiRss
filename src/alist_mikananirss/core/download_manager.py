import asyncio
import os
from typing import Optional

from loguru import logger
from tenacity import (
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from alist_mikananirss import utils
from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTask,
    AlistTaskState,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.websites.models import ResourceInfo

from ..utils import FixedSizeSet, Singleton
from .notification_sender import NotificationSender
from .renamer import AnimeRenamer


class TaskMonitor:
    NORMAL_STATUS = [
        AlistTaskState.Pending,
        AlistTaskState.Running,
        AlistTaskState.StateBeforeRetry,
        AlistTaskState.StateWaitingRetry,
    ]

    def __init__(
        self,
        alist_client: Alist,
        db: SubscribeDatabase,
        use_renamer: bool,
        need_notification: bool,
    ):
        self.alist_client = alist_client
        self.db = db
        self.uuid_set = FixedSizeSet()
        self.use_renamer = use_renamer
        self.need_notification = need_notification
        self.running_tasks: list[AlistTask] = []
        self.task_resource_map: dict[AlistTask, ResourceInfo] = {}

        self.lock = asyncio.Lock()
        self.coroutine = None

    async def _fetch_remote_tasks(self):
        """获取远程任务列表"""
        try:
            download_tasks = await self.alist_client.get_task_list(
                AlistTaskType.DOWNLOAD
            )
            transfer_tasks = await self.alist_client.get_task_list(
                AlistTaskType.TRANSFER
            )
            return download_tasks + transfer_tasks
        except Exception as e:
            logger.error(f"Error when getting task list: {e}")
            return []

    def _refresh_task(
        self, old_task_list: list[AlistTask], new_task_list: list[AlistTask]
    ):
        new_tid_map = {task.tid: task for task in new_task_list}
        for task in old_task_list:
            if task.tid not in new_tid_map:
                logger.warning(f"Task {task.tid} not found in remote task list")
                continue

            new_task = new_tid_map[task.tid]
            task.__dict__.update(new_task.__dict__)
            logger.debug(
                f"Checking {task} state: {task.state} progress: {task.progress:.2f}%"
            )

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=0.5, min=1, max=15),
        retry=retry_if_result(lambda x: x is None),
        retry_error_callback=lambda _: None,
    )
    async def _find_transfer_task(
        self, download_task: AlistDownloadTask
    ) -> Optional[AlistTransferTask]:
        """Find the transfer task that is related to the download task

        Args:
            download_task (AlistDownloadTask): The download task to find the transfer task for

        Returns:
            Optional[AlistTransferTask]: The transfer task if found, None otherwise
        """
        try:
            transfer_task_list: list[AlistTransferTask] = (
                await self.alist_client.get_task_list(AlistTaskType.TRANSFER)
            )
        except Exception as e:
            logger.warning(f"Error when getting transfer task list: {e}")
            return None
        # Filter out the transfer tasks by start_time and state
        transfer_task_list = [
            task
            for task in transfer_task_list
            if (
                # 1. The transfer task is not already linked
                task.uuid not in self.uuid_set
                # 2. It's a video file
                and utils.is_video(task.target_path)
                # 3. It's created after the download task
                and task.start_time > download_task.start_time
                # 4. The transfer task is in a valid state
                and task.state
                in [
                    AlistTaskState.Pending,
                    AlistTaskState.Running,
                    AlistTaskState.Succeeded,
                ]
                # 5. Same anime, same season
                and download_task.download_path in task.target_path
            )
        ]
        if len(transfer_task_list) == 0:
            return None
        # Sort by start time, the latest one first
        transfer_task_list.sort(key=lambda x: x.start_time, reverse=True)
        matched_tf_task = transfer_task_list[0]
        self.uuid_set.add(matched_tf_task.uuid)
        logger.debug(f"Linked [{download_task.url}] to {matched_tf_task.uuid}")
        return matched_tf_task

    async def _post_process(self, tf_task: AlistTransferTask, resource: ResourceInfo):
        "Something to do after download task success"
        logger.info(f"Download {resource.resource_title} success")
        if self.use_renamer:
            remote_filepath = tf_task.target_path
            await AnimeRenamer.rename(remote_filepath, resource)
        if self.need_notification:
            await NotificationSender.add_resource(resource)

    async def _process_successed_tasks(self, task_list: list[AlistTask]):
        """Process the successed tasks

        Args:
            task_list (list[AlistTask]): The task list to process
        """
        for task in task_list:
            if task.task_type == AlistTaskType.DOWNLOAD:
                tf_task = await self._find_transfer_task(task)
                if tf_task is None:
                    logger.error(
                        f"Can't find transfer task for [{self.task_resource_map[task].resource_title}]"
                    )
                else:
                    self.running_tasks.append(tf_task)
                    self.task_resource_map[tf_task] = self.task_resource_map[task]
            elif task.task_type == AlistTaskType.TRANSFER:
                resource = self.task_resource_map[task]
                await self._post_process(task, resource)

    async def _process_failed_tasks(self, task_list: list[AlistTask]):
        """Process the failed tasks

        Args:
            task_list (list[AlistTask]): The task list to process
        """
        for task in task_list:
            resource = self.task_resource_map[task]
            logger.error(
                f"{type(task)} of [{resource.resource_title}] failed: {task.error}"
            )
            await self.db.delete_by_resource_title(resource.resource_title)

    async def monitor(self, task: AlistTask, resource_info: ResourceInfo):
        """Start monitor the download task.

        Args:
            task (AlistTask): Download task object
            resource_info (ResourceInfo): The resource info which is related to the task
        """
        async with self.lock:
            self.running_tasks.append(task)
            self.task_resource_map[task] = resource_info
            if (
                self.coroutine is None
                or self.coroutine.done()
                or self.coroutine.cancelled()
            ):
                logger.debug("Createing a new monitor task")
                self.coroutine = asyncio.create_task(self.run())

    async def run(self):
        while len(self.running_tasks) > 0:
            # 1. Get remote task list
            async with self.lock:
                new_task_list = await self._fetch_remote_tasks()
                if not new_task_list:
                    await asyncio.sleep(1)
                    continue

                # 2. Update running tasks state
                self._refresh_task(self.running_tasks, new_task_list)

                # 3. Process finished tasks
                successed_task = []
                failed_task = []
                for task in self.running_tasks:
                    if task.state == AlistTaskState.Succeeded:
                        successed_task.append(task)
                    elif task.state not in self.NORMAL_STATUS:
                        failed_task.append(task)

                await self._process_successed_tasks(successed_task)
                await self._process_failed_tasks(failed_task)

                # 4. update running tasks
                tasks_to_remove = successed_task + failed_task

                for task in tasks_to_remove:
                    self.running_tasks.remove(task)
                    del self.task_resource_map[task]

            await asyncio.sleep(1)

    async def wait_finished(self):
        if self.coroutine and not self.coroutine.done():
            await self.coroutine


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
        self.db = db
        self.task_monitor = TaskMonitor(
            alist_client=alist_client,
            db=db,
            use_renamer=use_renamer,
            need_notification=need_notification,
        )

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
    ) -> list[AlistDownloadTask]:
        """Create alist offline download task

        Args:
            new_resources (list[ResourceInfo]): resources list

        Returns:
            list[AlistDownloadTask]: Successful download tasks
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
        return task_list

    @classmethod
    async def add_download_tasks(cls, resources: list[ResourceInfo]):
        instance = cls()
        dl_tasks = await instance.download(resources)
        for dl_task in dl_tasks:
            matched_resource = None
            for resource in resources:
                if resource.torrent_url == dl_task.url:
                    matched_resource = resource
                    break
            if not matched_resource:
                logger.error(f"Can't matched download task [{dl_task.url}] to resource")
                continue
            await instance.db.insert_resource_info(matched_resource)
            await instance.task_monitor.monitor(dl_task, matched_resource)
