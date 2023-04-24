import feedparser
import pandas as pd

import rss


class Rss:
    def __init__(
        self, url: str, rss_filter_name: list[str] = None, sub_folder: str = None
    ):
        self.url = url
        if sub_folder == "__AUTO__":
            auto_name = self.__autoName()
            self.sub_folder = auto_name
        else:
            self.sub_folder = sub_folder
        self.name = self.sub_folder if self.sub_folder else url
        self.feed = None
        self.setFilter(rss_filter_name)

    def setFilter(self, filter_names: list[str]) -> None:
        """Set regex filter for rss feed"""
        rss_filter = []
        for name in filter_names:
            rss_filter.append(rss.Filter.getFilter(name))
        self.filter = rss_filter
        return

    def __autoName(self) -> str:
        """Auto get name from rss feed"""
        try:
            feed = feedparser.parse(self.url)
            name = rss.Parser.parseAnimeName(feed)
        except Exception:
            return None
        return name

    def getName(self) -> str:
        """get name of rss feed, subfolder name or url"""
        return self.name

    def getUrl(self) -> str:
        """get url of rss feed"""
        return self.url

    def getSubFolder(self) -> str:
        """get subfolder name of rss feed"""
        return self.sub_folder

    def parse(self) -> pd.DataFrame:
        """Parse rss feed and return a pandas DataFrame"""
        self.feed = feedparser.parse(self.url)
        if self.feed.bozo:
            raise ConnectionError(f"{self.feed.bozo_exception}")
        return rss.Parser.parseDataFrame(self.feed, self.filter)

    def __str__(self) -> str:
        return self.name
