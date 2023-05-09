"""
Only Test in mikanani.me
"""
import gc
import logging
import re

import bs4
import feedparser
import pandas
import requests

logger = logging.getLogger(__name__)


class RssParser:
    def __init__(self) -> None:
        pass

    @staticmethod
    def parse_torrent_link(entry: dict) -> str:
        """Get torrent link from rss feed entry

        Args:
            entry (dict): Rss feed entry

        Returns:
            str: torrent link
        """
        for link in entry.links:
            if link["type"] == "application/x-bittorrent":
                return link["href"]

    @staticmethod
    def parse_anime_name(entry: dict) -> str:
        try:
            home_page_url = entry.link
            resp = requests.get(home_page_url)
            soup = bs4.BeautifulSoup(resp.text, "html.parser")
            anime_name = soup.find("p", class_="bangumi-title").text.strip()
            # fix memory leak caused by BeautifulSoup
            resp.close()
            soup.decompose()
            soup = None
            gc.collect()
        except Exception as e:
            logger.error(f"Error when parsing anime name:{e}")
            return None
        return anime_name

    @staticmethod
    def parse_data_frame(
        feed: feedparser.FeedParserDict, filters: list[re.Pattern] = []
    ) -> pandas.DataFrame:
        """Parse rss feed from rss feed url to pandas.DataFrame
        with title, link, publish date

        Args:
            rss_url (dict): FeedParserDict generated by feedparser.parse()
            filters (list[re.Pattern], optional): Filter list. Defaults to [].

        Returns:
            pandas.DataFrame: With rss feed's title, link, publish date
        """
        data = {"title": [], "link": [], "pubDate": [], "animeName": []}
        for entry in feed.entries:
            match_result = True
            for pattern in filters:
                match_result = match_result and re.search(pattern, entry.title)
            if match_result:
                data["title"].append(entry.title)
                data["link"].append(RssParser.parse_torrent_link(entry))
                data["pubDate"].append(entry.published)
                data["animeName"].append(RssParser.parse_anime_name(entry))
        df = pandas.DataFrame(data)
        df["pubDate"] = pandas.to_datetime(df["pubDate"], format="mixed", utc=True)
        return df
