import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openlist_ani.adapters.download_backends.openlist import (
    DownloadBackendError,
    OpenListDownloadAdapter,
    OpenlistTask,
    OpenlistTaskState,
)
from openlist_ani.domain import (
    DownloadJob,
    LanguageType,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)


def _adapter():
    client = AsyncMock()
    client.mkdir = AsyncMock(return_value=True)
    client.rename_file = AsyncMock(return_value=True)
    client.move_file = AsyncMock(return_value=True)
    client.remove_path = AsyncMock(return_value=True)
    adapter = OpenListDownloadAdapter(
        client=client,
        offline_download_tool="aria2",
        sleep=AsyncMock(),
    )
    return adapter, client


def _job(*, checkpoint=None, job_id="workflow-1") -> DownloadJob:
    candidate = ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="[ANi] Example - 01 [1080P][CHT]",
        download_url="magnet:?xt=urn:btih:abc123",
    )
    return DownloadJob(
        id=job_id,
        candidate=candidate,
        metadata=MetadataDocument(
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                fansub="ANi",
                quality=VideoQuality.Q1080P,
                languages=[LanguageType.CHT],
            )
        ),
        checkpoint=dict(checkpoint or {}),
        artifact={"base_path": "/anime"},
    )


async def _run(adapter, job, checkpoints=None):
    async def checkpoint(payload):
        job.checkpoint = dict(payload)
        if checkpoints is not None:
            checkpoints.append(dict(payload))
        await asyncio.sleep(0)

    return await adapter.start_or_resume(
        job,
        "/anime/Example/Season 1",
        checkpoint,
    )


def _successful_remote(client, filename="raw episode [1080p].mkv"):
    client.add_offline_download = AsyncMock(
        return_value=[OpenlistTask(id="offline-1", name="offline")]
    )
    client.get_offline_download_undone = AsyncMock(return_value=[])
    client.get_offline_download_done = AsyncMock(
        return_value=[
            OpenlistTask(
                id="offline-1",
                name="offline",
                state=OpenlistTaskState.SUCCEEDED,
            )
        ]
    )
    client.get_offline_download_transfer_undone = AsyncMock(return_value=[])
    client.get_offline_download_transfer_done = AsyncMock(return_value=[])
    client.list_files = AsyncMock(
        side_effect=[
            [SimpleNamespace(name=filename, is_dir=False, size=100)],
            [],
            [SimpleNamespace(name=filename, is_dir=False, size=100)],
            [],
            [SimpleNamespace(name=filename, is_dir=False, size=100)],
            [],
            [],
            [SimpleNamespace(name=filename, is_dir=False, size=100)],
        ]
    )


async def test_download_moves_detected_file_and_persists_checkpoints():
    adapter, client = _adapter()
    _successful_remote(client)
    checkpoints = []

    result = await _run(adapter, _job(), checkpoints)

    assert result.directory_path == "/anime/Example/Season 1"
    assert result.filename == "raw episode [1080p].mkv"
    assert result.checkpoint["task_id"] == "offline-1"
    assert result.checkpoint["workflow_state"] == "done"
    assert any(item["workflow_state"] == "submitted" for item in checkpoints)
    client.add_offline_download.assert_awaited_once_with(
        urls=["magnet:?xt=urn:btih:abc123"],
        path="/anime/.oani-download-tmp/workflow-1",
        tool="aria2",
    )
    client.mkdir.assert_any_await("/anime/Example")
    client.mkdir.assert_any_await("/anime/Example/Season 1")
    client.move_file.assert_awaited_once_with(
        "/anime/.oani-download-tmp/workflow-1",
        "/anime/Example/Season 1",
        ["raw episode [1080p].mkv"],
    )
    client.remove_path.assert_awaited_once_with(
        "/anime/.oani-download-tmp", ["workflow-1"]
    )


async def test_download_moves_related_subtitles_with_video():
    adapter, client = _adapter()
    files = [
        SimpleNamespace(name="raw.mkv", is_dir=False, size=1000),
        SimpleNamespace(name="raw.zh.ass", is_dir=False, size=10),
        SimpleNamespace(name="unrelated.ass", is_dir=False, size=10),
    ]
    moved_files = [files[0], files[1]]
    client.add_offline_download = AsyncMock(
        return_value=[OpenlistTask(id="offline-1", name="offline")]
    )
    client.get_offline_download_undone = AsyncMock(return_value=[])
    client.get_offline_download_done = AsyncMock(
        return_value=[
            OpenlistTask(
                id="offline-1",
                name="offline",
                state=OpenlistTaskState.SUCCEEDED,
            )
        ]
    )
    client.get_offline_download_transfer_undone = AsyncMock(return_value=[])
    client.get_offline_download_transfer_done = AsyncMock(return_value=[])
    client.list_files = AsyncMock(
        side_effect=[
            files,
            files,
            files,
            [],
            files,
            [],
            [files[2]],
            moved_files,
        ]
    )

    result = await _run(adapter, _job())

    assert [(item.filename, item.suffix) for item in result.sidecars] == [
        ("raw.zh.ass", ".zh")
    ]
    client.move_file.assert_awaited_once_with(
        "/anime/.oani-download-tmp/workflow-1",
        "/anime/Example/Season 1",
        ["raw.mkv", "raw.zh.ass"],
    )


async def test_download_resumes_existing_task_without_resubmitting():
    adapter, client = _adapter()
    _successful_remote(client, "ep01.mkv")
    job = _job(
        checkpoint={
            "workflow_state": "submitted",
            "task_id": "offline-1",
            "temp_path": "/anime/.oani-download-tmp/workflow-1",
        }
    )

    result = await _run(adapter, job)

    assert result.filename == "ep01.mkv"
    client.add_offline_download.assert_not_awaited()
    client.move_file.assert_awaited_once()


async def test_download_recovers_uncertain_remote_submission():
    adapter, client = _adapter()
    client.get_offline_download_undone = AsyncMock(
        return_value=[
            OpenlistTask(
                id="existing-task",
                name="workflow-1 remote task",
                state=OpenlistTaskState.RUNNING,
            )
        ]
    )
    client.get_offline_download_done = AsyncMock(return_value=[])
    checkpoints = []
    job = _job(
        checkpoint={
            "workflow_state": "submitting",
            "temp_path": "/anime/.oani-download-tmp/workflow-1",
        }
    )

    async def crash_after_reconciliation(payload):
        checkpoints.append(dict(payload))
        if payload.get("task_id") == "existing-task":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        await adapter.start_or_resume(
            job,
            "/anime/Example/Season 1",
            crash_after_reconciliation,
        )

    client.add_offline_download.assert_not_awaited()
    assert any(item.get("task_id") == "existing-task" for item in checkpoints)


async def test_download_recovers_move_completed_before_checkpoint():
    adapter, client = _adapter()
    client.list_files = AsyncMock(
        side_effect=[
            [],
            [SimpleNamespace(name="ep01.mkv", is_dir=False, size=100)],
        ]
    )
    job = _job(
        checkpoint={
            "workflow_state": "moving",
            "temp_path": "/anime/.oani-download-tmp/workflow-1",
            "file_parent_path": "/anime/.oani-download-tmp/workflow-1",
            "resolved_filename": "ep01.mkv",
        }
    )

    result = await _run(adapter, job)

    assert result.filename == "ep01.mkv"
    client.move_file.assert_not_awaited()
    assert result.checkpoint["workflow_state"] == "done"


async def test_download_resumes_persisted_conflict_plan_after_partial_rename():
    adapter, client = _adapter()
    resolved_video = "raw (1).mkv"
    resolved_subtitle = "raw.zh (1).ass"
    client.list_files = AsyncMock(
        side_effect=[
            [
                SimpleNamespace(name=resolved_video, is_dir=False, size=100),
                SimpleNamespace(name="raw.zh.ass", is_dir=False, size=10),
            ],
            [
                SimpleNamespace(name=resolved_video, is_dir=False, size=100),
                SimpleNamespace(name="raw.zh.ass", is_dir=False, size=10),
            ],
            [
                SimpleNamespace(name=resolved_video, is_dir=False, size=100),
                SimpleNamespace(name=resolved_subtitle, is_dir=False, size=10),
            ],
            [],
            [],
            [
                SimpleNamespace(name=resolved_video, is_dir=False, size=100),
                SimpleNamespace(name=resolved_subtitle, is_dir=False, size=10),
            ],
        ]
    )
    job = _job(
        checkpoint={
            "workflow_state": "file_detected",
            "temp_path": "/anime/.oani-download-tmp/workflow-1",
            "downloaded_filename": "raw.mkv",
            "downloaded_sidecars": [{"relative_path": "raw.zh.ass", "suffix": ".zh"}],
            "file_parent_path": "/anime/.oani-download-tmp/workflow-1",
            "resolved_filename": resolved_video,
            "move_plan": [
                {
                    "kind": "video",
                    "source": "raw.mkv",
                    "filename": resolved_video,
                },
                {
                    "kind": "subtitle",
                    "source": "raw.zh.ass",
                    "filename": resolved_subtitle,
                    "suffix": ".zh",
                },
            ],
        }
    )

    result = await _run(adapter, job)

    assert result.filename == resolved_video
    assert result.sidecars[0].filename == resolved_subtitle
    client.rename_file.assert_awaited_once_with(
        "/anime/.oani-download-tmp/workflow-1/raw.zh.ass",
        resolved_subtitle,
    )


async def test_failed_remote_task_is_retryable_and_checkpoint_is_reset():
    adapter, client = _adapter()
    client.get_offline_download_undone = AsyncMock(return_value=[])
    client.get_offline_download_done = AsyncMock(
        return_value=[
            OpenlistTask(
                id="offline-1",
                name="offline",
                state=OpenlistTaskState.FAILED,
                error="qbit failed",
            )
        ]
    )
    checkpoints = []
    job = _job(
        checkpoint={
            "workflow_state": "submitted",
            "task_id": "offline-1",
            "temp_path": "/anime/.oani-download-tmp/workflow-1",
        }
    )

    with pytest.raises(DownloadBackendError, match="qbit failed"):
        await _run(adapter, job, checkpoints)

    assert checkpoints[-1]["workflow_state"] == "init"
    assert "task_id" not in checkpoints[-1]
    client.remove_path.assert_awaited_once()
