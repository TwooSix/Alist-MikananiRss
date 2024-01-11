import threading
import time
from queue import Queue

import feedparser
from loguru import logger

from core.api.alist import Alist, Aria2TaskStatus
from core.common.database import SubscribeDatabase
from core.common.filters import RegexFilter
from core.mikan import MikanAnimeResource


class AlistDonwloadMonitor(threading.Thread):
    def __init__(
        self,
        alist: Alist,
        download_queue: Queue,
        success_queue: Queue,
        download_path: str,
    ):
        super().__init__(daemon=True)
        self.alist = alist
        self.download_queue = download_queue
        self.success_queue = success_queue
        self.download_path = download_path
        self.db = SubscribeDatabase()

    def get_task_status(self, url):
        flag, task_list = self.alist.get_aria2_task_list()
        if not flag:
            return None

        for task in task_list:
            if task.url == url and task.status not in [
                Aria2TaskStatus.UNKNOWN,
                Aria2TaskStatus.ERROR,
            ]:
                return task.status
        return None

    def run(self):
        while True:
            resource: MikanAnimeResource = self.download_queue.get()
            if resource is None:
                time.sleep(60)
            resource_url = resource.torrent_url
            status = self.get_task_status(resource_url)
            if status is None:
                logger.error(f"Error when get task status of {resource_url}")
                self.download_queue.put(resource)
                continue
            logger.debug(f"Checking Task {resource_url} status: {status}")
            if status == Aria2TaskStatus.DONE:
                self.success_queue.put(resource)
                self.download_queue.task_done()
            elif status == Aria2TaskStatus.ERROR:
                # delete the failed resource from database
                self.db.delete_by_id(resource.resource_id)
                self.download_queue.task_done()
                logger.error(f"Error when download {resource_url}")
            else:
                self.download_queue.put(resource)


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

    def __parse_subscribe(self):
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
                resource = MikanAnimeResource.from_feed_entry(entry)
                resources.append(resource)
            except Exception as e:
                logger.error(f"Pass {entry.title} because of error: {e}")
                continue
        return resources

    def get_new_resource(self):
        """Filter out the new resources from the resource list"""
        resources = self.__parse_subscribe()
        new_resources = []
        for resource in resources:
            if not self.db.is_exist(resource.resource_id):
                new_resources.append(resource)
        return new_resources
