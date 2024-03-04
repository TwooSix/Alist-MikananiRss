import asyncio
import os
import re

from loguru import logger

from core.alist.api import Alist
from core.common import initializer
from core.mikan import MikanAnimeResource


class Renamer:
    def __init__(self, alist: Alist, download_path: str):
        self.alist = alist
        self.download_path = download_path
        self.chatgpt = initializer.init_chatgpt_client()

    def __find_wrong_format_videos(self, filename_list):
        video_extensions = ["mp4", "mkv", "MP4", "MKV"]
        video_ext_regex = r".*\.({})$".format("|".join(video_extensions))
        format_pattern = r".+ S\d+E\d+\..{3,4}"  # find correct format video files

        video_files = [
            s for s in filename_list if re.match(video_ext_regex, s, re.IGNORECASE)
        ]
        wrong_format_videos = [
            s for s in video_files if not re.match(format_pattern, s, re.IGNORECASE)
        ]
        return wrong_format_videos

    def __get_rename_files(self, dir_path, file_list) -> list[str]:
        wrong_format_videos = self.__find_wrong_format_videos(file_list)
        filepath_rename = [os.path.join(dir_path, s) for s in wrong_format_videos]
        return filepath_rename

    async def __build_new_name(self, old_filename:str, resource: MikanAnimeResource, file_count:int):
        name, season, episode = resource.anime_name, resource.season, resource.episode
        ext = old_filename.split(".")[-1]
        if season == 0:
            # 总集篇/特别篇以播出顺序排序命名
            new_name = f"{name} S{season:02}E{file_count:02}.{ext}"
        else:
            # 正常集数按照季数和集数排序命名
            new_name = f"{name} S{season:02}E{episode:02}.{ext}"
        return new_name

    async def rename(self, resource: MikanAnimeResource):
        while True:
            name, season = resource.anime_name, resource.season
            try:
                dir_path = os.path.join(self.download_path, name, f"Season {season}")
                file_list = await self.alist.list_dir(dir_path)
                filepath_rename = await self.__get_rename_files(
                    dir_path, file_list
                )
            except Exception as e:
                logger.error(f"Error when get file path: {e}")
                await asyncio.sleep(1)
                continue
            done_flag = True
            error_flag = False
            for filepath in filepath_rename:
                new_name = await self.__build_new_name(filepath, resource, len(file_list))
                if new_name is None:
                    done_flag = False
                    continue
                try:
                    await self.alist.rename(filepath, new_name)
                except Exception as e:
                    logger.error(f"Error when rename {filepath}: {e}")
                    error_flag = True
                    continue
                logger.info(f"Rename {filepath} to {new_name}")
            if done_flag:
                return not error_flag
            await asyncio.sleep(1)
