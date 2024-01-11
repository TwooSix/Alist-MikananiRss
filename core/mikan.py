import gc
import time

import bs4
import requests

from core.common import extractor


def get_torrent_url(feed_entry) -> str:
    for link in feed_entry.links:
        if link["type"] == "application/x-bittorrent":
            return link["href"]


def get_anime_name(feed_entry) -> str:
    home_page_url = feed_entry.link
    # craw the anime name from homepage
    resp = requests.get(home_page_url)
    resp.raise_for_status()
    time.sleep(1)
    soup = bs4.BeautifulSoup(resp.text, "html.parser")
    anime_name = soup.find("p", class_="bangumi-title").text.strip()
    # try to fix memory leak caused by BeautifulSoup
    resp.close()
    soup.decompose()
    soup = None
    gc.collect()
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

    @classmethod
    def from_feed_entry(cls, feed_entry):
        rid = feed_entry.link.split("/")[-1]
        tmp_anime_name = get_anime_name(feed_entry)
        res = process_anime_name(tmp_anime_name)
        resource_title = feed_entry.title
        published_date = feed_entry.published
        torrent_url = get_torrent_url(feed_entry)
        return cls(
            rid, res["name"], res["season"], torrent_url, published_date, resource_title
        )

    def __repr__(self):
        return (
            "<MikanAnimeResource"
            f" {self.anime_name} {self.season} {self.resource_title}>"
        )
