from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from alist_mikananirss.alist import Alist
from alist_mikananirss.alist.tasks import (
    AlistDownloadTask,
    AlistTaskCollection,
    AlistTaskStatus,
    AlistTransferTask,
)
from alist_mikananirss.common.database import SubscribeDatabase
from alist_mikananirss.core import DownloadManager
from alist_mikananirss.core.download_manager import AnimeDownloadTaskInfo, TaskMonitor
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture
def test_rousources():
    resources = [
        ResourceInfo(
            resource_title="title1",
            torrent_url="https://test1.torrent",
            published_date="1",
            anime_name="Test Anime",
            season=1,
            episode=5,
            fansub="TestSub",
            quality="1080p",
            language="JP",
        ),
        ResourceInfo(
            resource_title="title2",
            torrent_url="https://test2.torrent",
            published_date="1",
            anime_name="Test Anime2",
            season=1,
            episode=5,
            fansub="TestSub",
            quality="1080p",
            language="JP",
        ),
    ]
    return resources


@pytest.fixture
def download_manager():
    mock_alist = AsyncMock(spec=Alist)
    mock_db = AsyncMock(spec=SubscribeDatabase)
    DownloadManager.initialize(
        mock_alist, "/base/path", use_renamer=True, need_notification=True, db=mock_db
    )
    return DownloadManager()


@pytest.mark.asyncio
async def test_download(download_manager, test_rousources):
    download_manager.alist_client.add_offline_download_task.side_effect = [
        AlistTaskCollection(
            [
                AlistDownloadTask(
                    tid=1,
                    description="Download task 1",
                    status="success",
                    progress=100,
                    error_msg=None,
                    url=test_rousources[0].torrent_url,
                ),
            ]
        ),
        TimeoutError,
    ]
    with patch.object(logger, "error") as logger_error_mock:
        success_task_info = await download_manager.download(test_rousources)
        logger_error_mock.assert_called_once()
        assert len(success_task_info) == 1
        assert success_task_info[0].resource == test_rousources[0]


@pytest.mark.asyncio
async def test_monitor_success(download_manager):
    test_task = AnimeDownloadTaskInfo(
        resource=ResourceInfo(
            resource_title="title",
            torrent_url="https://test1.torrent",
            published_date="1",
            anime_name="Test Anime",
            season=1,
            episode=5,
            fansub="TestSub",
            quality="1080p",
            language="JP",
        ),
        download_path="test/path",
        download_task=MagicMock(),
    )

    with (
        patch.object(download_manager, "_wait_finished") as wait_finished_mock,
        patch.object(download_manager, "_post_process") as post_process_mock,
    ):
        wait_finished_mock.return_value = MagicMock()
        await download_manager.monitor(test_task)
        wait_finished_mock.assert_awaited_once_with(test_task)
        post_process_mock.assert_called_once()
        assert download_manager.db.delete_by_resource_title.call_count == 0


@pytest.mark.asyncio
async def test_monitor_failed(download_manager):
    test_task = AnimeDownloadTaskInfo(
        resource=ResourceInfo(
            resource_title="title",
            torrent_url="https://test1.torrent",
            published_date="1",
            anime_name="Test Anime",
            season=1,
            episode=5,
            fansub="TestSub",
            quality="1080p",
            language="JP",
        ),
        download_path="test/path",
        download_task=MagicMock(),
    )

    with (
        patch.object(download_manager, "_wait_finished") as wait_finished_mock,
        patch.object(download_manager, "_post_process") as post_process_mock,
    ):
        wait_finished_mock.return_value = None
        await download_manager.monitor(test_task)
        wait_finished_mock.assert_awaited_once_with(test_task)
        assert post_process_mock.call_count == 0
        download_manager.db.delete_by_resource_title.assert_called_once_with(
            test_task.resource.resource_title
        )


@pytest.mark.asyncio
async def test_add_download_task(download_manager, test_rousources):
    download_tasks_info = [
        AnimeDownloadTaskInfo(
            resource=test_rousources[0],
            download_path="test/path",
            download_task=MagicMock(),
        ),
        AnimeDownloadTaskInfo(
            resource=test_rousources[1],
            download_path="test/path",
            download_task=MagicMock(),
        ),
    ]

    with patch.object(download_manager, "download") as download_mock:
        with patch.object(download_manager, "monitor") as monitor_mock:
            download_mock.return_value = download_tasks_info
            await DownloadManager.add_download_tasks(test_rousources)
            download_mock.assert_called_once()
            assert download_manager.db.insert_resource_info.call_count == 2
            assert monitor_mock.call_count == 2


@pytest.mark.asyncio
async def test_find_transfer_task(download_manager):
    resource = ResourceInfo(
        anime_name="Test Anime",
        resource_title="Episode 1",
        torrent_url="https://example.com/test.torrent",
    )
    transfer_task = AlistTransferTask(
        tid="123",
        description="transfer Test Anime/file.mp4 to [/path]",
        status=AlistTaskStatus.Running,
        progress=50,
        uuid="123",
        file_name="file.mp4",
    )

    download_manager.alist_client.get_task_list.return_value = [transfer_task]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await download_manager._find_transfer_task(resource)

    assert result == transfer_task
    assert transfer_task.uuid in download_manager.uuid_set


@pytest.mark.asyncio
async def test_wait_finished_success(download_manager):
    resource = ResourceInfo(
        anime_name="Test Anime",
        resource_title="Episode 1",
        torrent_url="https://example.com/test.torrent",
    )
    download_task = AlistDownloadTask(
        tid="123",
        description="download https://example.com/test.torrent to",
        status=AlistTaskStatus.Running,
        progress=0.5,
        url="https://example.com/test.torrent",
    )
    transfer_task = AlistTransferTask(
        tid="456",
        description="transfer Test Anime/file.mp4 to [/path]",
        status=AlistTaskStatus.Running,
        progress=0.5,
        uuid="uuid",
        file_name="file.mp4",
    )

    task_info = AnimeDownloadTaskInfo(
        resource=resource,
        download_path="/base/path/Test Anime",
        download_task=download_task,
    )

    with (
        patch(
            "alist_mikananirss.core.download_manager.TaskMonitor"
        ) as mock_task_monitor,
        patch.object(
            download_manager,
            "_find_transfer_task",
            AsyncMock(return_value=transfer_task),
        ),
    ):
        mock_download_task_monitor = AsyncMock(spec=TaskMonitor)
        mock_download_task_monitor.wait_finished.return_value = AlistDownloadTask(
            tid="123",
            description="",
            status=AlistTaskStatus.Succeeded,
            progress=1.0,
            url="https://example.com/test.torrent",
        )
        mock_transfer_task_monitor = MagicMock(spec=TaskMonitor)
        mock_transfer_task_monitor.wait_finished.return_value = AlistTransferTask(
            tid="456",
            description="",
            status=AlistTaskStatus.Succeeded,
            progress=1.0,
            uuid="uuid",
            file_name="file.mp4",
        )
        mock_task_monitor.side_effect = [
            mock_download_task_monitor,
            mock_transfer_task_monitor,
        ]
        result = await download_manager._wait_finished(task_info)
        assert result is not None
        assert result.transfer_task.tid == transfer_task.tid
