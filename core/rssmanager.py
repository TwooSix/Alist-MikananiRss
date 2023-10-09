import os
import re

import feedparser

import core.api.alist as alist
from core.common.database import SubscribeDatabase
from core.common.logger import Log
from core.mikan import MikanAnimeResource


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

    def download(self, urls: list[str], subFolder: str = None) -> None:
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
        if isinstance(urls, str):
            urls = [urls]
        self.alist_handler.add_aria2(download_path, urls)

    def notify(self, message: str) -> None:
        """Send notification to user

        Args:
            message (str): message to send
        """

        if self.notification_bot:
            self.notification_bot.send_message(message)

    def filt_entries(self, feed: feedparser.FeedParserDict) -> bool:
        """Filter feed entries using regex"""
        match_result = True
        for entry in feed.entries:
            for pattern in self.filter:
                match_result = match_result and re.search(pattern, entry.title)
            if match_result:
                yield entry

    def parse_subscribe(self):
        """Get anime resource from rss feed"""
        feed = feedparser.parse(self.subscribe_url)
        if feed.bozo:
            Log.error(
                f"Error when connect to {self.subscribe_url}:\n {feed.bozo_exception}"
            )
            raise ConnectionError(feed.bozo_exception)
        resources = []
        for entry in self.filt_entries(feed):
            try:
                resource = MikanAnimeResource(entry)
                resources.append(resource)
            except Exception as e:
                Log.error(f"Error when parse rss feed:\n {e}")
                continue
        return resources

    def new_resource(self, resources: list[MikanAnimeResource]):
        """Filter out the new resources from the resource list"""
        for resource in resources:
            if not self.db.is_exist(resource.resource_id):
                yield resource

    # def save_checkpoint(self):
    #     with open("checkpoint_time.txt", "w") as f:
    #         f.write(str(self.checkpoint_time))

    def check_update(self):
        """Check if there is new torrent in rss feed,
        if so, add it to aria2 task queue
        """
        Log.debug("Start Update Checking...")
        resources = self.parse_subscribe()
        update_info = []
        resource_group = {}
        # group resource by anime name
        for resource in self.new_resource(resources):
            if resource.anime_name not in resource_group:
                resource_group[resource.anime_name] = []
            resource_group[resource.anime_name].append(resource)

        for name, resources in resource_group.items():
            # Download the torrent of new feed
            try:
                name = resource.anime_name
                links = [resource.torrent_link for resource in resources]  # noqa
                titles = [resource.resource_title for resource in resources]
                # self.download(links, name)
            except Exception as e:
                Log.error(f"Error when downloading {name}:\n {e}")
                continue
            update_info = update_info + titles
            Log.info("Start to download: \n{}".format("\n".join(titles)))
            # add downloaded resource to database
            for resource in resources:
                self.db.add_data(
                    resource.resource_id,
                    resource.resource_title,
                    resource.torrent_link,
                    str(resource.published_date),
                    resource.anime_name,
                )
        if len(update_info):
            self.notify("你订阅的番剧有更新啦:\n{}".format("\n".join(update_info)))
        else:
            Log.debug("No new anime found")
