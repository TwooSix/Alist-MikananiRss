import os

from loguru import logger

from alist_mikananirss.alist.api import Alist
from alist_mikananirss.mikan import MikanAnimeResource


class Renamer:
    def __init__(self, alist: Alist, download_path: str):
        self.alist = alist
        self.download_path = download_path

    async def __build_new_name(self, resource: MikanAnimeResource, old_filename: str):
        name = resource.anime_name
        season = resource.season
        episode = resource.episode
        ext = old_filename.split(".")[-1]
        if season == 0:
            # 总集篇/OVA 则以顺序命名
            abs_dir_path = os.path.join(self.download_path, name, f"Season {season}")
            file_list = await self.alist.list_dir(abs_dir_path, per_page=999)
            episode = len(file_list)
        new_filename = f"{name} S{season:02}E{episode:02}.{ext}"
        return new_filename

    async def rename(self, old_filename: str, resource: MikanAnimeResource):
        name, season = resource.anime_name, resource.season
        abs_filepath = os.path.join(
            self.download_path, name, f"Season {season}", old_filename
        )
        new_filename = await self.__build_new_name(resource, old_filename)
        try:
            await self.alist.rename(abs_filepath, new_filename)
        except Exception as e:
            logger.error(f"Error when rename {abs_filepath}: {e}")
        logger.info(f"Rename {abs_filepath} to {new_filename}")
