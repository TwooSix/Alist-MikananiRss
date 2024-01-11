import feedparser
import pytest

from core.common import config_loader
from core.mikan import MikanAnimeResource

if config_loader.get_use_proxy():
    import os

    proxies = config_loader.get_proxies()
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


class TestRssParser:
    @pytest.fixture
    def resource(self):
        base_url = "mikanani.me"
        # base_url = "mikanime.tv"
        feed_url = f"https://{base_url}/RSS/Bangumi?bangumiId=3039&subgroupid=611"
        feed = feedparser.parse(feed_url)
        resource = MikanAnimeResource(feed.entries[-1])
        return resource

    def test_parse_torrent_link(self, resource: MikanAnimeResource):
        assert resource.torrent_url.endswith(".torrent")

    def test_parse_anime_name(self, resource: MikanAnimeResource):
        assert resource.anime_name == "赛马娘 Pretty Derby Road to the Top"
