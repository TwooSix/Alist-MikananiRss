import asyncio
import os
import string

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
        data = {
            "name": name,
            "season": season,
            "episode": episode,
            "ext": file_ext,
            "fansub": fansub,
            "quality": quality,
            "language": language,
        }
        data = {k: v for k, v in data.items() if v is not None}
        formatter = string.Formatter()
        result = []
        for literal_text, field_name, format_spec, _ in formatter.parse(
            self.rename_format
        ):
            if literal_text:
                result.append(literal_text)
            if field_name in data:
                value = data[field_name]
                value = format(value, format_spec)
                result.append(str(value))
        new_filename = "".join(result).strip()
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
