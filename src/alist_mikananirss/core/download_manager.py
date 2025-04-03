import asyncio
import os

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

        self.running_tasks: list[AlistTask] = []
        self.task_resource_map: dict[AlistTask, ResourceInfo] = {}

        self.monitor_task = None

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
            instance.running_tasks.append(dl_task)
            instance.task_resource_map[dl_task] = matched_resource

        if (
            instance.monitor_task is None
            or instance.monitor_task.done()
            or instance.monitor_task.cancelled()
        ):
            logger.debug("Createing a new monitor task")
            instance.monitor_task = asyncio.create_task(instance.monitor())

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=0.5, min=1, max=15),
        retry=retry_if_result(lambda x: x is None),
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
            logger.warning(f"Error when getting transfer task list: {e}")
            return None
        # Filter out the transfer tasks by start_time and state
        transfer_task_list = [
            task
            for task in transfer_task_list
            if (
                task.uuid not in self.uuid_set
                and utils.is_video(task.target_path)
                and task.start_time > download_task.start_time
                and task.state
                in [
                    AlistTaskState.Pending,
                    AlistTaskState.Running,
                    AlistTaskState.Succeeded,
                ]
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

    async def monitor(self):
        NORMAL_STATUS = [
            AlistTaskState.Pending,
            AlistTaskState.Running,
            AlistTaskState.StateBeforeRetry,
            AlistTaskState.StateWaitingRetry,
        ]
        while len(self.running_tasks) > 0:
            # 1. Get remote task list
            try:
                new_task_list = await self.alist_client.get_task_list(
                    AlistTaskType.DOWNLOAD
                )
                new_task_list += await self.alist_client.get_task_list(
                    AlistTaskType.TRANSFER
                )
            except Exception as e:
                logger.error(f"Error when getting task list: {e}")
                await asyncio.sleep(1)
                continue

            new_tid_map = {task.tid: task for task in new_task_list}
            # 2. Update running tasks state
            tasks_to_remove = []
            for task in self.running_tasks:

                if task.tid not in new_tid_map:
                    logger.warning(f"Task {task.tid} not found in remote task list")
                    continue

                new_task = new_tid_map[task.tid]
                task.__dict__.update(new_task.__dict__)
                logger.debug(
                    f"Checking {task} state: {task.state} progress: {task.progress:.2f}%"
                )

                # 3. Check if the task is finished
                if task.state == AlistTaskState.Succeeded:
                    # download success
                    if task.task_type == AlistTaskType.DOWNLOAD:
                        # if download task success, find the transfer task and monitor it
                        tf_task = await self._find_transfer_task(task)
                        if tf_task is None:
                            logger.error(
                                f"Can't find transfer task for [{self.task_resource_map[task].resource_title}]"
                            )
                        else:
                            self.running_tasks.append(tf_task)
                            self.task_resource_map[tf_task] = self.task_resource_map[
                                task
                            ]
                    elif task.task_type == AlistTaskType.TRANSFER:
                        # if transfer task success, done it.
                        resource = self.task_resource_map[task]
                        await self._post_process(task, resource)
                    tasks_to_remove.append(task)
                elif task.state not in NORMAL_STATUS:
                    # download failed
                    resource = self.task_resource_map[task]
                    logger.error(
                        f"{type(task)} of [{resource.resource_title}] failed: {task.error}"
                    )
                    await self.db.delete_by_resource_title(resource.resource_title)
                    tasks_to_remove.append(task)

            for task in tasks_to_remove:
                if task in self.running_tasks:
                    self.running_tasks.remove(task)
                if task in self.task_resource_map:
                    del self.task_resource_map[task]

            await asyncio.sleep(1)
