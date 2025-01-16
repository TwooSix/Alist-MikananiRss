from urllib.parse import urlparse

from loguru import logger

from alist_mikananirss import utils
from alist_mikananirss.extractor import Extractor

from .base import Website
from .entities import FeedEntry, ResourceInfo


class DefaultWebsite(Website):
    def __init__(self, rss_url: str):
        super().__init__(rss_url)

    async def get_feed_entries(self) -> list[FeedEntry]:
        feed = await self.parse_feed(self.rss_url)
        if feed is None:
            return []
        feed_entries = []
        for tmp_entry in feed.entries:
            resource_title = tmp_entry.get("title", None)
            torrent_url = None
            for link_entry in tmp_entry.get("links", []):
                # 判断是否是磁力链接
                link = link_entry["href"]
                if link.startswith("magnet:") or link.endswith(".torrent"):
                    torrent_url = link
                    break
                # 判断是否是视频直链
                link_parsed = urlparse(link)
                if utils.is_video(link_parsed.path):
                    torrent_url = link
                    break
            published_date = tmp_entry.get("published", None)

            if not resource_title or not torrent_url:
                logger.error(f"Unsupport rss feed format: {self.rss_url}")
                return []

            feed_entry = FeedEntry(
                resource_title=resource_title,
                torrent_url=torrent_url,
                published_date=published_date,
            )
            feed_entries.append(feed_entry)
        return feed_entries

    async def extract_resource_info(
        self, entry: FeedEntry, use_extractor: bool = False
    ) -> ResourceInfo:
        resource_info = ResourceInfo(
            resource_title=entry.resource_title,
            torrent_url=entry.torrent_url,
            published_date=entry.published_date,
        )
        if use_extractor:
            rtitle_extract_result = await Extractor.analyse_resource_title(
                resource_info.resource_title
            )
            resource_info = ResourceInfo(
                anime_name=rtitle_extract_result.anime_name,
                season=rtitle_extract_result.season,
                episode=rtitle_extract_result.episode,
                quality=rtitle_extract_result.quality,
                language=rtitle_extract_result.language,
                fansub=rtitle_extract_result.fansub,
                resource_title=resource_info.resource_title,
                torrent_url=resource_info.torrent_url,
                published_date=resource_info.published_date,
                version=rtitle_extract_result.version,
            )
        return resource_info
