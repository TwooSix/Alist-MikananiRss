from dataclasses import dataclass

import aiohttp
import bs4

from alist_mikananirss.websites import FeedEntry, ResourceInfo, Website


@dataclass
class MikanHomePageInfo:
    anime_name: str
    fansub: str


class Mikan(Website):
    def __init__(self, rss_url: str):
        super().__init__(rss_url)

    async def parse_homepage(self, home_page_url: str) -> MikanHomePageInfo:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(home_page_url) as response:
                response.raise_for_status()
                html = await response.text()
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

    async def get_feed_entries(self) -> set[FeedEntry]:
        feed = await self.parse_feed(self.rss_url)
        feed_entries = set()
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
            feed_entries.add(feed_entry)
        return feed_entries

    async def extract_resource_info(self, entry: FeedEntry) -> ResourceInfo:
        homepage_info = await self.parse_homepage(entry.homepage_url)
        resource_info = ResourceInfo(
            anime_name=homepage_info.anime_name,
            resource_title=entry.resource_title,
            torrent_url=entry.torrent_url,
            published_date=entry.published_date,
            fansub=homepage_info.fansub,
        )
        return resource_info
