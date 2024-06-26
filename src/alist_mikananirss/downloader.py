import asyncio
import os

from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.offline_download import TaskList
from alist_mikananirss.common.globalvar import downloading_res_q, new_res_q
from alist_mikananirss.mikan import MikanAnimeResource


class AlistDownloader:
    def __init__(self, alist: Alist, use_renamer: bool) -> None:
        self.alist = alist
        self.use_renamer = use_renamer

    def __group_resources(self, resources: list[MikanAnimeResource]):
        """group resources by anime name and season"""
        resource_group: dict[str, dict[str, list[MikanAnimeResource]]] = {}
        for resource in resources:
            if resource.anime_name not in resource_group:
                resource_group[resource.anime_name] = {}
            if resource.season not in resource_group[resource.anime_name]:
                resource_group[resource.anime_name][resource.season] = []
            resource_group[resource.anime_name][resource.season].append(resource)
        return resource_group

    async def run(self, download_path: str, interval_time: int = 10):
        first_run = True
        while True:
            if not first_run:
                await asyncio.sleep(interval_time)
            new_resources = []
            while not new_res_q.empty():
                new_resources.append(await new_res_q.get())
            if new_resources:
                try:
                    downloading_resources = await self.download(
                        new_resources, download_path
                    )
                except Exception as e:
                    logger.error(f"Error when download: {e}")
                    continue
                for resource in downloading_resources:
                    logger.info(f"Start to download: {resource.resource_title}")
                    await downloading_res_q.put(resource)
            first_run = False

    def __prepare_download(self, new_resources, download_path: str):
        """Get DownloadPath: [url1, url2, ...] mapping from new_resources"""
        resrouce_group = self.__group_resources(new_resources)
        path_urls = {}
        for anime_name, season_group in resrouce_group.items():
            for season, season_resources in season_group.items():
                if self.use_renamer:
                    subfolder = os.path.join(anime_name, f"Season {season}")
                else:
                    subfolder = anime_name
                fin_path = os.path.join(download_path, subfolder)
                path_urls[fin_path] = [
                    resource.torrent_url for resource in season_resources
                ]
        return path_urls

    async def download(
        self, new_resources: list[MikanAnimeResource], download_path: str
    ):
        """Create alist offline download task

        Args:
            new_resources (list[MikanAnimeResource]): resources list
            download_path (str): remote path

        Returns:
            list[MikanAnimeResource]: resources that download task created successfully
        """
        path_urls = self.__prepare_download(new_resources, download_path)
        task_list = TaskList()
        for _download_path, urls in path_urls.items():
            try:
                tmp_task_list = await self.alist.add_offline_download_task(
                    _download_path, urls
                )
            except Exception as e:
                logger.error(f"Error when add offline download task: {e}")
                continue
            task_list = task_list + tmp_task_list
        # link resource with task
        success_resources = []
        for resource in new_resources:
            for task in task_list:
                if resource.torrent_url == task.url:
                    resource.set_download_task(task)
                    success_resources.append(resource)
                    break
        return success_resources
