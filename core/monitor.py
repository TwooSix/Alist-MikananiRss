from queue import Queue
from threading import Event

import feedparser
from loguru import logger

from core.alist.api import Alist
from core.alist.offline_download import Task, TaskStatus
from core.common.database import SubscribeDatabase
from core.common.filters import RegexFilter
from core.common.globalvar import executor
from core.mikan import MikanAnimeResource
from core.renamer import RenamerThread


class AlistDownloadMonitor:
    def __init__(
        self,
        alist: Alist,
        download_queue: Queue,
        success_download_queue: Queue,
        download_path,
        use_renamer=False,
    ):
        self.alist = alist
        self.download_queue = download_queue
        self.success_download_queue = success_download_queue
        self.download_path = download_path
        self.db = SubscribeDatabase()  # 假设这是已经定义的
        self.use_renamer = use_renamer
        self.transfer_uuid_set = set()
        self.keep_running = Event()
        self.keep_running.set()
        self._is_running = False
        self.future = None
        if use_renamer:
            self.renamer = RenamerThread(
                self.alist, self.download_path, self.success_download_queue
            )

    def __get_task_status(self, tid) -> TaskStatus:
        flag, task_list = self.alist.get_offline_download_task_list()
        if not flag:
            return None
        task: Task = task_list[tid]
        if task is None:
            return None
        return task.status

    def __proccess_finished_task(self, resource: MikanAnimeResource):
        download_task = resource.download_task
        flag, transfer_task_list = self.alist.get_offline_transfer_task_list()
        if not flag:
            logger.error(
                f"Error when get transfer task list of {resource.resource_title}"
            )
            self.download_queue.put(resource)
            return
        if not download_task.is_started_transfer:
            # 初始化下载任务对应的传输任务（使用新的未出现过的tempdir名称，即uuid建立关联）
            for transfer_task in transfer_task_list:
                if transfer_task.uuid in self.transfer_uuid_set:
                    continue
                if transfer_task.status in [TaskStatus.Pending, TaskStatus.Running]:
                    self.transfer_uuid_set.add(transfer_task.uuid)
                    download_task.add_transfer_task(transfer_task)
                    download_task.set_started_transfer(transfer_task.uuid)
                    logger.debug(
                        f"Link {resource.resource_title} to {transfer_task.uuid}"
                    )
                    break
            if not download_task.is_started_transfer:
                # maybe the transfer task is finished
                for transfer_task in transfer_task_list:
                    if (
                        transfer_task.status == TaskStatus.Succeeded
                        and resource.anime_name in transfer_task.description
                    ):
                        self.transfer_uuid_set.add(transfer_task.uuid)
                        download_task.add_transfer_task(transfer_task)
                        download_task.set_started_transfer(transfer_task.uuid)
                        logger.debug(
                            f"Link {resource.resource_title} to {transfer_task.uuid}"
                        )
                        break
            if not download_task.is_started_transfer:
                logger.error(
                    f"Can't find the transfer task of {resource.resource_title}"
                )
                self.download_queue.task_done()
            else:
                self.download_queue.put(resource)
            return
        else:
            # 添加新的正在运行的传输任务
            for transfer_task in transfer_task_list:
                if transfer_task.uuid != download_task.uuid:
                    continue
                if transfer_task.tid in download_task.transfer_task_id:
                    continue
                if transfer_task.status in [TaskStatus.Pending, TaskStatus.Running]:
                    download_task.add_transfer_task(transfer_task)
            if len(download_task.transfer_task_id) == 0:
                # 没有对应的传输任务了，则判断下载任务完成
                self.download_queue.task_done()
                return
            need_remove = []
            # 遍历下载任务对应的所有传输任务，判断其状态并进行相应的处理
            for ttid in download_task.transfer_task_id:
                transfer_task = transfer_task_list[ttid]
                if transfer_task is None:
                    logger.warning(f"Can't find the transfer task: {ttid}")
                    continue
                if transfer_task.status == TaskStatus.Errored:
                    need_remove.append(ttid)
                elif transfer_task.status == TaskStatus.Succeeded:
                    need_remove.append(ttid)
                    self.success_download_queue.put(resource)
                    if self.use_renamer and not self.renamer.is_running():
                        self.renamer.start()
                else:
                    continue
            # 移除出错/已完成的任务
            for need_remove_id in need_remove:
                download_task.transfer_task_id.remove(need_remove_id)
            self.download_queue.put(resource)

    def __proccess_error_task(self, resource: MikanAnimeResource):
        self.db.delete_by_id(resource.resource_id)
        self.download_queue.task_done()
        logger.error(f"Error when download {resource}")

    def run(self):
        while self.keep_running.is_set():
            if self.download_queue.empty():
                if self.use_renamer and self.renamer.is_running():
                    self.renamer.wait()
                logger.debug(
                    "No more downloading task, exit the download monitor thread"
                )
                break  # no more downloading task, exit the thread
            resource: MikanAnimeResource = self.download_queue.get(block=False)
            task = resource.download_task
            if task is None:
                logger.error(
                    f"Can't find the download task of {resource.resource_title}"
                )
                self.download_queue.task_done()
                continue

            status = self.__get_task_status(task.tid)
            if status is None:
                logger.warning(f"Can't get task status of {resource.resource_title}")
                self.download_queue.put(resource)
                continue
            task.update_status(status)  # update只是为了方便显示Transferring状态
            logger.debug(
                f"Checking Task {resource.resource_title} status: {task.status.name}"
            )
            if status == TaskStatus.Errored:
                self.__proccess_error_task(resource)
            elif status == TaskStatus.Succeeded:  # 下载完成，并非传输完成
                self.__proccess_finished_task(resource)
            else:
                self.download_queue.put(resource)
        self._is_running = False

    def start(self):
        if self.future is None or self.future.done():
            self.future = executor.submit(self.run)
            self._is_running = True

    def wait(self):
        if self.future:
            self.future.result()  # 等待任务完成

    def is_running(self):
        return self._is_running


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
