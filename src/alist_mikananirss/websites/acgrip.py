import re
from typing import Optional

import aiohttp
import bs4

from alist_mikananirss.extractor import Extractor
from alist_mikananirss.websites.models import FeedEntry, ResourceInfo

from .base import Website


class AcgRip(Website):
    def __init__(self, rss_url: str):
        super().__init__(rss_url)

    async def parse_homepage(self, home_page_url: str) -> Optional[str]:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(home_page_url) as response:
                response.raise_for_status()
                html = await response.text()
        soup = bs4.BeautifulSoup(html, "html.parser")
        fansub_tag = soup.find("a", href=re.compile(r"/team/\d+"))
        if not fansub_tag:
            return None
        fansub = fansub_tag.text
        return fansub

    async def get_feed_entries(self) -> list[FeedEntry]:
        feed = await self.parse_feed(self.rss_url)
        if feed is None:
            return []
        feed_entries = []
        for tmp_entry in feed.entries:
            resource_title = tmp_entry.title
            torrent_url = None
            for link in tmp_entry.links:
                if link["type"] == "application/x-bittorrent":
                    torrent_url = link["href"]
            if not torrent_url:
                raise RuntimeError("No torrent url found")
            homepage_url = tmp_entry.link
            published_date = tmp_entry.published
            feed_entry = FeedEntry(
                resource_title=resource_title,
                torrent_url=torrent_url,
                published_date=published_date,
                homepage_url=homepage_url,
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

            fansub = await self.parse_homepage(entry.homepage_url)

            resource_info = ResourceInfo(
                anime_name=rtitle_extract_result.anime_name,
                season=rtitle_extract_result.season,
                episode=rtitle_extract_result.episode,
                quality=rtitle_extract_result.quality,
                languages=rtitle_extract_result.languages,
                fansub=fansub if fansub else rtitle_extract_result.fansub,
                resource_title=resource_info.resource_title,
                torrent_url=resource_info.torrent_url,
                published_date=resource_info.published_date,
                version=rtitle_extract_result.version,
            )
        return resource_info
