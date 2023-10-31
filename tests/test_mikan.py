from urllib.request import ProxyHandler

import feedparser
import pytest

import config
from core.mikan import MikanAnimeResource


class TestRssParser:
    @pytest.fixture
    def resource(self):
        base_url = "mikanani.me"
        # base_url = "mikanime.tv"
        feed_url = f"https://{base_url}/RSS/Bangumi?bangumiId=3039&subgroupid=611"
        proxy_handler = ProxyHandler(config.PROXIES)
        feed = feedparser.parse(feed_url, handlers=[proxy_handler])
        resource = MikanAnimeResource(feed.entries[-1])
        return resource

    def test_parse_torrent_link(self, resource: MikanAnimeResource):
        assert resource.torrent_link.endswith(".torrent")

    def test_parse_anime_name(self, resource: MikanAnimeResource):
        assert resource.anime_name == "赛马娘 Pretty Derby Road to the Top"