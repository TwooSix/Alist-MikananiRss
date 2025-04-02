import os
import secrets
import string
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import wait_none, RetryError

from alist_mikananirss import AnimeDownloadTaskInfo, DownloadManager, SubscribeDatabase
from alist_mikananirss.alist import (
    Alist,
    AlistClientError,
    AlistDownloadTask,
    AlistTaskList,
    AlistTaskStatus,
    AlistTransferTask,
)
from alist_mikananirss.websites.models import LanguageType, ResourceInfo


@pytest.fixture
def download_path():
    return "/base/path"


def get_incomplete_download_task(resource):
    test_instance = DownloadManager()
    alphabet = "_-" + string.digits + string.ascii_letters
    tid = "".join(secrets.choice(alphabet) for _ in range(21))
    download_path = test_instance._build_download_path(resource).replace(os.sep, "/")
    json_data = {
        "error": "",
        "id": tid,
        "name": f"download {resource.torrent_url} to ({download_path})",
        "progress": 50.0,
        "state": 1,
        "status": "offline downloading",
    }

    return AlistDownloadTask.from_json(json_data)


def get_complete_download_task(download_task):
    new_task = deepcopy(download_task)
    new_task.status = AlistTaskStatus.Succeeded
    new_task.progress = 100
    return new_task


def get_incomplete_transfer_task(resource):
    test_instance = DownloadManager()
    alphabet = "_-" + string.digits + string.ascii_letters
    tid = "".join(secrets.choice(alphabet) for _ in range(21))
    uuid = "".join(
        secrets.choice(string.digits + string.ascii_lowercase) for _ in range(36)
    )
    download_path = test_instance._build_download_path(resource).replace(os.sep, "/")

    cleaned_path = download_path.strip("/")
    parts = cleaned_path.split("/", 1)
    tgt_drive = "/" + parts[0]
    drive_subdir = ""
    if len(parts) > 1:
        drive_subdir = "/" + parts[1]

    json_data = {
        "error": "",
        "id": tid,
        "name": f"transfer [](/path/to/alist/data/temp/qBittorrent/{uuid}/subfolder/{resource.anime_name}/filename.mp4) to [{tgt_drive}]({drive_subdir})",
        "progress": 50.0,
        "state": 1,
        "status": "running",
    }
    return AlistTransferTask.from_json(json_data)


def get_complete_transfer_task(transfer_task):
    new_task = deepcopy(transfer_task)
    new_task.status = AlistTaskStatus.Succeeded
    new_task.progress = 100
    return new_task


@pytest.fixture
def test_resources():
    resources = [
        # basic info
        ResourceInfo(
            resource_title="title1",
            torrent_url="https://test1.torrent",
        ),
        # only anime name
        ResourceInfo(
            resource_title="title2",
            torrent_url="https://test2.torrent",
            anime_name="Test Anime",
        ),
        # full info
        ResourceInfo(
            resource_title="title3",
            torrent_url="https://test3.torrent",
            published_date="1",
            anime_name="Test Anime",
            season=1,
            episode=5,
            fansub="TestSub",
            quality="1080p",
            languages=[LanguageType.SIMPLIFIED_CHINESE],
        ),
    ]
    return resources


@pytest.fixture
def download_manager(download_path):
    mock_alist = AsyncMock(spec=Alist)
    mock_db = AsyncMock(spec=SubscribeDatabase)
    DownloadManager.initialize(
        mock_alist, download_path, use_renamer=True, need_notification=True, db=mock_db
    )
    DownloadManager().alist_client = mock_alist
    DownloadManager().db = mock_db
    return DownloadManager()


@pytest.mark.asyncio
async def test_download_success(download_manager, test_resources):
    incomplete_download_tasks = []
    for resource in test_resources:
        incomplete_download_tasks.append(get_incomplete_download_task(resource))

    side_effect = []
    tasks_by_path = {}
    for task in incomplete_download_tasks:
        path = task.download_path
        if path not in tasks_by_path:
            tasks_by_path[path] = []
        tasks_by_path[path].append(task)

    for tasks in tasks_by_path.values():
        side_effect.append(AlistTaskList(tasks))

    download_manager.alist_client.add_offline_download_task.side_effect = side_effect

    with patch("asyncio.create_task", new_callable=MagicMock):
        with patch.object(download_manager, "monitor", new_callable=MagicMock):
            await DownloadManager.add_download_tasks(test_resources)

            assert (
                download_manager.alist_client.add_offline_download_task.call_count
                == len(side_effect)
            )
            assert download_manager.db.insert_resource_info.call_count == len(
                test_resources
            )
            calls = download_manager.db.insert_resource_info.call_args_list
            for i in range(len(test_resources)):
                assert calls[i].args[0] == test_resources[i]


@pytest.mark.asyncio
async def test_download_failed(download_manager, test_resources):
    incomplete_download_tasks = []
    for resource in test_resources:
        incomplete_download_tasks.append(get_incomplete_download_task(resource))

    task_lists = []
    tasks_by_path = {}
    for task in incomplete_download_tasks:
        path = task.download_path
        if path not in tasks_by_path:
            tasks_by_path[path] = []
        tasks_by_path[path].append(task)

    for tasks in tasks_by_path.values():
        task_lists.append(AlistTaskList(tasks))
    side_effect = []
    for i in range(len(task_lists)):
        if i == 0:
            side_effect.append(task_lists[i])
        else:
            side_effect.append(TimeoutError)

    download_manager.alist_client.add_offline_download_task.side_effect = side_effect

    with patch("asyncio.create_task", new_callable=MagicMock):
        with patch.object(download_manager, "monitor", new_callable=MagicMock):
            await DownloadManager.add_download_tasks(test_resources)
            assert (
                download_manager.alist_client.add_offline_download_task.call_count
                == len(task_lists)
            )
            assert download_manager.db.insert_resource_info.call_count == 1
            calls = download_manager.db.insert_resource_info.call_args_list
            assert calls[0].args[0] == test_resources[0]


@pytest.mark.asyncio
async def test_monitor_success(download_manager, test_resources):
    incomplete_download_tasks = []
    complete_download_tasks = []
    incomplete_transfer_tasks = []
    complete_transfer_tasks = []

    for resource in test_resources:
        incomplete_download_tasks.append(get_incomplete_download_task(resource))
        complete_download_tasks.append(
            get_complete_download_task(incomplete_download_tasks[-1])
        )
        incomplete_transfer_tasks.append(get_incomplete_transfer_task(resource))
        complete_transfer_tasks.append(
            get_complete_transfer_task(incomplete_transfer_tasks[-1])
        )

    task_info_list = []
    for i in range(len(test_resources)):
        task_info_list.append(
            AnimeDownloadTaskInfo(
                resource=test_resources[i],
                download_task=incomplete_download_tasks[i],
            )
        )

    with (
        patch(
            "alist_mikananirss.core.download_manager.TaskMonitor"
        ) as mock_task_monitor,
        patch.object(download_manager, "_post_process") as mock_post_process,
        patch.object(
            download_manager, "_find_transfer_task"
        ) as mock_find_transfer_task,
    ):
        for i in range(len(test_resources)):
            dl_monitor = AsyncMock()
            dl_monitor.wait_finished.side_effect = [complete_download_tasks[i]]
            mock_find_transfer_task.return_value = incomplete_transfer_tasks[i]
            tf_monitor = AsyncMock()
            tf_monitor.wait_finished.side_effect = [complete_transfer_tasks[i]]
            mock_task_monitor.side_effect = [dl_monitor, tf_monitor]
            await download_manager.monitor(task_info_list[i])

        assert mock_post_process.call_count == len(test_resources)


@pytest.mark.asyncio
async def test_monitor_failed(download_manager, test_resources):
    incomplete_download_task = get_incomplete_download_task(test_resources[0])

    task_info = AnimeDownloadTaskInfo(
        resource=test_resources[0],
        download_task=incomplete_download_task,
    )

    with (
        patch(
            "alist_mikananirss.core.download_manager.TaskMonitor"
        ) as mock_task_monitor,
        patch.object(
            download_manager.db, "delete_by_resource_title"
        ) as mock_delete_by_resource_title,
    ):
        dl_monitor = AsyncMock()
        dl_monitor.wait_finished.side_effect = [TimeoutError]
        mock_task_monitor.return_value = dl_monitor
        await download_manager.monitor(task_info)

        assert mock_delete_by_resource_title.call_count == 1
        assert (
            mock_delete_by_resource_title.call_args[0][0]
            == test_resources[0].resource_title
        )


@pytest.mark.asyncio
async def test_find_transfer_task_success(download_manager, test_resources):
    download_tasks = []
    transfer_tasks = []

    for resource in test_resources:
        download_tasks.append(
            get_complete_download_task(get_incomplete_download_task(resource))
        )
        transfer_tasks.append(get_incomplete_transfer_task(resource))

    mock_task_list = AlistTaskList(transfer_tasks)
    download_manager.alist_client.get_task_list.return_value = mock_task_list

    for i, dl_task in enumerate(download_tasks):
        find_res = await download_manager._find_transfer_task(dl_task)
        assert find_res == transfer_tasks[i]
        assert transfer_tasks[i].uuid in download_manager.uuid_set


@pytest.mark.asyncio
async def test_find_transfer_task_not_found(download_manager, test_resources):
    download_task = get_complete_download_task(
        get_incomplete_download_task(test_resources[0])
    )

    download_manager.alist_client.get_task_list.return_value = AlistTaskList([])
    download_manager._find_transfer_task.retry.wait = wait_none()
    result = await download_manager._find_transfer_task(download_task)

    assert result is None


@pytest.mark.asyncio
async def test_find_transfer_task_api_error(download_manager, test_resources):
    download_task = get_complete_download_task(
        get_incomplete_download_task(test_resources[0])
    )

    download_manager.alist_client.get_task_list.side_effect = AlistClientError(
        "Network error"
    )
    download_manager._find_transfer_task.retry.wait = wait_none()
    result = await download_manager._find_transfer_task(download_task)

    assert result is None
