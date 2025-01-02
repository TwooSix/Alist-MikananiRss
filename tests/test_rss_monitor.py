import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.core import RegexFilter, RssMonitor
from alist_mikananirss.websites import FeedEntry, ResourceInfo


@pytest.fixture
def mock_website():
    return AsyncMock()


@pytest.fixture
def mock_filter():
    return MagicMock(spec=RegexFilter)


@pytest.fixture
def mock_db():
    return MagicMock(spec=SubscribeDatabase)


@pytest.mark.asyncio
async def test_rss_monitor_initialization(mock_db):
    urls = ["https://example.com/rss1", "https://example.com/rss2"]
    filter_mock = MagicMock(spec=RegexFilter)

    with patch(
        "alist_mikananirss.websites.WebsiteFactory.get_website_parser"
    ) as mock_factory:
        mock_factory.side_effect = [MagicMock(), MagicMock()]
        monitor = RssMonitor(urls, filter_mock, mock_db)

        assert monitor.subscribe_urls == urls
        assert len(monitor.websites) == 2
        assert monitor.filter == filter_mock
        assert not monitor.use_extractor
        assert isinstance(monitor.db, SubscribeDatabase)
        assert monitor.interval_time == 300


@pytest.mark.asyncio
async def test_set_interval_time(mock_db):
    with patch("alist_mikananirss.websites.WebsiteFactory.get_website_parser"):
        monitor = RssMonitor(
            "https://example.com/rss", MagicMock(spec=RegexFilter), mock_db
        )
        monitor.set_interval_time(600)
        assert monitor.interval_time == 600


@pytest.mark.asyncio
async def test_get_new_resources(mock_website, mock_filter, mock_db):
    feed_entries = [
        FeedEntry("Resource 1", "https://example.com/torrent1"),
        FeedEntry("Resource 2", "https://example.com/torrent2"),
    ]
    mock_website.get_feed_entries.return_value = feed_entries
    mock_filter.filt_single.side_effect = [True, False]
    mock_db.is_resource_title_exist.return_value = False

    resource_info = ResourceInfo("Resource 1", "https://example.com/torrent1")
    mock_website.extract_resource_info.return_value = resource_info

    monitor = RssMonitor("https://mikanani.me/rss", mock_filter, mock_db)
    monitor.db = mock_db

    new_resources = await monitor.get_new_resources([mock_website], mock_filter)

    assert len(new_resources) == 1
    assert new_resources[0] == resource_info
    mock_website.get_feed_entries.assert_called_once()
    mock_filter.filt_single.assert_has_calls([call("Resource 1"), call("Resource 2")])
    mock_db.is_resource_title_exist.assert_called_once_with("Resource 1")
    mock_website.extract_resource_info.assert_called_once_with(feed_entries[0], False)


@pytest.mark.asyncio
async def test_run(mock_website, mock_filter, mock_db):
    with (
        patch(
            "alist_mikananirss.websites.WebsiteFactory.get_website_parser",
            return_value=mock_website,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch(
            "alist_mikananirss.core.download_manager.DownloadManager.add_download_tasks",
            new_callable=AsyncMock,
        ) as mock_add_tasks,
    ):

        monitor = RssMonitor("https://mikanani.me/rss", mock_filter, mock_db)
        monitor.db = mock_db
        monitor.get_new_resources = AsyncMock(
            return_value=[ResourceInfo("New Resource", "https://example.com/new")]
        )

        # 让run方法在第二次循环后退出
        mock_sleep.side_effect = [None, asyncio.CancelledError]

        with pytest.raises(asyncio.CancelledError):
            await monitor.run()

        assert monitor.get_new_resources.call_count == 2
        assert mock_add_tasks.call_count == 2
        mock_sleep.assert_called_with(300)


@pytest.mark.asyncio
async def test_get_new_resources_with_exceptions(mock_website, mock_filter, mock_db):
    feed_entries = [
        FeedEntry("Resource 1", "https://mikanani.me/rss/torrent1"),
        FeedEntry("Resource 2", "https://mikanani.me/rss/torrent2"),
    ]
    mock_website.get_feed_entries.return_value = feed_entries
    mock_filter.filt_single.side_effect = [True, True]
    mock_db.is_resource_title_exist.return_value = False
    mock_website.extract_resource_info.side_effect = [
        ResourceInfo("Resource 1", "https://example.com/torrent1"),
        Exception("Network error"),
    ]

    monitor = RssMonitor("https://mikanani.me/rss/rss", mock_filter, mock_db)
    monitor.db = mock_db

    new_resources = await monitor.get_new_resources([mock_website], mock_filter)

    assert len(new_resources) == 1
    mock_website.extract_resource_info.assert_has_calls(
        [call(feed_entries[0], False), call(feed_entries[1], False)]
    )


@pytest.mark.asyncio
async def test_get_new_resources_with_non_feed(mock_filter, mock_db):
    monitor = RssMonitor("https://mikanani.me/rss", mock_filter, mock_db)
    monitor.db = mock_db

    new_resources = await monitor.get_new_resources([], mock_filter)

    assert len(new_resources) == 0
