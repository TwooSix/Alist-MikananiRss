import feedparser
from core.rssparser import RssParser


class TestRssParser:
    feed_url = "https://mikanani.me/RSS/Bangumi?bangumiId=3039&subgroupid=611"
    feed = feedparser.parse(feed_url)

    def test_parse_torrent_link(self):
        entry = self.feed.entries[-1]
        assert (
            RssParser.parse_torrent_link(entry)
            == "https://mikanani.me/Download/20230419/af9edbcb71798164bf4ffd362f527d35fbeb1545.torrent"
        )

    def test_parse_anime_name(self):
        entry = self.feed.entries[-1]
        assert RssParser.parse_anime_name(entry) == "赛马娘 Pretty Derby Road to the Top"

    def test_parse_data_frame(self):
        df = RssParser.parse_data_frame(self.feed)
        assert df.shape[0] > 0
        assert df.columns.to_list() == ["title", "link", "pubDate", "animeName"]

    def test_parse_data_frame_with_filter(self):
        rssFilter = {
            "test": r"^((?!内封).)*$",
        }
        myfilter = [rssFilter["test"]]
        df = RssParser.parse_data_frame(self.feed, myfilter)
        res_df = df[df["title"].str.contains("内封")]
        assert res_df.shape[0] == 0
        res_df = df[df["title"].str.contains("内嵌")]
        assert res_df.shape[0] > 0
