from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTaskState,
    AlistTaskType,
    AlistTransferTask,
)
from alist_mikananirss.core.download_manager import TaskMonitor
from alist_mikananirss.websites.models import ResourceInfo


@pytest.fixture
def setup_task_monitor():
    alist_mock = AsyncMock()

    db_mock = AsyncMock()

    tm = TaskMonitor(
        alist_client=alist_mock,
        db=db_mock,
        use_renamer=True,
        need_notification=True,
    )

    return tm, alist_mock, db_mock


@pytest.fixture
def create_task():
    def _create_download_task(tid, state, url, download_path):
        task = MagicMock(spec=AlistDownloadTask)
        task.tid = tid
        task.state = state
        task.url = url
        task.download_path = download_path
        task.task_type = AlistTaskType.DOWNLOAD
        task.error = ""
        task.start_time = datetime.now()
        task.end_time = None
        task.progress = 0.0
        return task

    def _create_transfer_task(tid, state, uuid, target_path):
        task = MagicMock(spec=AlistTransferTask)
        task.tid = tid
        task.state = state
        task.uuid = uuid
        task.target_path = target_path
        task.task_type = AlistTaskType.TRANSFER
        task.error = ""
        task.start_time = datetime.now()
        task.end_time = None
        task.progress = 0.0
        return task

    return _create_download_task, _create_transfer_task


@pytest.mark.asyncio
async def test_monitor_successful_download_and_transfer(
    setup_task_monitor, create_task
):
    tm, alist_mock, db_mock = setup_task_monitor
    create_download_task, create_transfer_task = create_task

    # Create a download task in running state
    dl_task = create_download_task(
        tid="dl1",
        state=AlistTaskState.Running,
        url="http://example.com/test.torrent",
        download_path="/test/path/anime",
    )

    # Create a resource info
    resource = ResourceInfo(
        resource_title="Test Anime S01E01",
        torrent_url="http://example.com/test.torrent",
        anime_name="Test Anime",
        season=1,
        episode=1,
    )

    # Create a transfer task that will be returned when the download completes
    tf_task = create_transfer_task(
        tid="tf1",
        state=AlistTaskState.Running,
        uuid="uuid123",
        target_path="/test/path/anime/test_video.mkv",
    )

    # Mock the get_task_list method to simulate task state transitions
    # First call: download task is now succeeded
    # Second call: transfer task is running
    # Third call: transfer task is succeeded
    calls = []

    async def get_task_list_side_effect(task_type):
        calls.append(task_type)

        if len(calls) <= 2:  # First iteration
            if task_type == AlistTaskType.DOWNLOAD:
                dl_task.state = AlistTaskState.Succeeded
                return [dl_task]
            else:
                return [tf_task]
        elif len(calls) <= 4:  # Second iteration
            if task_type == AlistTaskType.DOWNLOAD:
                return [dl_task]
            else:
                return [tf_task]
        else:  # Third iteration
            if task_type == AlistTaskType.DOWNLOAD:
                return [dl_task]
            else:
                tf_task.state = AlistTaskState.Succeeded
                return [tf_task]

    alist_mock.get_task_list.side_effect = get_task_list_side_effect

    # Mock is_video to always return True
    with patch("alist_mikananirss.utils.is_video", return_value=True):
        # Mock _find_transfer_task to return our transfer task
        tm._find_transfer_task = AsyncMock(return_value=tf_task)

        # Mock _post_process
        tm._post_process = AsyncMock()

        # Run the monitor function with a timeout to prevent infinite loop
        await tm.monitor(dl_task, resource)
        await tm.wait_finished()

    # Verify that the download task is linked to a transfer task
    assert tm._find_transfer_task.called, "Should have tried to find a transfer task"
    assert tm._find_transfer_task.await_args[0][0] == dl_task

    # Verify that post-process was called for the successful transfer task
    assert tm._post_process.called
    post_process_args = tm._post_process.await_args[0]
    assert post_process_args[0] == tf_task
    assert post_process_args[1] == resource

    # Verify that completed tasks are removed from running_tasks
    assert not tm.running_tasks, "All tasks should be removed from running_tasks"
    assert (
        not tm.task_resource_map
    ), "All tasks should be removed from task_resource_map"


@pytest.mark.asyncio
async def test_monitor_failed_download(setup_task_monitor, create_task):
    tm, alist_mock, db_mock = setup_task_monitor
    create_download_task, _ = create_task

    # Create a download task that will fail
    dl_task = create_download_task(
        tid="dl1",
        state=AlistTaskState.Running,
        url="http://example.com/test.torrent",
        download_path="/test/path/anime",
    )

    # Create a resource info
    resource = ResourceInfo(
        resource_title="Test Anime S01E01",
        torrent_url="http://example.com/test.torrent",
        anime_name="Test Anime",
        season=1,
        episode=1,
    )

    # Mock get_task_list to return the failed download task
    async def get_task_list_side_effect(task_type):
        if task_type == AlistTaskType.DOWNLOAD:
            dl_task.state = AlistTaskState.Failed
            dl_task.error = "Download error"
            return [dl_task]
        else:
            return []

    alist_mock.get_task_list.side_effect = get_task_list_side_effect

    # Run the monitor
    await tm.monitor(dl_task, resource)
    await tm.wait_finished()

    # Verify that the task is removed from running_tasks
    assert not tm.running_tasks, "Failed task should be removed from running_tasks"
    assert (
        not tm.task_resource_map
    ), "Failed task should be removed from task_resource_map"

    # Verify that the resource is deleted from the database
    db_mock.delete_by_resource_title.assert_called_once_with(resource.resource_title)


@pytest.mark.asyncio
async def test_monitor_no_transfer_task_found(setup_task_monitor, create_task):
    tm, alist_mock, db_mock = setup_task_monitor
    create_download_task, _ = create_task

    # Create a download task that will succeed but with no matching transfer task
    dl_task = create_download_task(
        tid="dl1",
        state=AlistTaskState.Running,
        url="http://example.com/test.torrent",
        download_path="/test/path/anime",
    )

    # Create a resource info
    resource = ResourceInfo(
        resource_title="Test Anime S01E01",
        torrent_url="http://example.com/test.torrent",
        anime_name="Test Anime",
        season=1,
        episode=1,
    )

    # Mock get_task_list to return the successful download task
    async def get_task_list_side_effect(task_type):
        if task_type == AlistTaskType.DOWNLOAD:
            dl_task.state = AlistTaskState.Succeeded
            return [dl_task]
        else:
            return []

    alist_mock.get_task_list.side_effect = get_task_list_side_effect

    # Mock _find_transfer_task to return None
    tm._find_transfer_task = AsyncMock(return_value=None)

    # Run the monitor
    await tm.monitor(dl_task, resource)
    await tm.wait_finished()

    # Verify that _find_transfer_task was called
    tm._find_transfer_task.assert_called_once_with(dl_task)

    # Verify that the task is removed from running_tasks
    assert not tm.running_tasks, "Task should be removed from running_tasks"
    assert not tm.task_resource_map, "Task should be removed from task_resource_map"
