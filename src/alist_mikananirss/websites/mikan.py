import asyncio
from dataclasses import dataclass

import aiohttp
import bs4
from async_lru import alru_cache

from alist_mikananirss.extractor import Extractor
from alist_mikananirss.websites import FeedEntry, ResourceInfo, Website


@dataclass
class MikanHomePageInfo:
    anime_name: str
    fansub: str


class Mikan(Website):
    def __init__(self, rss_url: str):
        super().__init__(rss_url)

    @alru_cache(maxsize=1024)
    async def parse_homepage(self, home_page_url: str) -> MikanHomePageInfo:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(home_page_url) as response:
                response.raise_for_status()
                html = await response.text()
                await asyncio.sleep(1)
        soup = bs4.BeautifulSoup(html, "html.parser")
        anime_name = soup.find("p", class_="bangumi-title").text.strip()
        fansub = None
        bgm_info_elements = soup.find_all("p", class_="bangumi-info")
        for e in bgm_info_elements:
            if "字幕组" in e.text:
                text = e.text.strip()
                fansub = text.split("：")[-1]
                break
        return MikanHomePageInfo(anime_name=anime_name, fansub=fansub)

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
        homepage_info = await self.parse_homepage(entry.homepage_url)
        resource_info = ResourceInfo(
            anime_name=homepage_info.anime_name,
            resource_title=entry.resource_title,
            torrent_url=entry.torrent_url,
            published_date=entry.published_date,
            fansub=homepage_info.fansub,
        )
        if use_extractor:
            name_extract_result = await Extractor.analyse_anime_name(
                resource_info.anime_name
            )
            rtitle_extract_result = await Extractor.analyse_resource_title(
                resource_info.resource_title
            )
            resource_info = ResourceInfo(
                anime_name=name_extract_result.anime_name,
                season=name_extract_result.season,
                episode=rtitle_extract_result.episode,
                quality=rtitle_extract_result.quality,
                language=rtitle_extract_result.language,
                fansub=resource_info.fansub,
                resource_title=resource_info.resource_title,
                torrent_url=resource_info.torrent_url,
                published_date=resource_info.published_date,
                version=rtitle_extract_result.version,
            )
        return resource_info
