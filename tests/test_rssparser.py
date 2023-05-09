import feedparser
import pytest
from core.rssparser import RssParser


class TestRssParser:
    @pytest.fixture
    def feed(self):
        base_url = "mikanani.me"
        # base_url = "mikanime.tv"
        feed_url = f"https://{base_url}/RSS/Bangumi?bangumiId=3039&subgroupid=611"
        feed = feedparser.parse(feed_url)
        return feed

    def test_parse_torrent_link(self, feed):
        entry = feed.entries[-1]
        assert RssParser.parse_torrent_link(entry).endswith(".torrent")

    def test_parse_anime_name(self, feed):
        entry = feed.entries[-1]
        assert RssParser.parse_anime_name(entry) == "赛马娘 Pretty Derby Road to the Top"

    def test_parse_data_frame(self, feed):
        df = RssParser.parse_data_frame(feed)
        assert df.shape[0] > 0
        # assert df.columns.to_list() == ["title", "link", "pubDate", "animeName"]

    def test_parse_data_frame_with_filter(self, feed):
        rssFilter = {
            "test": r"^((?!内封).)*$",
        }
        myfilter = [rssFilter["test"]]
        df = RssParser.parse_data_frame(feed, myfilter)
        res_df = df[df["title"].str.contains("内封")]
        assert res_df.shape[0] == 0
        res_df = df[df["title"].str.contains("内嵌")]
        assert res_df.shape[0] > 0
