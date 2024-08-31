from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTaskCollection,
    AlistTaskStatus,
    AlistTaskType,
)
from alist_mikananirss.core.download_manager import TaskMonitor
from tenacity import wait_none


@pytest.fixture
def mock_alist():
    return AsyncMock(spec=Alist)


@pytest.fixture
def mock_task():
    return MagicMock(
        spec=AlistDownloadTask, tid="123", task_type=AlistTaskType.DOWNLOAD
    )


@pytest.fixture
def task_monitor(mock_alist, mock_task):
    return TaskMonitor(mock_alist, mock_task)


@pytest.mark.asyncio
async def test_refresh_success(task_monitor, mock_alist, mock_task):
    updated_task = MagicMock(
        spec=AlistDownloadTask, tid="123", status=AlistTaskStatus.Running, progress=0.5
    )
    mock_alist.get_task_list.return_value = AlistTaskCollection([updated_task])

    await task_monitor._refresh()

    mock_alist.get_task_list.assert_called_once_with(mock_task.task_type)
    assert task_monitor.task == updated_task


@pytest.mark.asyncio
async def test_refresh_task_not_found(task_monitor, mock_alist):
    mock_alist.get_task_list.return_value = AlistTaskCollection([])

    with pytest.raises(RuntimeError):
        task_monitor._refresh.retry.wait = wait_none()
        await task_monitor._refresh()


@pytest.mark.asyncio
async def test_wait_finished_success(task_monitor):
    progresses = [0, 50, 100]
    mock_tasks = [
        MagicMock(
            spec=AlistDownloadTask,
            tid="123",
            status=AlistTaskStatus.Running,
            progress=p,
        )
        for p in progresses
    ]
    mock_tasks[-1].status = AlistTaskStatus.Succeeded
    success_task = mock_tasks[-1]

    async def mock_refresh():
        task_monitor.task = mock_tasks.pop(0)

    with (
        patch.object(task_monitor, "_refresh", side_effect=mock_refresh),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("time.time", side_effect=[0, 1, 2, 3]),
    ):
        result = await task_monitor.wait_finished()

    assert result == success_task
    assert result.status == AlistTaskStatus.Succeeded


@pytest.mark.asyncio
async def test_wait_finished_failed(task_monitor):
    mock_task_failed = MagicMock(
        spec=AlistDownloadTask, tid="123", status=AlistTaskStatus.Failed, progress=0.5
    )

    async def mock_refresh():
        task_monitor.task = mock_task_failed

    with (
        patch.object(
            task_monitor,
            "_refresh",
            side_effect=mock_refresh,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await task_monitor.wait_finished()

    assert result == mock_task_failed
    assert result.status == AlistTaskStatus.Failed


@pytest.mark.asyncio
async def test_wait_finished_stalled(task_monitor):
    async def mock_refresh():
        task_monitor.task = mock_task

    mock_task = MagicMock(
        spec=AlistDownloadTask, tid="123", status=AlistTaskStatus.Running, progress=0.5
    )

    with (
        patch.object(task_monitor, "_refresh", side_effect=mock_refresh),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("time.time", side_effect=[0] + list(range(1, 302))),
    ):  # Simulate 301 seconds of no progress
        with pytest.raises(TimeoutError):
            await task_monitor.wait_finished()


@pytest.mark.parametrize("task_type", [AlistTaskType.DOWNLOAD, AlistTaskType.TRANSFER])
def test_normal_status(task_type):
    assert set(TaskMonitor.NORMAL_STATUSES) == {
        AlistTaskStatus.Pending,
        AlistTaskStatus.Running,
        AlistTaskStatus.StateBeforeRetry,
        AlistTaskStatus.StateWaitingRetry,
    }
