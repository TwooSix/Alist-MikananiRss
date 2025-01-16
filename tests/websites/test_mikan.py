from unittest.mock import patch

import feedparser
import pytest

from alist_mikananirss.extractor import (
    AnimeNameExtractResult,
    ResourceTitleExtractResult,
    VideoQuality,
)
from alist_mikananirss.websites import FeedEntry, ResourceInfo
from alist_mikananirss.websites.mikan import Mikan, MikanHomePageInfo


@pytest.fixture
def mikan():
    return Mikan("https://mikanani.me/RSS/Bangumi?bangumiId=3519&subgroupid=382")


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
async def test_get_feed_entries_real(mikan):
    # 测试真实的蜜柑RSS链接解析是否有报错
    await mikan.get_feed_entries()


@pytest.mark.asyncio
async def test_parse_homepage_error(mikan):
    # 对于蜜柑，强需求主页中的番剧名/字幕组信息，解析详情页时，如果出现异常，应该抛出异常
    mock_entry = FeedEntry(
        resource_title="【喵萌Production】★04月新番★[GIRLS BAND CRY][01-13][1080p][繁日双语][招募翻译时轴]",
        torrent_url="https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent",
        published_date="2024-07-17T19:09:00",
        homepage_url="https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7",
    )
    with patch.object(mikan, "parse_homepage", side_effect=Exception):
        with pytest.raises(Exception):
            await mikan.extract_resource_info(mock_entry, use_extractor=False)


@pytest.mark.asyncio
async def test_extract_resource_info(mikan):
    # 测试蜜柑是否使用主页提供的番剧名/字幕组信息
    mock_entry = FeedEntry(
        resource_title="【喵萌Production】★04月新番★[GIRLS BAND CRY][01][1080p][繁日双语][招募翻译时轴]",
        torrent_url="https://mikanani.me/Download/20240717/a19d5da34e2ec205bddd9c6935ab579ff37da7d7.torrent",
        published_date="2024-07-17T19:09:00",
        homepage_url="https://mikanani.me/Home/Episode/a19d5da34e2ec205bddd9c6935ab579ff37da7d7",
    )

    mock_homepage_info = MikanHomePageInfo(
        anime_name="GIRLS BAND CRY", fansub="喵萌奶茶屋"
    )

    mock_animename_extract_result = AnimeNameExtractResult(
        anime_name="GIRLS BAND CRY", season=1
    )

    mock_extract_result = ResourceTitleExtractResult(
        anime_name="tmdb_name",
        season=1,
        episode=1,
        quality=VideoQuality.p1080,
        language="繁日双语",
        fansub="gpt_fansub",
        version=1,
    )

    with patch.object(mikan, "parse_homepage", return_value=mock_homepage_info):
        with patch(
            "alist_mikananirss.extractor.Extractor.analyse_resource_title",
            return_value=mock_extract_result,
        ):
            with patch(
                "alist_mikananirss.extractor.Extractor.analyse_anime_name",
                return_value=mock_animename_extract_result,
            ):
                result = await mikan.extract_resource_info(
                    mock_entry, use_extractor=True
                )

    assert isinstance(result, ResourceInfo)
    assert result.anime_name == mock_homepage_info.anime_name
    assert result.resource_title == mock_entry.resource_title
    assert result.torrent_url == mock_entry.torrent_url
    assert result.season == mock_extract_result.season
    assert result.episode == mock_extract_result.episode
    assert result.fansub == mock_homepage_info.fansub
