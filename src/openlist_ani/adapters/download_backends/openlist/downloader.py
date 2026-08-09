"""OpenList durable download adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from openlist_ani.application.ports import DownloadedAsset, DownloadedSidecar
from openlist_ani.domain import DownloadJob

from .client import OpenListClient
from .file_conflicts import OpenListFileConflictResolver
from .file_detection import OpenListFileDetector
from .models import (
    OfflineDownloadTool,
    OpenListWorkflowContext,
    normalize_offline_download_tool_name,
)
from .task_snapshot_cache import OpenListTaskSnapshotCache
from .workflow import OpenListDownloadWorkflow


class OpenListDownloadAdapter:
    name = "openlist"

    def __init__(
        self,
        client: OpenListClient,
        offline_download_tool: OfflineDownloadTool | str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if client is None:
            raise ValueError("client is required")
        if offline_download_tool is None:
            raise ValueError("offline_download_tool is required")
        self._client = client
        self._offline_download_tool = normalize_offline_download_tool_name(
            offline_download_tool
        )
        self._sleep = sleep
        self._task_snapshot_cache = OpenListTaskSnapshotCache(client)

    async def start_or_resume(
        self,
        job: DownloadJob,
        target_directory_path: str,
        checkpoint_callback,
    ) -> DownloadedAsset:
        metadata = job.metadata.values
        task = OpenListWorkflowContext(
            id=job.id,
            title=job.candidate.title,
            download_url=job.candidate.download_url,
            anime_name=metadata.anime_name,
            season=metadata.season,
            episode=metadata.episode,
            base_path=str(job.artifact.get("base_path", "")),
            target_directory_path=target_directory_path,
            downloader_data=dict(job.checkpoint),
        )
        workflow = OpenListDownloadWorkflow(
            client=self._client,
            offline_download_tool=self._offline_download_tool,
            file_detector=OpenListFileDetector(self._client, self._sleep),
            conflict_resolver=OpenListFileConflictResolver(self._client, self._sleep),
            sleep=self._sleep,
            task_snapshot_cache=self._task_snapshot_cache,
        )

        async def checkpoint(value: OpenListWorkflowContext) -> None:
            await checkpoint_callback(dict(value.downloader_data))

        await workflow.run(task, checkpoint=checkpoint)
        return DownloadedAsset(
            directory_path=task.downloader_data["materialized_directory_path"],
            filename=task.downloader_data["materialized_filename"],
            sidecars=tuple(
                DownloadedSidecar(
                    filename=item["filename"],
                    suffix=item.get("suffix", ""),
                )
                for item in task.downloader_data.get("materialized_sidecars", [])
            ),
            checkpoint=dict(task.downloader_data),
        )
