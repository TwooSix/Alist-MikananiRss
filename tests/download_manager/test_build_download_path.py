import os
from unittest.mock import AsyncMock

import pytest

from alist_mikananirss.core import DownloadManager
from alist_mikananirss.websites.entities import ResourceInfo


@pytest.fixture
def base_path():
    return "/base/path"


@pytest.mark.asyncio
async def test_initialize(base_path):
    mock_alist = AsyncMock()
    mock_db = AsyncMock()
    DownloadManager.initialize(mock_alist, base_path, True, True, mock_db)
    assert DownloadManager().base_download_path == base_path


def test_build_download_path_without_anime_name(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
    )
    expected_path = base_path
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_anime_name(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name="Test Anime",
    )
    expected_path = os.path.join(base_path, "Test Anime")
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_anime_name_and_season(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name="Test Anime",
        season=1,
    )
    expected_path = os.path.join(base_path, "Test Anime", "Season 1")
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_season_no_anime_name(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        season=1,
    )
    expected_path = base_path
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_special_characters(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name="Test:Anime!",
        season=2,
    )
    expected_path = os.path.join(base_path, "Test Anime!", "Season 2")
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_empty_anime_name(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name="",
        season=3,
    )
    expected_path = base_path
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_none_anime_name(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name=None,
        season=4,
    )
    expected_path = base_path
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path


def test_build_download_path_with_special_season(base_path):
    resource = ResourceInfo(
        resource_title="Test Resource",
        torrent_url="https://example.com/torrent",
        published_date="2023-05-20",
        anime_name="Test Anime",
        season=0,
    )
    expected_path = os.path.join(base_path, "Test Anime", "Season 0")
    test_instance = DownloadManager()
    assert test_instance._build_download_path(resource) == expected_path
