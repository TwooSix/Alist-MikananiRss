import asyncio
from types import SimpleNamespace
from openlist_ani.adapters.feed_sources import (
    AniApiFeedAdapter,
    CommonFeedAdapter,
    MikanFeedAdapter,
)
from openlist_ani.adapters.feed_sources.mikan import _split_season
from openlist_ani.domain import ReleaseMetadata


class _Entry(dict):
    def __getattr__(self, name):
        return self[name]


class _Response:
    status = 200
    headers = {"ETag": '"new"', "Last-Modified": "today"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def text(self):
        return "rss"

    def raise_for_status(self):
        return None


class _Session:
    def get(self, *_args, **_kwargs):
        return _Response()


async def test_mikan_entry_enrichment_has_a_hard_concurrency_limit(monkeypatch):
    entries = [
        _Entry(
            title=f"Example {index}",
            link=f"https://mikanani.me/Home/Episode/{index}",
            enclosures=[
                {
                    "href": f"https://mikanani.me/Download/{index}.torrent",
                    "type": "application/x-bittorrent",
                }
            ],
        )
        for index in range(12)
    ]
    monkeypatch.setattr(
        "openlist_ani.adapters.feed_sources.common.feedparser.parse",
        lambda _text: SimpleNamespace(entries=entries),
    )
    adapter = MikanFeedAdapter(_Session())
    active = 0
    max_active = 0

    async def metadata(_url):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ReleaseMetadata(anime_name="Example", season=1)

    adapter._metadata = metadata
    result = await adapter.fetch("https://mikanani.me/RSS/MyBangumi")

    assert len(result.candidates) == 12
    assert max_active <= 5
    assert result.etag == '"new"'


def test_feed_adapters_select_only_their_supported_urls():
    session = _Session()
    assert MikanFeedAdapter(session).supports(
        "https://mikanani.me/RSS/Bangumi?bangumiId=1"
    )
    assert AniApiFeedAdapter(session).supports("https://api.ani.rip/ani-download.xml")
    assert CommonFeedAdapter(session).supports("https://example.test/rss")


def test_mikan_season_parser_supports_chinese_and_arabic_numbers():
    assert _split_season("我推的孩子 第二季") == ("我推的孩子", 2)
    assert _split_season("Example 第12季") == ("Example", 12)
    assert _split_season("No Season") == ("No Season", 1)
