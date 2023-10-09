import os

import feedparser
import pandas as pd

import core.api.alist as alist
from core.database import SubscribeDatabase
from core.logger import Log
from core.rssparser import RssParser


class RssManager:
    """rss feed manager"""

    def __init__(
        self,
        subscribe_url: str,
        download_path: str,
        filter,
        alist: alist.Alist,
        notification_bot=None,
    ) -> None:
        """init the rss feed manager

        Args:
            rss_list (list[rss.Rss]): List rss
            download_path (str): Default path to download torrent file
            alist (alist.Alist): Alist's api handler
        """

        self.subscribe_url = subscribe_url
        self.download_path = download_path
        self.alist_handler = alist
        self.filter = filter
        self.notification_bot = notification_bot
        self.db = SubscribeDatabase()

    def download(self, urls: str, subFolder: str = None) -> None:
        """Download torrent file to subfolder via alist's aria2

        Args:
            urls (list[str]): list of torrent url
            subFolder (str): download to subfloder. Defaults to None.
        """

        download_path = (
            os.path.join(self.download_path, subFolder)
            if subFolder
            else self.download_path
        )
        self.alist_handler.add_aria2(download_path, urls)

    def notify(self, message: str) -> None:
        """Send notification to user

        Args:
            message (str): message to send
        """

        if self.notification_bot:
            self.notification_bot.send_message(message)

    def parse_subscribe(self):
        feed = feedparser.parse(self.subscribe_url)
        if feed.bozo:
            Log.error(
                f"Error when connect to {self.subscribe_url}:\n {feed.bozo_exception}"
            )
            raise ConnectionError(feed.bozo_exception)

        subscribe_info = RssParser.parse_data_frame(feed, self.filter)
        return subscribe_info

    def get_new_anime_info(self, subscribe_info: pd.DataFrame):
        new_anime_info = subscribe_info[~subscribe_info["id"].apply(self.db.is_exist)]
        return new_anime_info

    # def save_checkpoint(self):
    #     with open("checkpoint_time.txt", "w") as f:
    #         f.write(str(self.checkpoint_time))

    def check_update(self):
        """Check if there is new torrent in rss feed,
        if so, add it to aria2 task queue
        """
        Log.debug("Start Update Checking...")
        subscribe_info = self.parse_subscribe()
        new_anime_info = self.get_new_anime_info(subscribe_info)
        if new_anime_info.shape[0] > 0:
            # Download the torrent of new feed
            groups = new_anime_info.groupby("animeName")
            for name, group in groups:
                try:
                    links = group["link"].tolist()
                    self.download(links, name)
                except Exception as e:
                    Log.error(f"Error when downloading {name}:\n {e}")
                    continue
                self.notify(
                    "你订阅的番剧 [{}] 有更新啦:\n{}".format(
                        name, "\n".join(group["title"].tolist())
                    )
                )
                Log.info(f"Start to download: {name}")
                for _, row in group.iterrows():
                    self.db.add_data(
                        row["id"],
                        row["title"],
                        row["link"],
                        str(row["pubDate"]),
                        name,
                    )
        else:
            Log.debug("No new anime found")
