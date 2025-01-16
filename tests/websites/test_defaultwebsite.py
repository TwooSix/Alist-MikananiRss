from unittest.mock import patch

import feedparser
import pytest
from loguru import logger

from alist_mikananirss.websites import FeedEntry
from alist_mikananirss.websites.default import DefaultWebsite


@pytest.fixture
def default_website():
    return DefaultWebsite("https://example.com/rss")


@pytest.fixture
def mock_nyaa_rss():
    return """<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:nyaa="https://nyaa.si/xmlns/nyaa" version="2.0">
<channel>
<title>Nyaa - Home - Torrent File RSS</title>
<description>RSS Feed for Home</description>
<link>https://nyaa.si/</link>
<atom:link href="https://nyaa.si/?page=rss" rel="self" type="application/rss+xml"/>
<item>
<title>[FLE] Dr. Stone - S01 (BD 1080p HEVC x265 Opus) [Dual Audio] | Dr Stone Season 1</title>
<link>https://nyaa.si/download/1921713.torrent</link>
<guid isPermaLink="true">https://nyaa.si/view/1921713</guid>
<pubDate>Wed, 15 Jan 2025 08:08:41 -0000</pubDate>
<nyaa:seeders>24</nyaa:seeders>
<nyaa:leechers>443</nyaa:leechers>
<nyaa:downloads>38</nyaa:downloads>
<nyaa:infoHash>a1cdf8f9edf70d074bb4cd22e6f122bd5ad5aa3b</nyaa:infoHash>
<nyaa:categoryId>1_2</nyaa:categoryId>
<nyaa:category>Anime - English-translated</nyaa:category>
<nyaa:size>37.3 GiB</nyaa:size>
<nyaa:comments>0</nyaa:comments>
<nyaa:trusted>No</nyaa:trusted>
<nyaa:remake>No</nyaa:remake>
<description>
<![CDATA[ <a href="https://nyaa.si/view/1921713">#1921713 | [FLE] Dr. Stone - S01 (BD 1080p HEVC x265 Opus) [Dual Audio] | Dr Stone Season 1</a> | 37.3 GiB | Anime - English-translated | A1CDF8F9EDF70D074BB4CD22E6F122BD5AD5AA3B ]]>
</description>
</item>
</channel>
</rss>"""


@pytest.fixture
def mock_aniapi_rss():
    return """<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:anime="https://open.ani-download.workers.dev" version="2.0">
<channel>
<title>
<![CDATA[ ANi Download API ]]>
</title>
<description>
<![CDATA[ ANi RSS for Share Anime ]]>
</description>
<link>https://open.ani.rip</link>
<generator>RSS By ANi API</generator>
<lastBuildDate>Tue, 14 Jan 2025 17:35:55 GMT</lastBuildDate>
<atom:link href="https://api.ani.rip/ani-download.xml" rel="self" type="application/rss+xml"/>
<item>
<title>
<![CDATA[ [ANi] 青之壬生浪 - 13 [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4 ]]>
</title>
<link>https://resources.ani.rip/2024-10/%5BANi%5D%20%E9%9D%92%E4%B9%8B%E5%A3%AC%E7%94%9F%E6%B5%AA%20-%2013%20%5B1080P%5D%5BBaha%5D%5BWEB-DL%5D%5BAAC%20AVC%5D%5BCHT%5D.mp4?d=true</link>
<guid isPermaLink="true">https://resources.ani.rip/2024-10/%5BANi%5D%20%E9%9D%92%E4%B9%8B%E5%A3%AC%E7%94%9F%E6%B5%AA%20-%2013%20%5B1080P%5D%5BBaha%5D%5BWEB-DL%5D%5BAAC%20AVC%5D%5BCHT%5D.mp4?d=true</guid>
<pubDate>Sat, 11 Jan 2025 13:34:09 GMT</pubDate>
<anime:size>286.2 MB</anime:size>
</item>"""


@pytest.fixture
def mock_unsupported_rss():
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test RSS Feed</title>
<link>http://example.com</link>
<description>Test feed with unsupported format</description>
<item>
<title>Test Item</title>
<description>Description without torrent link or video link</description>
<link>http://example.com/article</link>
<pubDate>Wed, 15 Jan 2025 08:08:41 -0000</pubDate>
</item>
</channel>
</rss>"""


@pytest.mark.asyncio
async def test_nyaa(default_website, mock_nyaa_rss):
    with patch.object(
        default_website, "parse_feed", return_value=feedparser.parse(mock_nyaa_rss)
    ):
        result = await default_website.get_feed_entries()

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result.pop()
    assert isinstance(entry, FeedEntry)
    assert (
        entry.resource_title
        == "[FLE] Dr. Stone - S01 (BD 1080p HEVC x265 Opus) [Dual Audio] | Dr Stone Season 1"
    )
    assert entry.torrent_url == "https://nyaa.si/download/1921713.torrent"


@pytest.mark.asyncio
async def test_aniapi(default_website, mock_aniapi_rss):
    with patch.object(
        default_website, "parse_feed", return_value=feedparser.parse(mock_aniapi_rss)
    ):
        result = await default_website.get_feed_entries()

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result.pop()
    assert isinstance(entry, FeedEntry)
    assert (
        entry.resource_title
        == "[ANi] 青之壬生浪 - 13 [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4"
    )
    assert (
        entry.torrent_url
        == "https://resources.ani.rip/2024-10/%5BANi%5D%20%E9%9D%92%E4%B9%8B%E5%A3%AC%E7%94%9F%E6%B5%AA%20-%2013%20%5B1080P%5D%5BBaha%5D%5BWEB-DL%5D%5BAAC%20AVC%5D%5BCHT%5D.mp4?d=true"
    )


@pytest.mark.asyncio
async def test_unsupported_rss(default_website, mock_unsupported_rss):
    with patch.object(
        default_website,
        "parse_feed",
        return_value=feedparser.parse(mock_unsupported_rss),
    ):
        with patch.object(logger, "error") as mock_logger_error:
            result = await default_website.get_feed_entries()

    mock_logger_error.assert_called_once()
    assert isinstance(result, list)
    assert len(result) == 0
