"""
Only Test in mikanani.me
"""
import re

import feedparser
import pandas


class Parser:
    def __init__(self) -> None:
        pass

    def __parseTorrentLink(entry: dict) -> str:
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
    def parse(rss_url: str, filter: list[re.Pattern] = []) -> pandas.DataFrame:
        """Parse rss feed from rss feed url to pandas.DataFrame
        with title, link, publish date

        Args:
            rss_url (str): url
            filter (list[re.Pattern], optional): Filter list. Defaults to [].

        Returns:
            pandas.DataFrame: With rss feed's title, link, publish date
        """
        data = {"title": [], "link": [], "pubDate": []}
        feed = feedparser.parse(rss_url)
        for each in feed.entries:
            match_result = True
            for pattern in filter:
                match_result = match_result and re.search(pattern, each.title)
            if match_result:
                data["title"].append(each.title)
                data["link"].append(Parser.__parseTorrentLink(each))
                data["pubDate"].append(each.published)
        df = pandas.DataFrame(data)
        df["pubDate"] = pandas.to_datetime(df["pubDate"], format="mixed", utc=True)
        return df
