import aiohttp
import bs4

from alist_mikananirss import extractor
from alist_mikananirss.alist.offline_download import DownloadTask


class HomePageParser:
    def __init__(self, url, timeout=5):
        self.url = url
        self.timeout = timeout
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
            async with session.get(url, timeout=self.timeout) as response:
                response.raise_for_status()
                return await response.text()

    def _parse_html(self, html):
        return bs4.BeautifulSoup(html, "html.parser")


def get_torrent_url(feed_entry) -> str:
    for link in feed_entry.links:
        if link["type"] == "application/x-bittorrent":
            return link["href"]


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
        fansub=None,
    ) -> None:
        self.resource_id = rid
        self.anime_name = name
        self.season = season
        self.torrent_url = torrent_url
        self.published_date = published_date
        self.resource_title = resource_title
        self.episode = episode
        self.fansub = fansub
        self.download_task = None

    @classmethod
    async def from_feed_entry(cls, feed_entry):
        hp_parser = HomePageParser(feed_entry.link)
        rid = feed_entry.link.split("/")[-1]
        await hp_parser.fetch_and_parse()
        tmp_anime_name = hp_parser.get_anime_name()
        fansub = hp_parser.get_fansub()
        res = process_anime_name(tmp_anime_name)
        resource_title = feed_entry.title
        published_date = feed_entry.published
        torrent_url = get_torrent_url(feed_entry)
        return cls(
            rid,
            res["name"],
            res["season"],
            torrent_url,
            published_date,
            resource_title,
            fansub=fansub,
        )

    def set_download_task(self, task: DownloadTask):
        self.download_task = task

    async def extract(self, extractor: extractor.Regex | extractor.ChatGPT):
        info = await extractor.analyse_resource_name(self.resource_title)
        self.episode = info["episode"]
        if "season" in info:
            self.season = info["season"]

    def __repr__(self):
        return (
            "<MikanAnimeResource"
            f" {self.anime_name} {self.season} {self.resource_title}>"
        )
