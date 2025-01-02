from unittest.mock import AsyncMock, patch

import pytest
from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.core import AnimeRenamer
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture(autouse=True)
def reset_anime_renamer():
    AnimeRenamer._instances.pop(AnimeRenamer, None)
    yield
    AnimeRenamer._instances.pop(AnimeRenamer, None)


@pytest.fixture
def alist_mock():
    return AsyncMock(spec=Alist)


@pytest.fixture
def resource_info():
    return ResourceInfo(
        resource_title="title",
        torrent_url="https://test1.torrent",
        published_date="1",
        anime_name="Test Anime",
        season=1,
        episode=5,
        fansub="TestSub",
        quality="1080p",
        language="JP",
    )


@pytest.mark.asyncio
async def test_initialize():
    alist = AsyncMock(spec=Alist)
    rename_format = "{name} - {season}x{episode}"

    AnimeRenamer.initialize(alist, rename_format)

    assert AnimeRenamer().alist_client == alist
    assert AnimeRenamer().rename_format == rename_format


@pytest.mark.asyncio
async def test_build_new_name(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"

    alist_mock.list_dir.return_value = ["file1", "file2", "file3"]

    new_filename = await AnimeRenamer()._build_new_name(old_filepath, resource_info)

    expected_filename = "Test Anime S01E05.mp4"
    assert new_filename == expected_filename


@pytest.mark.asyncio
async def test_build_new_name_ova(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"
    resource_info.season = 0

    alist_mock.list_dir.return_value = ["file1", "file2", "file3"]

    new_filename = await AnimeRenamer()._build_new_name(old_filepath, resource_info)

    expected_filename = "Test Anime S00E03.mp4"
    assert new_filename == expected_filename


@pytest.mark.asyncio
async def test_build_new_name_version(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"
    resource_info.version = 2

    new_filename = await AnimeRenamer()._build_new_name(old_filepath, resource_info)

    expected_filename = "Test Anime S01E05 v2.mp4"
    assert new_filename == expected_filename


@pytest.mark.asyncio
async def test_rename_success(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"

    with patch.object(AnimeRenamer, "_build_new_name", return_value="new_file.mp4"):
        await AnimeRenamer.rename(old_filepath, resource_info)

    alist_mock.rename.assert_called_once_with(old_filepath, "new_file.mp4")


@pytest.mark.asyncio
async def test_rename_retry(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"

    alist_mock.rename.side_effect = [Exception("Error"), Exception("Error"), None]

    with patch.object(AnimeRenamer, "_build_new_name", return_value="new_file.mp4"):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await AnimeRenamer.rename(old_filepath, resource_info)

    assert alist_mock.rename.call_count == 3


@pytest.mark.asyncio
async def test_rename_max_retry_exceeded(alist_mock, resource_info):
    AnimeRenamer.initialize(alist_mock, "{name} S{season:02d}E{episode:02d}")

    old_filepath = "/path/to/old_file.mp4"

    alist_mock.rename.side_effect = Exception("Error")

    with patch.object(AnimeRenamer, "_build_new_name", return_value="new_file.mp4"):
        with patch.object(logger, "error") as mock_logger_error:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await AnimeRenamer.rename(old_filepath, resource_info)

    assert alist_mock.rename.call_count == 3
    mock_logger_error.assert_called_once()
