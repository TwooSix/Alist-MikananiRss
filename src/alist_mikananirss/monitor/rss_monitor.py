import asyncio

from loguru import logger

from alist_mikananirss.common import globalvar
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.extractor import Extractor
from alist_mikananirss.filters import RegexFilter
from alist_mikananirss.websites.base import WebsiteFactory
from alist_mikananirss.websites.data import FeedEntry, ResourceInfo


class RssMonitor:
    def __init__(
        self,
        subscribe_urls: list[str] | str,
        filter: RegexFilter,
        extractor: Extractor = None,
    ) -> None:
        """The rss feed manager"""
        if not isinstance(subscribe_urls, list):
            subscribe_urls = [subscribe_urls]
        self.subscribe_urls = subscribe_urls
        self.websites = [
            WebsiteFactory.get_website_parser(url) for url in subscribe_urls
        ]
        self.filter = filter
        self.extractor = extractor
        self.db = SubscribeDatabase()

    async def get_new_resource(self, fileter: RegexFilter):
        new_resources: list[ResourceInfo] = []
        for website in self.websites:
            feed_entries = await website.get_feed_entries()
            feed_entries_filted: list[FeedEntry] = []
            for entry in feed_entries:
                flag = fileter.filt_single(entry.resource_title)
                if flag:
                    feed_entries_filted.append(entry)

            for entry in feed_entries_filted:
                if not self.db.is_exist(entry.rid):
                    resourcec = await website.extract_resource_info(entry)
                    new_resources.append(resourcec)
        return new_resources

    async def run(self, interval_time):
        while 1:
            logger.info("Start update checking")
            new_resources = await self.get_new_resource(fileter=self.filter)
            if not new_resources:
                logger.info("No new resources")
            else:
                for resource in new_resources:
                    if self.extractor:
                        await self.extractor.process(resource)
                    await globalvar.new_res_q.put(resource)
            await asyncio.sleep(interval_time)
