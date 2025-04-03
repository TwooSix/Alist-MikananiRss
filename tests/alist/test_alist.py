from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from alist_mikananirss.alist.api import Alist
from alist_mikananirss.alist.tasks import (
    AlistDeletePolicy,
    AlistDownloaderType,
    AlistDownloadTask,
    AlistTaskState,
    AlistTaskType,
    AlistTransferTask,
)
from datetime import datetime
import random


@pytest.fixture
def alist():
    return Alist(
        base_url="https://example.com",
        token="test_token",
        downloader=AlistDownloaderType.ARIA,
    )


@pytest.fixture
def create_task_json():
    def _create_download_task_json(tid, state, url, download_path, status=None):
        task_json_dict = {
            "creator": "alist_mikananirss",
            "creator_role": 2,
            "end_time": None,
            "error": "",
            "id": tid,
            "name": f"download {url} to ({download_path})",
            "progress": 100,
            "start_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "state": state,
            "status": status if status else "[qBittorrent]: [qBittorrent] downloading",
            "total_bytes": random.randint(1000000, 1000000000),
        }
        return task_json_dict

    def _create_transfer_task_json(
        tid, state, uuid, target_drive, target_dir, filename, total_bytes=None
    ):
        task_json_dict = {
            "creator": "twosix",
            "creator_role": 2,
            "end_time": None,
            "error": "",
            "id": tid,
            "name": f"transfer [](/opt/alist/data/temp/qBittorrent/{uuid}/{filename}) to [{target_drive}]({target_dir})",
            "progress": 100,
            "start_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "state": state,
            "status": "getting src object",
            "total_bytes": (
                total_bytes if total_bytes else random.randint(1000000, 1000000000)
            ),
        }
        return task_json_dict

    return _create_download_task_json, _create_transfer_task_json


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
async def test_add_offline_download_task(alist, create_task_json):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        create_dl_task_json, _ = create_task_json
        json_data = create_dl_task_json(
            "dl1",
            AlistTaskState.Running,
            "magnet:?xt=xxx",
            "/Local/Anime/Season 1",
        )
        mock_api_call.return_value = {
            "tasks": [json_data],
        }

        tasks = await alist.add_offline_download_task(
            "/Local/Anime/Season 1", ["magnet:?xt=xxx"]
        )
        assert isinstance(tasks[0], AlistDownloadTask)
        mock_api_call.assert_called_once_with(
            "POST",
            "api/fs/add_offline_download",
            json={
                "delete_policy": AlistDeletePolicy.DeleteAlways.value,
                "path": "/Local/Anime/Season 1",
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
async def test_cancel_task(alist, create_task_json):
    with patch.object(alist, "_api_call", new_callable=AsyncMock) as mock_api_call:
        create_dl_task_json, _ = create_task_json
        json_data = create_dl_task_json(
            "dl1", AlistTaskState.Running, "magnet:?xt=xxx", "/Local/Anime/Season 1"
        )
        task = AlistDownloadTask.from_json(json_data)
        result = await alist.cancel_task(task)
        assert result is True
        mock_api_call.assert_called_once_with(
            "POST", f"/api/task/offline_download/cancel?tid={json_data['id']}"
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


def test_dl_task_extract(create_task_json):
    create_dl_task_json, _ = create_task_json
    test_url = "magnet:?xt=testtorrent1"
    test_path = "/Local/Anime/Season 1"
    json_data = create_dl_task_json(
        "dl1",
        AlistTaskState.Running,
        test_url,
        test_path,
    )

    task: AlistDownloadTask = AlistDownloadTask.from_json(json_data)

    assert task.url == test_url
    assert task.download_path == test_path
    assert task.task_type == AlistTaskType.DOWNLOAD

    # seeding situation
    json_data = create_dl_task_json(
        "dl1",
        AlistTaskState.Running,
        test_url,
        test_path,
        "offline download completed, waiting for seeding",
    )
    task2 = AlistDownloadTask.from_json(json_data)
    assert task2.state == AlistTaskState.Succeeded


def test_tf_task_extract(create_task_json):
    _, create_tf_task_json = create_task_json
    test_uuid = "d82ddec1-08f6-4894-b7ed-d9c9f25dc4db"
    test_target_drive = "/Google"
    test_target_dir = "/Debug/test/Season 1"
    test_filename = "test.mkv"
    json_data = create_tf_task_json(
        "tf1",
        AlistTaskState.Running,
        test_uuid,
        test_target_drive,
        test_target_dir,
        test_filename,
    )
    task: AlistTransferTask = AlistTransferTask.from_json(
        json_data,
    )

    assert task.uuid == test_uuid
    assert task.target_path == test_target_drive + test_target_dir + "/" + test_filename
    assert task.task_type == AlistTaskType.TRANSFER
