from unittest.mock import patch

import feedparser
import pytest

from alist_mikananirss.extractor import (  # noqa
    Extractor,
    ResourceTitleExtractResult,
    VideoQuality,
)
from alist_mikananirss.websites import FeedEntry, ResourceInfo
from alist_mikananirss.websites.acgrip import AcgRip


@pytest.fixture
def acgrip():
    return AcgRip("https://acg.rip/.xml")


@pytest.fixture
def mock_rss_data():
    return """<rss version="2.0">
<channel>
<title>ACG.RIP</title>
<description>ACG.RIP has super cow power</description>
<link>https://acg.rip/.xml</link>
<ttl>1800</ttl>
<item>
<title>[ANi] Hana wa Saku Shura no Gotoku / 群花綻放、彷如修羅 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]</title>
<description>Torrent Info By: ANi API (Auto Generated)<br /> Subtitle:<br /> HardSub<br /> Mediainfo:<br /> Resolution: 1080P<br /> Video Format: AVC<br /> Audio Format: AAC<br /> <br /> Note:<br /> Xunlei, tor...</description>
<pubDate>Tue, 14 Jan 2025 09:35:59 -0800</pubDate>
<link>https://acg.rip/t/321423</link>
<guid>https://acg.rip/t/321423</guid>
<enclosure url="https://acg.rip/t/321423.torrent" type="application/x-bittorrent"/>
</item>
</channel>
</rss>"""


@pytest.fixture
def mock_extract_data():
    ret = {
        "mock_entry": FeedEntry(
            resource_title="[ANi] Hana wa Saku Shura no Gotoku / 群花綻放、彷如修羅 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
            torrent_url="https://acg.rip/t/321423.torrent",
            homepage_url="https://acg.rip/t/321423",
        ),
        "mock_extract_result": ResourceTitleExtractResult(
            anime_name="群花绽放，仿如修罗",
            season=1,
            episode=2,
            quality=VideoQuality.p1080,
            language="CHT",
            fansub="ANi",
            version=1,
        ),
    }
    return ret


@pytest.mark.asyncio
async def test_get_feed_entries(acgrip, mock_rss_data):
    with patch.object(
        acgrip, "parse_feed", return_value=feedparser.parse(mock_rss_data)
    ):
        result = await acgrip.get_feed_entries()

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result.pop()
    assert isinstance(entry, FeedEntry)
    assert (
        entry.resource_title
        == "[ANi] Hana wa Saku Shura no Gotoku / 群花綻放、彷如修羅 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]"
    )
    assert entry.torrent_url == "https://acg.rip/t/321423.torrent"
    assert entry.homepage_url == "https://acg.rip/t/321423"


@pytest.mark.asyncio
async def test_get_feed_entries_real(acgrip):
    # 测试真实的RSS链接解析是否有报错
    await acgrip.get_feed_entries()


@pytest.mark.asyncio
async def test_parse_homepage_error(acgrip, mock_extract_data):
    # 非强需求；不报错
    with patch.object(acgrip, "parse_homepage", side_effect=Exception):
        await acgrip.extract_resource_info(
            mock_extract_data["mock_entry"], use_extractor=False
        )


@pytest.mark.asyncio
async def test_none_fansub(acgrip, mock_extract_data):
    # 无法从主页解析到fansub，使用extractor解析的fansub结果

    with patch.object(acgrip, "parse_homepage", return_value=None):
        with patch(
            "alist_mikananirss.extractor.Extractor.analyse_resource_title",
            return_value=mock_extract_data["mock_extract_result"],
        ):
            result = await acgrip.extract_resource_info(
                mock_extract_data["mock_entry"], use_extractor=True
            )

    assert isinstance(result, ResourceInfo)
    assert result.fansub == mock_extract_data["mock_extract_result"].fansub


@pytest.mark.asyncio
async def test_homepage_fansub(acgrip, mock_extract_data):
    # 从主页解析得到fansub，使用主页解析的fansub结果

    mock_extract_result = ResourceTitleExtractResult(
        anime_name="最弱技能《果实大师》",
        season=1,
        episode=3,
        quality=VideoQuality.p1080,
        language="日语",
        fansub="LoliHouse",
        version=1,
    )

    with patch.object(acgrip, "parse_homepage", return_value="homepage_fansub"):
        with patch(
            "alist_mikananirss.extractor.Extractor.analyse_resource_title",
            return_value=mock_extract_result,
        ):
            result = await acgrip.extract_resource_info(
                mock_extract_data["mock_entry"], use_extractor=True
            )

    assert isinstance(result, ResourceInfo)
    assert result.fansub == "homepage_fansub"
