import gc

import bs4
import requests
from loguru import logger

import config


class MikanAnimeResource:
    def __init__(self, feed_entry) -> None:
        self.resource_id = feed_entry.link.split("/")[-1]
        self.anime_name = self.__parse_anime_name(feed_entry)
        self.torrent_link = self.__parse_torrent_link(feed_entry)
        self.published_date = feed_entry.published
        self.resource_title = feed_entry.title

    def __parse_torrent_link(self, feed_entry) -> str:
        for link in feed_entry.links:
            if link["type"] == "application/x-bittorrent":
                return link["href"]

    def __parse_anime_name(self, feed_entry) -> str:
        try:
            home_page_url = feed_entry.link
            # craw the anime name from homepage
            resp = requests.get(home_page_url, proxies=config.PROXIES)
            soup = bs4.BeautifulSoup(resp.text, "html.parser")
            anime_name = soup.find("p", class_="bangumi-title").text.strip()
            # try to fix memory leak caused by BeautifulSoup
            resp.close()
            soup.decompose()
            soup = None
            gc.collect()
        except Exception as e:
            logger.error(f"Error when get anime name:\n{e}")
            return None
        return anime_name
