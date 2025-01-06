import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alist_mikananirss.alist.api import Alist
from alist_mikananirss.alist.tasks import (
    AlistDeletePolicy,
    AlistDownloaderType,
    AlistDownloadTask,
    AlistTaskCollection,
    AlistTaskState,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)


@pytest.fixture
def alist():
    return Alist(
        base_url="https://example.com",
        token="test_token",
        downloader=AlistDownloaderType.ARIA,
    )


@pytest.mark.asyncio
async def test_alist_init(alist):
    assert alist.base_url == "https://example.com"
    assert alist.token == "test_token"
    assert alist.downloader == AlistDownloaderType.ARIA


@pytest.mark.asyncio
async def test_get_alist_ver(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        mock_api_call.return_value = {"version": "v2.0.0"}
        version = await alist.get_alist_ver()
        assert version == "2.0.0"
        mock_api_call.assert_called_once_with("GET", "/api/public/settings")


@pytest.mark.asyncio
async def test_add_offline_download_task(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        mock_api_call.return_value = {
            "tasks": [
                {
                    "id": "task1",
                    "name": "download https://example.com/file.zip to /path/to/save",
                    "state": 0,
                    "progress": 0.0,
                    "error": None,
                }
            ]
        }
        tasks = await alist.add_offline_download_task(
            "/path/to/save", ["https://example.com/file.zip"]
        )
        assert isinstance(tasks, AlistTaskCollection)
        assert len(tasks) == 1
        assert isinstance(tasks[0], AlistDownloadTask)
        assert tasks[0].tid == "task1"
        assert tasks[0].url == "https://example.com/file.zip"
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/add_offline_download",
            json={
                "delete_policy": AlistDeletePolicy.DeleteAlways.value,
                "path": "/path/to/save",
                "urls": ["https://example.com/file.zip"],
                "tool": AlistDownloaderType.ARIA.value,
            },
        )


@pytest.mark.asyncio
async def test_upload(alist):
    with (
        patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call,
        patch("os.path.abspath", return_value="/local/path/file.txt"),
        patch("os.stat") as mock_stat,
        patch("builtins.open", create=True) as mock_open,
        patch("mimetypes.guess_type", return_value=("application/octet-stream", None)),
    ):

        mock_stat.return_value = MagicMock(st_size=1024)
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file

        result = await alist.upload("/remote/path", "/local/path/file.txt")

        assert result is True
        mock_api_call.assert_called_once()
        args, kwargs = mock_api_call.call_args
        assert args[0] == "PUT"
        assert args[1] == "api/fs/put"
        assert kwargs["custom_headers"]["file-path"] == "/remote/path/file.txt"
        assert kwargs["custom_headers"]["Content-Type"] == "application/octet-stream"
        assert kwargs["data"] == mock_file


@pytest.mark.asyncio
async def test_list_dir(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        mock_api_call.return_value = {
            "content": [{"name": "file1.txt"}, {"name": "file2.txt"}]
        }
        files = await alist.list_dir("/test/path")
        assert files == ["file1.txt", "file2.txt"]
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/list",
            json={
                "path": "/test/path",
                "password": None,
                "page": 1,
                "per_page": 30,
                "refresh": False,
            },
        )


@pytest.mark.asyncio
async def test_get_task_list(alist):
    with patch.object(
        alist, "_fetch_tasks", new_callable=AsyncMock
    ) as mock_fetch_tasks:
        mock_fetch_tasks.return_value = AlistTaskCollection(
            [
                AlistDownloadTask(
                    tid="task1",
                    description="test task",
                    status=AlistTaskStatus.Running,
                    progress=0.5,
                )
            ]
        )
        tasks = await alist.get_task_list(AlistTaskType.DOWNLOAD, AlistTaskState.UNDONE)
        assert isinstance(tasks, AlistTaskCollection)
        assert len(tasks) == 1
        assert tasks[0].tid == "task1"
        mock_fetch_tasks.assert_called_once_with(
            AlistTaskType.DOWNLOAD, AlistTaskState.UNDONE
        )


@pytest.mark.asyncio
async def test_cancel_task(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        task = AlistDownloadTask(
            tid="task1",
            description="test task",
            status=AlistTaskStatus.Running,
            progress=0.5,
        )
        result = await alist.cancel_task(task)
        assert result is True
        mock_api_call.assert_called_once_with(
            "POST", "/api/admin/task/offline_download/cancel?tid=task1"
        )


@pytest.mark.asyncio
async def test_rename(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        result = await alist.rename("/old/path/file.txt", "new_file.txt")
        assert result is True
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/rename",
            json={"path": "/old/path/file.txt", "name": "new_file.txt"},
        )


def test_alist_task_collection():
    task1 = AlistDownloadTask(
        tid="task1",
        description="test task 1",
        status=AlistTaskStatus.Running,
        progress=0.5,
    )
    task2 = AlistDownloadTask(
        tid="task2",
        description="test task 2",
        status=AlistTaskStatus.Pending,
        progress=0.0,
    )

    collection = AlistTaskCollection([task1, task2])

    assert len(collection) == 2
    assert collection["task1"] == task1
    assert collection[0] == task1
    assert task1 in collection

    task3 = AlistDownloadTask(
        tid="task3",
        description="test task 3",
        status=AlistTaskStatus.Succeeded,
        progress=1.0,
    )
    collection.add_task(task3)

    assert len(collection) == 3
    assert collection["task3"] == task3

    new_collection = AlistTaskCollection([task1])
    combined_collection = collection + new_collection

    assert len(combined_collection) == 3
    assert combined_collection["task1"] == task1
    assert combined_collection["task2"] == task2
    assert combined_collection["task3"] == task3


def test_alist_download_task():
    task = AlistDownloadTask.from_json(
        {
            "id": "task1",
            "name": "download https://example.com/file.zip to /path/to/save",
            "state": 1,
            "progress": 0.5,
            "error": None,
        }
    )

    assert task.tid == "task1"
    assert task.description == "download https://example.com/file.zip to /path/to/save"
    assert task.status == AlistTaskStatus.Running
    assert math.isclose(task.progress, 0.5, rel_tol=1e-9, abs_tol=1e-9)
    assert task.error_msg is None
    assert task.url == "https://example.com/file.zip"
    assert task.task_type == AlistTaskType.DOWNLOAD


def test_alist_transfer_task():
    task = AlistTransferTask.from_json(
        {
            "id": "task1",
            "name": "transfer /root/program/alist/data/temp/qBittorrent/b33f58c0-5357-4c9d-bf43-334fc3e622a4/[KTXP][Grisaia_Phantom_Trigger][01][GB_CN][HEVC_opus][1080p]/[KTXP][Grisaia_Phantom_Trigger][01][GB_CN][HEVC_opus][1080p].mkv to [/Onedrive/Anime/灰色：幻影扳机/Season 2]",
            "state": 2,
            "progress": 1.0,
            "error": None,
        }
    )

    assert task.tid == "task1"
    assert task.status == AlistTaskStatus.Succeeded
    assert math.isclose(task.progress, 1.0, rel_tol=1e-9, abs_tol=1e-9)
    assert task.error_msg is None
    assert task.uuid == "b33f58c0-5357-4c9d-bf43-334fc3e622a4"
    assert (
        task.file_name
        == "[KTXP][Grisaia_Phantom_Trigger][01][GB_CN][HEVC_opus][1080p]/[KTXP][Grisaia_Phantom_Trigger][01][GB_CN][HEVC_opus][1080p].mkv"
    )
    assert task.task_type == AlistTaskType.TRANSFER
