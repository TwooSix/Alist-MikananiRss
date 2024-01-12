import os
import re
import threading
from queue import Queue

from loguru import logger

from core.api.alist import Alist
from core.common import config_loader
from core.common.extractor import ChatGPT
from core.mikan import MikanAnimeResource


class RenamerThread(threading.Thread):
    def __init__(self, alist: Alist, download_path: str, rename_queue: Queue):
        super().__init__(daemon=True)
        self.alist = alist
        self.rename_queue = rename_queue
        self.download_path = download_path
        api_key = config_loader.get_chatgpt_api_key()
        base_url = config_loader.get_chatgpt_base_url()
        model = config_loader.get_chatgpt_model()
        self.chatgpt = ChatGPT(api_key, base_url, model)

    def add_rename_task(self, resource: MikanAnimeResource):
        self.rename_queue.put(resource)

    def find_wrong_format_videos(self, filename_list):
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

    def __get_file_path(self, name, season, download_path) -> list[str]:
        dir_path = os.path.join(download_path, name, f"Season {season}")
        flag, data = self.alist.list_dir(dir_path)
        if not flag:
            return []
        file_list = data
        wrong_format_videos = self.find_wrong_format_videos(file_list)
        filepath_rename = [os.path.join(dir_path, s) for s in wrong_format_videos]
        return filepath_rename

    def __build_new_name(self, name, season, filename):
        try:
            res = self.chatgpt.analyse_resource_name(filename)
        except Exception as e:
            logger.error(f"Error when analyse {filename}: {e}")
            return None
        ext = filename.split(".")[-1]
        episode = res["episode"]
        new_name = f"{name} S{season:02}E{episode:02}.{ext}"
        return new_name

    def run(self):
        while True:
            if self.rename_queue.empty():
                logger.debug("No more rename task, exit the rename thread")
                break  # no more renaming task, exit the thread
            resource: MikanAnimeResource = self.rename_queue.get(block=False)
            name, season = resource.anime_name, resource.season
            filepath_rename = self.__get_file_path(name, season, self.download_path)
            done_flag = True
            for filepath in filepath_rename:
                new_name = self.__build_new_name(name, season, filepath)
                if new_name is None:
                    done_flag = False
                    break  # break而非continue是因为每个任务按理只对应一个文件，避免把其他任务的文件重命名了导致任务无法结束
                flag, msg = self.alist.rename(filepath, new_name)
                if not flag:
                    logger.error(f"Error when rename {filepath}:\n {msg}")
                    break
                logger.info(f"Rename {filepath} to {new_name}")
            if done_flag:
                self.rename_queue.task_done()
            else:
                self.rename_queue.put(resource)
