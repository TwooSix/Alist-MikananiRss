import asyncio
import os

from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.websites import ResourceInfo

from ..utils import Singleton


class AnimeRenamer(metaclass=Singleton):
    _lock = asyncio.Lock()

    def __init__(self, alist: Alist, rename_format: str):
        self.alist_client = alist
        self.rename_format = rename_format

    @classmethod
    def initialize(cls, alist: Alist, rename_format: str):
        cls(alist, rename_format)

    async def _build_new_name(self, old_filepath: str, resource: ResourceInfo):
        name = resource.anime_name
        season = resource.season
        episode = resource.episode
        if season is None or episode is None:
            raise ValueError("Season or episode is none when rename")
        fansub = resource.fansub
        quality = resource.quality
        language = resource.language
        old_filedir = os.path.dirname(old_filepath)
        old_filename = os.path.basename(old_filepath)
        file_ext = os.path.splitext(old_filename)[-1].replace(".", "")

        if season == 0:
            # 总集篇/OVA 则以顺序命名
            file_list = await self.alist_client.list_dir(old_filedir, per_page=999)
            episode = len(file_list)

        new_filename = self.rename_format.format(
            name=name,
            season=season,
            episode=episode,
            fansub=fansub,
            quality=quality,
            language=language,
        )
        if resource.version != 1:
            new_filename += f" v{resource.version}"
        new_filename += f".{file_ext}"
        return new_filename

    @classmethod
    async def rename(cls, old_filepath: str, resource: ResourceInfo, max_retry=3):
        if (
            resource.anime_name is None
            or resource.season is None
            or resource.episode is None
        ):
            logger.error(f"rename failed due to resource info is invalid: {resource}")
            return
        instance = cls()
        for i in range(max_retry):
            try:
                new_filename = await instance._build_new_name(old_filepath, resource)
                await instance.alist_client.rename(old_filepath, new_filename)
                logger.info(f"Rename {old_filepath} to {new_filename}")
                break
            except Exception as e:
                if i < max_retry - 1:
                    logger.warning(f"Failed to rename {old_filepath}, retrying...: {e}")
                else:
                    logger.error(f"Error when rename {old_filepath}: {e}")
                await asyncio.sleep(5)
