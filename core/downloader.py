import os

from loguru import logger

from core.alist import Alist
from core.alist.offline_download import TaskList
from core.mikan import MikanAnimeResource


class AlistDownloader:
    def __init__(self, alist: Alist) -> None:
        self.alist = alist

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

    async def download(self, root_path: str, new_resources: list[MikanAnimeResource]):
        resrouce_group = self.__group_resources(new_resources)
        task_list = TaskList()

        for anime_name, season_group in resrouce_group.items():
            for season, season_resources in season_group.items():
                subfolder = os.path.join(anime_name, f"Season {season}")
                download_path = os.path.join(root_path, subfolder)
                urls = [resource.torrent_url for resource in season_resources]
                try:
                    tmp_task_list = await self.alist.add_offline_download_task(
                        download_path, urls
                    )
                except Exception as e:
                    logger.error(f"Error when add offline download task: {e}")
                    continue
                task_list = task_list + tmp_task_list

        success_resources = []
        for resource in new_resources:
            for task in task_list:
                if resource.torrent_url == task.url:
                    resource.set_download_task(task)
                    success_resources.append(resource)
                    logger.info(f"Start to download: {resource.resource_title}")
                    break
        return success_resources
