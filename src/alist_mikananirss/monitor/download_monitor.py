import asyncio
import time
from typing import Optional

from loguru import logger

from alist_mikananirss import utils
from alist_mikananirss.alist.api import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.common import globalvar
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.downloader import AnimeDownloadTask
from alist_mikananirss.renamer import Renamer
from alist_mikananirss.websites.data import ResourceInfo


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

    async def wait_succeed(self):
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


class AlistDownloadMonitor:
    def __init__(
        self,
        alist: Alist,
        download_path,
        renamer: Renamer = None,
    ):
        self.alist = alist
        self.download_path = download_path
        self.transfer_uuid_set = set()
        self.db = SubscribeDatabase()
        self.use_renamer = renamer is not None
        self.renamer = renamer

    async def find_transfer_task(self, resource: ResourceInfo) -> AlistTransferTask:
        async with asyncio.timeout(10):
            while True:
                try:
                    transfer_task_list = await self.alist.get_task_list(
                        AlistTaskType.TRANSFER
                    )
                    for transfer_task in transfer_task_list:
                        # 查找第一个，未被标记过的番剧名相同的视频文件传输任务作为下载任务对应的传输任务
                        if (
                            transfer_task.uuid not in self.transfer_uuid_set
                            and utils.is_video(transfer_task.file_name)
                            and transfer_task.status
                            in [AlistTaskStatus.Pending, AlistTaskStatus.Running]
                            and resource.anime_name in transfer_task.description
                        ):

                            self.transfer_uuid_set.add(transfer_task.uuid)
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

    async def __monitor_one_task(
        self, task: AnimeDownloadTask
    ) -> Optional[ResourceInfo]:
        """monitor one task until it succeed

        Args:
            resource (MikanAnimeResource): resource need to be monitored

        Returns:
            MikanAnimeResource | None: return the resource if download succeed, else return None
        """
        download_task = task.download_task
        download_task_monitor = TaskMonitor(self.alist, download_task)
        try:
            download_task = await download_task_monitor.wait_succeed()
        except RuntimeError:
            self.alist.cancel_task(download_task)
            logger.error(
                f"Timeout to wait the download task of {task.resource.resource_title} succeed"
            )
            return None
        if download_task.status != AlistTaskStatus.Succeeded:
            logger.error(f"Error when download {task.resource.resource_title}")
            return None

        try:
            transfer_task = await self.find_transfer_task(task.resource)
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout to find the transfer task of {task.resource.resource_title}"
            )
            return None
        transfer_task_monitor = TaskMonitor(self.alist, transfer_task)
        try:
            transfer_task = await transfer_task_monitor.wait_succeed()
        except asyncio.TimeoutError:
            self.alist.cancel_task(transfer_task)
            logger.error(
                f"Timeout to wait the transfer task of {task.resource.resource_title} succeed"
            )
            return None
        if transfer_task.status != AlistTaskStatus.Succeeded:
            logger.error(f"Error when transfer {task.resource.resource_title}")
            return None
        if self.use_renamer:
            old_name = transfer_task.file_name
            asyncio.create_task(self.renamer.rename(old_name, task.resource))
        return task.resource

    async def start_monitor(self, task: AnimeDownloadTask):
        success_resource = await self.__monitor_one_task(task)
        if success_resource is not None:
            await globalvar.success_res_q.put(success_resource)
        else:
            # 下载失败，删除数据库记录
            self.db.delete_by_id(task.resource.rid)

    async def run(self, interval_time: int = 1):
        while True:
            while not globalvar.downloading_res_q.empty():
                task: AnimeDownloadTask = await globalvar.downloading_res_q.get()
                logger.debug(f"Start monitor {task.resource.resource_title}")
                # 开始下载，先插入数据库，避免下次检查时重复下载
                self.db.insert_mikan_resource(task.resource)
                asyncio.create_task(self.start_monitor(task))
            await asyncio.sleep(interval_time)
