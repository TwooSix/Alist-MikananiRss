from unittest.mock import AsyncMock, MagicMock, patch

import feedparser
import pytest

from alist_mikananirss.websites import FeedEntry, ResourceInfo
from alist_mikananirss.websites.mikan import Mikan, MikanHomePageInfo


@pytest.fixture
def mikan():
    return Mikan("https://mikanani.me/RSS/Bangumi?bangumiId=2742&subgroupid=370")


@pytest.fixture
def mock_rss_data():
    return """<rss version="2.0">
<channel>
<title>Mikan Project - GIRLS BAND CRY</title>
<link>https://mikanani.me/RSS/Bangumi?bangumiId=3298&subgroupid=382</link>
<description>Mikan Project - GIRLS BAND CRY</description>
<item>
<guid isPermaLink="false">【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]</guid>
<link>https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7</link>
<title>【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]</title>
<description>【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴][8.8GB]</description>
<torrent xmlns="https://mikanani.me/0.1/">
<link>https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7</link>
<contentLength>9448928256</contentLength>
<pubDate>2024-07-17T19:09:00</pubDate>
</torrent>
<enclosure type="application/x-bittorrent" length="9448928256" url="https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent"/>
</item>
</channel>
</rss>"""


@pytest.mark.asyncio
async def test_get_feed_entries(mikan, mock_rss_data):
    with patch.object(
        mikan, "parse_feed", return_value=feedparser.parse(mock_rss_data)
    ):
        result = await mikan.get_feed_entries()

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result.pop()
    assert isinstance(entry, FeedEntry)
    assert (
        entry.resource_title
        == "【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]"
    )
    assert (
        entry.torrent_url
        == "https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent"
    )
    assert entry.published_date == "2024-07-17T19:09:00"
    assert (
        entry.homepage_url
        == "https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7"
    )


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.get")
async def test_parse_homepage(mock_get, mikan):
    # Setup mock response
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = AsyncMock(
        return_value="""
    <html>
        <p class="bangumi-title">GIRLS BAND CRY</p>
        <p class="bangumi-info">字幕组：喵萌奶茶屋</p>
    </html>
    """
    )
    mock_get.return_value.__aenter__.return_value = mock_response
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await mikan.parse_homepage(
            "https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7"
        )
    assert isinstance(result, MikanHomePageInfo)
    assert result.anime_name == "GIRLS BAND CRY"
    assert result.fansub == "喵萌奶茶屋"


@pytest.mark.asyncio
async def test_extract_resource_info(mikan):
    mock_entry = FeedEntry(
        resource_title="【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]",
        torrent_url="https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent",
        published_date="2024-07-17T19:09:00",
        homepage_url="https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7",
    )

    mock_homepage_info = MikanHomePageInfo(
        anime_name="GIRLS BAND CRY", fansub="喵萌奶茶屋"
    )

    with patch.object(mikan, "parse_homepage", return_value=mock_homepage_info):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await mikan.extract_resource_info(mock_entry)

    assert isinstance(result, ResourceInfo)
    assert result.anime_name == "GIRLS BAND CRY"
    assert (
        result.resource_title
        == "【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]"
    )
    assert (
        result.torrent_url
        == "https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent"
    )
    assert result.published_date == "2024-07-17T19:09:00"
    assert result.fansub == "喵萌奶茶屋"
