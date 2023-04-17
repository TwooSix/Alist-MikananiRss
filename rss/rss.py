import pandas as pd

import rss


class Rss:
    def __init__(
        self, url: str, rss_filter_name: list[str] = None, sub_folder: str = None
    ):
        """Class of rss feed

        Args:
            url (str): Rss feed's url
            rss_filter_name (list[str], optional): The list of filter's name,
                which will auto change to regex. Defaults to None.
            sub_folder (str, optional): Name of subfolder. Defaults to None.
        """
        self.url = url
        self.sub_folder = sub_folder
        self.name = sub_folder if sub_folder else url
        self.set_filter(rss_filter_name)

    def set_filter(self, filter_names: list[str]) -> None:
        """Set regex filter for rss feed"""
        rss_filter = []
        for name in filter_names:
            rss_filter.append(rss.Filter.getFilter(name))
        self.filter = rss_filter
        return

    def get_name(self) -> str:
        """get name of rss feed, subfolder name or url"""
        return self.name

    def get_url(self) -> str:
        """get url of rss feed"""
        return self.url

    def get_subfolder(self) -> str:
        """get subfolder name of rss feed"""
        return self.sub_folder

    def parse(self) -> pd.DataFrame:
        """Parse rss feed and return a pandas DataFrame"""
        return rss.Parser.parse(self.url, self.filter)

    def __str__(self) -> str:
        return self.name
