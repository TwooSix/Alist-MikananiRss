import os

from loguru import logger

from alist_mikananirss.alist.api import Alist
from alist_mikananirss.websites.data import ResourceInfo


class Renamer:
    def __init__(
        self,
        alist: Alist,
        download_path: str,
        rename_format: str = None,
    ):
        self.alist = alist
        self.download_path = download_path
        if rename_format is None:
            self.rename_format = "{name} S{season:02d}E{episode:02d}.{ext}"
        else:
            self.rename_format = rename_format

    async def __build_new_name(self, resource: ResourceInfo, old_filename: str):
        name = resource.anime_name
        season = resource.season
        episode = resource.episode
        fansub = resource.fansub
        quality = resource.quality
        language = resource.language
        ext = old_filename.split(".")[-1]
        if season == 0:
            # 总集篇/OVA 则以顺序命名
            abs_dir_path = os.path.join(self.download_path, name, f"Season {season}")
            file_list = await self.alist.list_dir(abs_dir_path, per_page=999)
            episode = len(file_list)
        data = {
            "name": name,
            "season": season,
            "episode": episode,
            "ext": ext,
            "fansub": fansub,
            "quality": quality,
            "language": language,
        }
        new_filename = self.rename_format.format_map(data)
        return new_filename

    async def rename(self, old_filename: str, resource: ResourceInfo, max_retry=3):
        name, season = resource.anime_name, resource.season
        abs_filepath = os.path.join(
            self.download_path, name, f"Season {season}", old_filename
        )
        new_filename = await self.__build_new_name(resource, old_filename)
        for i in range(max_retry):
            try:
                await self.alist.rename(abs_filepath, new_filename)
                logger.info(f"Rename {abs_filepath} to {new_filename}")
                break
            except Exception as e:
                if i < max_retry - 1:
                    logger.warning(f"Failed to rename {abs_filepath}, retrying...: {e}")
                else:
                    logger.error(f"Error when rename {abs_filepath}: {e}")
