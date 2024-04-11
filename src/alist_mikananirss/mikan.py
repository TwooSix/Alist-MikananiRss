import aiohttp
import bs4

from alist_mikananirss.alist.offline_download import DownloadTask
from alist_mikananirss.extractor import Extractor


class HomePageParser:
    def __init__(self, url):
        self.url = url
        self.soup = None
        self.anime_name = None
        self.fansub = None

    async def fetch_and_parse(self):
        html = await self._async_fetch(self.url)
        self.soup = self._parse_html(html)

        self.anime_name = self.soup.find("p", class_="bangumi-title").text.strip()

        bgm_info_elements = self.soup.find_all("p", class_="bangumi-info")
        for e in bgm_info_elements:
            if "字幕组" in e.text:
                text = e.text.strip()
                self.fansub = text.split("：")[-1]
                break
        return True

    def get_anime_name(self):
        illegal_chars = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]
        for char in illegal_chars:
            anime_name = self.anime_name.replace(char, " ")
        return anime_name

    def get_fansub(self):
        return self.fansub

    async def _async_fetch(self, url):
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

    def _parse_html(self, html):
        return bs4.BeautifulSoup(html, "html.parser")


def get_torrent_url(feed_entry) -> str:
    for link in feed_entry.links:
        if link["type"] == "application/x-bittorrent":
            return link["href"]


class MikanAnimeResource:
    def __init__(
        self,
        rid,
        name,
        torrent_url,
        published_date,
        resource_title,
        season=None,
        episode=None,
        fansub=None,
        quality=None,
        language=None,
    ) -> None:
        self.resource_id = rid
        self.anime_name = name
        self.season = season
        self.torrent_url = torrent_url
        self.published_date = published_date
        self.resource_title = resource_title
        self.episode = episode
        self.fansub = fansub
        self.quality = quality
        self.language = language
        self.download_task = None

    @classmethod
    async def from_feed_entry(cls, feed_entry):
        hp_parser = HomePageParser(feed_entry.link)
        rid = feed_entry.link.split("/")[-1]
        await hp_parser.fetch_and_parse()
        anime_name = hp_parser.get_anime_name()
        fansub = hp_parser.get_fansub()
        resource_title = feed_entry.title
        published_date = feed_entry.published
        torrent_url = get_torrent_url(feed_entry)
        return cls(
            rid=rid,
            name=anime_name,
            torrent_url=torrent_url,
            published_date=published_date,
            resource_title=resource_title,
            fansub=fansub,
        )

    def set_download_task(self, task: DownloadTask):
        self.download_task = task

    async def extract(self, extractor: Extractor):
        """Use extractor to extract resource info from resource title"""
        await extractor.extract(self.anime_name, self.resource_title)
        self.episode = extractor.get_episode()
        self.season = extractor.get_season()
        self.quality = extractor.get_quality()
        self.language = extractor.get_language()

    def __repr__(self):
        return (
            "<MikanAnimeResource"
            f" {self.anime_name} {self.season} {self.resource_title}>"
        )
