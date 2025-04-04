import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from alist_mikananirss.alist.tasks import AlistDownloadTask
from alist_mikananirss.core.download_manager import DownloadManager
from alist_mikananirss.websites.models import ResourceInfo, VideoQuality


@pytest.fixture
def setup_download_manager():
    mock_alist_client = AsyncMock()
    mock_alist_client.add_offline_download_task = AsyncMock()

    mock_db = AsyncMock()
    mock_db.insert_resource_info = AsyncMock()
    mock_db.delete_by_resource_title = AsyncMock()

    DownloadManager.destroy_instance()
    dm = DownloadManager(
        alist_client=mock_alist_client, base_download_path="/anime", db=mock_db
    )

    # Mock the task_monitor
    dm.task_monitor = MagicMock()
    dm.task_monitor.monitor = AsyncMock()

    return dm, mock_alist_client, mock_db


@pytest.fixture
def resources():
    return [
        ResourceInfo(
            resource_title="Test Anime S01E01",
            torrent_url="https://example.com/test1.torrent",
            anime_name="Test Anime",
            season=1,
            episode=1,
            quality=VideoQuality.p1080,
        ),
        ResourceInfo(
            resource_title="Another Anime S02E03",
            torrent_url="https://example.com/test2.torrent",
            anime_name="Another Anime",
            season=2,
            episode=3,
        ),
        ResourceInfo(
            resource_title="No Season E01",
            torrent_url="https://example.com/test3.torrent",
            anime_name="No Season",
            episode=1,
        ),
        ResourceInfo(
            resource_title="No Anime", torrent_url="https://example.com/test4.torrent"
        ),
    ]


@pytest.mark.asyncio
async def test_download(setup_download_manager, resources):
    # Mock the return value of add_offline_download_task
    dm, mock_alist_client, _ = setup_download_manager
    mock_tasks = [
        MagicMock(spec=AlistDownloadTask, url=resources[0].torrent_url),
        MagicMock(spec=AlistDownloadTask, url=resources[1].torrent_url),
        MagicMock(spec=AlistDownloadTask, url=resources[2].torrent_url),
        MagicMock(spec=AlistDownloadTask, url=resources[3].torrent_url),
    ]

    mock_alist_client.add_offline_download_task.side_effect = [
        [mock_tasks[0]],
        [mock_tasks[1]],
        [mock_tasks[2]],
        [mock_tasks[3]],
    ]

    # Call the function
    tasks = await dm.download(resources)

    # Check that add_offline_download_task was called with correct arguments
    assert mock_alist_client.add_offline_download_task.call_count == 4

    # Check that the correct number of tasks were returned
    assert len(tasks) == 4

    # Check that the returned tasks are the ones we mocked
    for mock_task in mock_tasks:
        assert mock_task in tasks


@pytest.mark.asyncio
async def test_download_grouping_by_path(setup_download_manager):
    dm, mock_alist_client, _ = setup_download_manager
    # Create resources that will have the same download path
    resources = [
        ResourceInfo(
            resource_title="Same Path 1",
            torrent_url="http://example.com/same1.torrent",
            anime_name="Same Anime",
            season=1,
            episode=1,
        ),
        ResourceInfo(
            resource_title="Same Path 2",
            torrent_url="http://example.com/same2.torrent",
            anime_name="Same Anime",
            season=1,
            episode=2,
        ),
    ]

    mock_tasks = [
        MagicMock(spec=AlistDownloadTask, url=resources[0].torrent_url),
        MagicMock(spec=AlistDownloadTask, url=resources[1].torrent_url),
    ]
    mock_alist_client.add_offline_download_task.return_value = mock_tasks

    # Call the function
    tasks = await dm.download(resources)

    # Check that add_offline_download_task was called once (grouped by path)
    mock_alist_client.add_offline_download_task.assert_called_once()

    # Check it was called with both URLs
    call_args = mock_alist_client.add_offline_download_task.call_args
    assert call_args[0][0] == os.path.join("/anime", "Same Anime", "Season 1")
    assert sorted(call_args[0][1]) == sorted([r.torrent_url for r in resources])

    assert len(tasks) == 2
    assert all(t in tasks for t in mock_tasks)


@pytest.mark.asyncio
async def test_download_exception_handling(setup_download_manager, resources):
    dm, mock_alist_client, _ = setup_download_manager
    # Make add_offline_download_task raise an exception
    mock_alist_client.add_offline_download_task.side_effect = Exception(
        "Test exception"
    )

    # Call the function
    tasks = await dm.download(resources)

    # Check that no tasks were returned
    assert len(tasks) == 0


@pytest.mark.asyncio
async def test_add_download_tasks(setup_download_manager, resources):
    # Mock the download method
    dm, _, mock_db = setup_download_manager
    mock_tasks = [
        MagicMock(spec=AlistDownloadTask, url=resources[0].torrent_url),
        MagicMock(spec=AlistDownloadTask, url=resources[1].torrent_url),
    ]
    dm.download = AsyncMock(return_value=mock_tasks)

    # Call the function
    await DownloadManager.add_download_tasks([resources[0], resources[1]])

    # Check that download was called with the correct arguments
    dm.download.assert_called_once_with([resources[0], resources[1]])

    # Check that insert_resource_info was called for each resource
    mock_db.insert_resource_info.assert_any_call(resources[0])
    mock_db.insert_resource_info.assert_any_call(resources[1])

    # Check that monitor was called for each task
    dm.task_monitor.monitor.assert_any_call(mock_tasks[0], resources[0])
    dm.task_monitor.monitor.assert_any_call(mock_tasks[1], resources[1])


@pytest.mark.asyncio
async def test_add_download_tasks_no_tasks(setup_download_manager, resources):
    # Mock the download method to return an empty list
    dm, _, mock_db = setup_download_manager
    dm.download = AsyncMock(return_value=[])

    # Call the function
    await DownloadManager.add_download_tasks([resources[0], resources[1]])

    # Check that insert_resource_info was not called (no tasks returned)
    mock_db.insert_resource_info.assert_not_called()

    # Check that monitor was not called (no tasks returned)
    dm.task_monitor.monitor.assert_not_called()


@pytest.mark.asyncio
async def test_add_download_tasks_unmatched_task(setup_download_manager, resources):
    dm, _, mock_db = setup_download_manager
    # Mock a task that doesn't match any resource
    unmatched_task = MagicMock(
        spec=AlistDownloadTask, url="http://example.com/unmatched.torrent"
    )
    matched_task = MagicMock(spec=AlistDownloadTask, url=resources[0].torrent_url)
    dm.download = AsyncMock(return_value=[matched_task, unmatched_task])

    # Call the function
    await DownloadManager.add_download_tasks([resources[0]])

    # Check that only the matched resource was processed
    mock_db.insert_resource_info.assert_called_once_with(resources[0])
    dm.task_monitor.monitor.assert_called_once_with(matched_task, resources[0])
