from unittest.mock import AsyncMock, patch

import pytest

from alist_mikananirss.alist.api import Alist
from alist_mikananirss.alist.tasks import (
    AlistDeletePolicy,
    AlistDownloaderType,
    AlistDownloadTask,
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
                    "error": "",
                    "id": "lwYyV7TlpdS06fiflUmBH",
                    "name": "download magnet:?xt=xxx to (/Local/颂乐人偶/Season 1)",
                    "progress": 0.0,
                    "state": 1,
                    "status": "offline download waiting",
                }
            ]
        }
        tasks = await alist.add_offline_download_task(
            "/Local/颂乐人偶/Season 1", ["magnet:?xt=xxx"]
        )
        assert isinstance(tasks[0], AlistDownloadTask)
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/add_offline_download",
            json={
                "delete_policy": AlistDeletePolicy.DeleteAlways.value,
                "path": "/Local/颂乐人偶/Season 1",
                "urls": ["magnet:?xt=xxx"],
                "tool": alist.downloader.value,
            },
        )


@pytest.mark.asyncio
async def test_list_dir(alist):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        mock_api_call.return_value = {
            "content": [{"name": "file1.txt"}, {"name": "file2.txt"}]
        }
        files = await alist.list_dir("/test/path")
        assert files == ["file1.txt", "file2.txt"]


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
        await alist.rename("/old/path/file.txt", "new_file.txt")
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/rename",
            json={"path": "/old/path/file.txt", "name": "new_file.txt"},
        )


def test_dl_task_extract():
    task = AlistDownloadTask.from_json(
        {
            "error": "",
            "id": "lwYyV7TlpdS06fiflUmBH",
            "name": "download magnet:?xt=xxx to (/Local/颂乐人偶/Season 1)",
            "progress": 100,
            "state": 2,
            "status": "offline download completed, waiting for seeding",
        }
    )

    assert task.url == "magnet:?xt=xxx"
    assert task.download_path == "/Local/颂乐人偶/Season 1"
    assert task.task_type == AlistTaskType.DOWNLOAD


def test_alist_transfer_task():
    task = AlistTransferTask.from_json(
        {
            "error": "",
            "id": "i-T7dWBTgh_9bohMpRlcA",
            "name": "transfer /path/to/alist/data/temp/qBittorrent/107bd39c-44fa-4891-a930-8c101a31adca/subfolder/Avemujica 03.mp4 to [/Local/颂乐人偶/Season 1]",
            "progress": 100.0000041135186,
            "state": 2,
            "status": "transferring",
        }
    )

    assert task.uuid == "107bd39c-44fa-4891-a930-8c101a31adca"
    assert task.target_path == "/Local/颂乐人偶/Season 1/subfolder/Avemujica 03.mp4"
    assert task.task_type == AlistTaskType.TRANSFER
