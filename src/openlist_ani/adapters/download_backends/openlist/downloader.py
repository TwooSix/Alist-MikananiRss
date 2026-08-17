"""OpenList durable download adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from openlist_ani.application.ports import (
    CheckpointCallback,
    DownloadedFile,
    DownloadManifest,
    DownloadedSidecar,
)
from openlist_ani.domain import DownloadJob
from openlist_ani.domain.naming import ReleaseDirectoryPlanner

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


@dataclass(frozen=True)
class _LegacyCompatibleManifest(DownloadManifest):
    """Manifest with the read-only attributes exposed by the v1 adapter."""

    @property
    def directory_path(self) -> str:
        return self.root_path

    @property
    def filename(self) -> str:
        return self.files[0].relative_path

    @property
    def sidecars(self) -> tuple[DownloadedSidecar, ...]:
        raw = self.checkpoint.get("materialized_sidecars", [])
        return tuple(
            DownloadedSidecar(
                filename=str(item["filename"]),
                suffix=str(item.get("suffix") or ""),
            )
            for item in raw
        )


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
        checkpoint_callback: CheckpointCallback | str,
        legacy_checkpoint_callback: CheckpointCallback | None = None,
    ) -> DownloadManifest:
        """Download into OpenList staging and return a durable file manifest.

        ``legacy_checkpoint_callback`` keeps source compatibility with v1
        callers that supplied ``(job, target_directory, callback)``.  Persisted
        v1 jobs also use the original move/materialize workflow and are wrapped
        in a single-asset manifest for the new worker.
        """

        legacy_target_override: str | None = None
        if isinstance(checkpoint_callback, str):
            legacy_target_override = checkpoint_callback
            if legacy_checkpoint_callback is None:
                raise TypeError("checkpoint callback is required")
            callback = legacy_checkpoint_callback
            use_manifest_v2 = False
        else:
            callback = checkpoint_callback
            use_manifest_v2 = job.checkpoint_version >= 2

        metadata = job.metadata.values
        base_path = str(job.artifact.get("base_path", ""))
        target_directory_path = legacy_target_override or (
            ReleaseDirectoryPlanner().target_directory_path(base_path, metadata)
            if not use_manifest_v2
            else ""
        )
        task = OpenListWorkflowContext(
            id=job.id,
            title=job.candidate.title,
            download_url=job.candidate.download_url,
            anime_name=metadata.anime_name,
            season=metadata.season,
            episode=metadata.episode,
            base_path=base_path,
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
            await callback(dict(value.downloader_data))

        if use_manifest_v2:
            await workflow.run_to_manifest(task, checkpoint=checkpoint)
            temp_path = str(task.downloader_data.get("temp_path") or "")
            if not temp_path:
                raise RuntimeError("OpenList manifest has no staging root")
            return DownloadManifest(
                root_path=temp_path,
                files=tuple(
                    DownloadedFile(
                        relative_path=str(item["relative_path"]),
                        size=int(item.get("size") or 0),
                    )
                    for item in task.downloader_data.get("downloaded_files", [])
                ),
                checkpoint=dict(task.downloader_data),
                cleanup_root=temp_path,
            )

        await workflow.run(task, checkpoint=checkpoint)
        directory_path = task.downloader_data["materialized_directory_path"]
        filename = task.downloader_data["materialized_filename"]
        sidecars = task.downloader_data.get("materialized_sidecars", [])
        return _LegacyCompatibleManifest(
            root_path=directory_path,
            files=(
                DownloadedFile(relative_path=filename),
                *(
                    DownloadedFile(relative_path=str(item["filename"]))
                    for item in sidecars
                ),
            ),
            checkpoint=dict(task.downloader_data),
            cleanup_root=None,
            legacy_materialized=True,
        )
