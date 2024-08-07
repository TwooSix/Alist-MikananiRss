import abc
import asyncio
from concurrent.futures import ThreadPoolExecutor

import feedparser
from loguru import logger

from .entities import FeedEntry, ResourceInfo


class Website(abc.ABC):
    """Website，虚基类，提供从各站点Rss链接中提取资源信息的接口"""

    def __init__(self, rss_url: str):
        self.rss_url = rss_url

    async def parse_feed(self, url):
        """使用feedparser库异步解析rss链接"""
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            try:
                feed = await loop.run_in_executor(pool, feedparser.parse, url)
                return feed
            except Exception as e:
                logger.error(f"Failed to get rss feed: {e}")
                return None

    @abc.abstractmethod
    async def get_feed_entries(self) -> list[FeedEntry]:
        """从rss链接中获取所有的资源条目"""
        pass

    @abc.abstractmethod
    async def extract_resource_info(
        self, entry: FeedEntry, use_extractor: bool = False
    ) -> ResourceInfo:
        """从资源条目中提取番剧资源信息"""
        pass


class WebsiteFactory:
    """Website工厂类，根据rss链接创建对应的Website类"""

    @staticmethod
    def get_website_parser(rss_url: str) -> Website:
        if "mikan" in rss_url:
            from alist_mikananirss.websites import Mikan

            return Mikan(rss_url)
        else:
            raise ValueError("Unknown website")
