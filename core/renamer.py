import asyncio
import os
import re

from loguru import logger

from core.alist.api import Alist
from core.mikan import MikanAnimeResource


class Renamer:
    def __init__(self, alist: Alist, download_path: str):
        self.alist = alist
        self.download_path = download_path

    async def __build_new_name(self, resource: MikanAnimeResource, local_title: str):
        name = resource.anime_name
        season = resource.season
        episode = resource.episode
        ext = local_title.split(".")[-1]
        new_name = f"{name} S{season:02}E{episode:02}.{ext}"
        return new_name

    async def rename(self, local_title: str, resource: MikanAnimeResource):
        while True:
            name, season = resource.anime_name, resource.season
            filepath = os.path.join(
                self.download_path, name, f"Season {season}", local_title
            )
            done_flag = True
            error_flag = False
            new_name = await self.__build_new_name(resource, local_title)
            try:
                await self.alist.rename(filepath, new_name)
            except Exception as e:
                logger.error(f"Error when rename {filepath}: {e}")
                error_flag = True
            logger.info(f"Rename {filepath} to {new_name}")
            if done_flag:
                return not error_flag
            await asyncio.sleep(1)
