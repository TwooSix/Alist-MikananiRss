import asyncio

import feedparser
from loguru import logger

from core.alist.api import Alist
from core.alist.offline_download import DownloadTask, TaskStatus, TransferTask
from core.common.database import SubscribeDatabase
from core.common.filters import RegexFilter
from core.mikan import MikanAnimeResource
from core.renamer import Renamer


class TaskMonitor:
    normal_status = [
        TaskStatus.Pending,
        TaskStatus.Running,
        TaskStatus.StateBeforeRetry,
        TaskStatus.StateWaitingRetry,
    ]

    def __init__(self, alist: Alist, task: DownloadTask | TransferTask):
        self.alist = alist
        self.task = task

    async def __refresh_status(self) -> TaskStatus:
        if isinstance(self.task, DownloadTask):
            task_list = await self.alist.get_offline_download_task_list()
        elif isinstance(self.task, TransferTask):
            task_list = await self.alist.get_offline_transfer_task_list()
        else:
            raise ValueError(f"Invalid task type: {type(self.task)}")
        if self.task not in task_list:
            raise ValueError(f"Can't find {self.task} in task list")
        status = task_list[self.task.tid].status
        self.task.update_status(status)
        return self.task.status

    async def wait_succeed(self):
        while True:
            try:
                status = await self.__refresh_status()
            except Exception as e:
                logger.error(f"Error when refresh status: {e}")
                await asyncio.sleep(1)
                continue
            logger.debug(f"Checking {self.task} status: {status}")
            if status not in self.normal_status:
                return status
            await asyncio.sleep(1)


class AlistDownloadMonitor:
    def __init__(
        self,
        alist: Alist,
        download_path,
        use_renamer=False,
    ):
        self.alist = alist
        self.download_path = download_path
        self.use_renamer = use_renamer
        self.transfer_uuid_set = set()
        if use_renamer:
            self.renamer = Renamer(alist, download_path)

    async def find_transfer_task(self, resource: MikanAnimeResource):
        while True:
            download_task = resource.download_task
            try:
                transfer_task_list = await self.alist.get_offline_transfer_task_list()
            except Exception as e:
                logger.error(f"Error when get transfer task list: {e}")
                await asyncio.sleep(1)
                continue
            # 使用新的未出现过的tempdir名称，即uuid，与下载任务建立关联
            for transfer_task in transfer_task_list:
                if transfer_task.uuid in self.transfer_uuid_set:
                    continue
                if transfer_task.status in [TaskStatus.Pending, TaskStatus.Running] and resource.anime_name in transfer_task.description:
                    self.transfer_uuid_set.add(transfer_task.uuid)
                    logger.debug(
                        f"Link {resource.resource_title} to {transfer_task.uuid}"
                    )
                    return transfer_task
            if not download_task.is_started_transfer:
                logger.error(
                    f"Can't find the transfer task of {resource.resource_title}"
                )
            await asyncio.sleep(1)

    async def monitor_one_task(self, resource: MikanAnimeResource):
        download_task = resource.download_task
        download_task_monitor = TaskMonitor(self.alist, download_task)
        status = await download_task_monitor.wait_succeed()
        if status != TaskStatus.Succeeded:
            logger.error(f"Error when download {resource.resource_title}")
            return None
        try:
            # 10s内未能找到对应的transfer task，则认为传输失败
            transfer_task = await asyncio.wait_for(
                self.find_transfer_task(resource), timeout=10
            )
        except asyncio.TimeoutError:
            logger.error(f"Can't find the transfer task of {resource.resource_title}")
            return None
        transfer_task_monitor = TaskMonitor(self.alist, transfer_task)
        status = await transfer_task_monitor.wait_succeed()
        if status != TaskStatus.Succeeded:
            logger.error(f"Error when transfer {resource.resource_title}")
            return None
        if self.use_renamer:
            await self.renamer.rename(resource)
        return resource

    async def wait_succeed(self, resrouces):
        results = await asyncio.gather(
            *[self.monitor_one_task(resource) for resource in resrouces]
        )
        success_resources = [r for r in results if r is not None]
        return success_resources


class MikanRSSMonitor:
    def __init__(
        self,
        subscribe_url: str,
        filter: RegexFilter,
    ) -> None:
        """The rss feed manager

        Args:
            rss_list (list[rss.Rss]): List rss
            subscribe_url (str): Mikan subscribe url
            filter (RegexFilter): Filter to filter out the resource
        """

        self.subscribe_url = subscribe_url
        self.filter = filter
        self.db = SubscribeDatabase()

    def __filt_entries(self, feed):
        """Filter feed entries"""
        for entry in feed.entries:
            filt_result = self.filter.filt_single(entry.title)
            if filt_result:
                yield entry

    async def __parse_subscribe(self):
        """Get anime resource from rss feed"""
        feed = feedparser.parse(self.subscribe_url)
        if feed.bozo:
            logger.error(
                f"Error when connect to {self.subscribe_url}:\n {feed.bozo_exception}"
            )
            raise ConnectionError(feed.bozo_exception)
        resources: list[MikanAnimeResource] = []
        for entry in self.__filt_entries(feed):
            try:
                resource = await MikanAnimeResource.from_feed_entry(entry)
                resources.append(resource)
            except Exception as e:
                logger.error(f"Pass {entry.title} because of error: {e}")
                continue
        return resources

    async def get_new_resource(self):
        """Filter out the new resources from the resource list"""
        resources = await self.__parse_subscribe()
        new_resources = []
        for resource in resources:
            if not self.db.is_exist(resource.resource_id):
                new_resources.append(resource)
        return new_resources

    def mark_downloaded(self, resources: list[MikanAnimeResource]):
        for resource in resources:
            self.db.insert_mikan_resource(resource)
