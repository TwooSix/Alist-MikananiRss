import time

import aiohttp
import bs4

from core.alist.offline_download import DownloadTask
from core.common import extractor


def get_torrent_url(feed_entry) -> str:
    for link in feed_entry.links:
        if link["type"] == "application/x-bittorrent":
            return link["href"]


async def get_anime_name(feed_entry) -> str:
    home_page_url = feed_entry.link
    # craw the anime name from homepage
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(home_page_url) as response:
            response.raise_for_status()
            time.sleep(1)
            soup = bs4.BeautifulSoup(await response.text(), "html.parser")
            anime_name = soup.find("p", class_="bangumi-title").text.strip()
            soup.decompose()
    return anime_name


def process_anime_name(anime_name: str) -> dict:
    """Process the anime name, get the real name and season"""
    regex_extractor = extractor.Regex()
    res = regex_extractor.analyse_anime_name(anime_name)
    return res


class MikanAnimeResource:
    def __init__(
        self,
        rid,
        name,
        season,
        torrent_url,
        published_date,
        resource_title,
        episode=None,
    ) -> None:
        self.resource_id = rid
        self.anime_name = name
        self.season = season
        self.torrent_url = torrent_url
        self.published_date = published_date
        self.resource_title = resource_title
        self.episode = episode
        self.download_task = None

    @classmethod
    async def from_feed_entry(cls, feed_entry):
        rid = feed_entry.link.split("/")[-1]
        tmp_anime_name = await get_anime_name(feed_entry)
        res = process_anime_name(tmp_anime_name)
        resource_title = feed_entry.title
        published_date = feed_entry.published
        torrent_url = get_torrent_url(feed_entry)
        return cls(
            rid, res["name"], res["season"], torrent_url, published_date, resource_title
        )

    def set_download_task(self, task: DownloadTask):
        self.download_task = task

    def __repr__(self):
        return (
            "<MikanAnimeResource"
            f" {self.anime_name} {self.season} {self.resource_title}>"
        )
