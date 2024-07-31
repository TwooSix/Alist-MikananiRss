import asyncio
import os

from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.websites import ResourceInfo


class AnimeRenamer:
    _instance = None
    _lock = asyncio.Lock()
    alist_client: Alist = None
    rename_format: str = "{name} S{season:02d}E{episode:02d}.{ext}"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AnimeRenamer, cls).__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, alist: Alist, rename_format: str = None):
        instance = cls()
        instance.alist_client = alist
        if rename_format is not None:
            instance.rename_format = rename_format

    async def _build_new_name(self, old_filepath: str, resource: ResourceInfo):
        name = resource.anime_name
        season = resource.season
        episode = resource.episode
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
        data = {
            "name": name,
            "season": season,
            "episode": episode,
            "ext": file_ext,
            "fansub": fansub,
            "quality": quality,
            "language": language,
        }
        new_filename = self.rename_format.format_map(data)
        return new_filename

    @classmethod
    async def rename(cls, old_filepath: str, resource: ResourceInfo, max_retry=3):
        instance = cls()
        new_filename = await instance._build_new_name(old_filepath, resource)
        for i in range(max_retry):
            try:
                await instance.alist_client.rename(old_filepath, new_filename)
                logger.info(f"Rename {old_filepath} to {new_filename}")
                break
            except Exception as e:
                if i < max_retry - 1:
                    logger.warning(f"Failed to rename {old_filepath}, retrying...: {e}")
                else:
                    logger.error(f"Error when rename {old_filepath}: {e}")
