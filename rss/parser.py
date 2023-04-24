"""
Only Test in mikanani.me
"""
import re

import feedparser
import pandas


class Parser:
    def __init__(self) -> None:
        pass

    @staticmethod
    def parseTorrentLink(entry: dict) -> str:
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
    def parseAnimeName(feed: feedparser.FeedParserDict) -> str:
        """Parse anime name from rss feed

        Args:
            feed (feedparser.FeedParserDict): FeedParserDict generated by
                feedparser.parse()

        Returns:
            str: anime name, None if error
        """
        try:
            anime_name = feed["feed"]["title"].split(" - ")[1]
        except KeyError as e:
            print(f"Error when parsing anime name:{e}")
            return None
        return anime_name

    @staticmethod
    def parseDataFrame(
        feed: feedparser.FeedParserDict, filter: list[re.Pattern] = []
    ) -> pandas.DataFrame:
        """Parse rss feed from rss feed url to pandas.DataFrame
        with title, link, publish date

        Args:
            rss_url (dict): FeedParserDict generated by feedparser.parse()
            filter (list[re.Pattern], optional): Filter list. Defaults to [].

        Returns:
            pandas.DataFrame: With rss feed's title, link, publish date
        """
        data = {"title": [], "link": [], "pubDate": []}
        for each in feed.entries:
            match_result = True
            for pattern in filter:
                match_result = match_result and re.search(pattern, each.title)
            if match_result:
                data["title"].append(each.title)
                data["link"].append(Parser.parseTorrentLink(each))
                data["pubDate"].append(each.published)
        df = pandas.DataFrame(data)
        df["pubDate"] = pandas.to_datetime(df["pubDate"], format="mixed", utc=True)
        return df

if __name__ == '__main__':
    rssFilter = {
        "简体": r"(简体)|(简中)|(简日)|(CHS)",
        "繁体": r"(繁体)|(繁中)|(繁日)|(CHT)",
        "1080": r"(1080[pP])",
        "非合集": r"^((?!合集).)*$",
    }

    rss_url = "https://mikanani.me/RSS/Bangumi?bangumiId=2817"
    feed = feedparser.parse(rss_url)
    myfilter = [rssFilter['简体'], rssFilter['1080']]
    df = Parser.parseDataFrame(feed, myfilter)
    print(df['title'])
    print(Parser.parseAnimeName(feed))