import os

import pandas as pd

import core.api.alist as alist
import logging
import feedparser
from .parser import Parser

logger = logging.getLogger(__name__)


class Manager:
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
        try:
            with open("checkpoint_time.txt", "r") as f:
                self.checkpoint_time = pd.to_datetime(
                    f.read(), format="mixed", utc=True
                )
        except FileNotFoundError:
            self.checkpoint_time = pd.to_datetime(
                "1970-01-01 00:00:00", format="mixed", utc=True
            )
        except Exception as e:
            logger.error(f"Unkonwn Error when load checkpoint_time: {e}")
            exit(1)

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
            logger.error(
                f"Error when connect to {self.subscribe_url}: {feed.bozo_exception}"
            )
            raise ConnectionError(feed.bozo_exception)

        subscribe_info = Parser.parseDataFrame(feed, self.filter)
        return subscribe_info

    def get_new_anime_info(self, subscribe_info):
        new_anime_info = subscribe_info[
            subscribe_info["pubDate"] > self.checkpoint_time
        ]
        return new_anime_info

    def save_checkpoint(self):
        with open("checkpoint_time.txt", "w") as f:
            f.write(str(self.checkpoint_time))

    def check_update(self):
        """Check if there is new torrent in rss feed,
        if so, add it to aria2 task queue
        """
        logger.info("Start Update Checking...")
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
                    logger.error(f"Error when downloading {name}: {e}")
                    continue
                self.notify(
                    "你订阅的番剧 [{}] 有更新啦:\n{}".format(
                        name, "\n".join(group["title"].tolist())
                    )
                )
                logger.info(f"Start to download: {name}")
                latest_time = group["pubDate"].max()
                self.checkpoint_time = (
                    latest_time
                    if latest_time > self.checkpoint_time
                    else self.checkpoint_time
                )
        else:
            logger.info("No new anime found")
        self.save_checkpoint()
