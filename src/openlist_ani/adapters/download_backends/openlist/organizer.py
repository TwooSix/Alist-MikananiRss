"""OpenList composition root for the shared durable organizer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from openlist_ani.application.organization import DurableOrganizationExecutor
from openlist_ani.application.ports import (
    CheckpointCallback,
    DownloadedAsset,
    DownloadManifest,
    DownloadedFile,
    OrganizedAsset,
    OrganizationRequest,
    OrganizationSidecar,
)
from openlist_ani.domain import DownloadJob

from .client import OpenListClient
from .storage import OpenListStorageOperations


class OpenListOrganizerAdapter:
    backend_name = "openlist"

    def __init__(
        self,
        client: OpenListClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._storage = OpenListStorageOperations(client, sleep)
        self._executor = DurableOrganizationExecutor(self._storage)

    async def organize(
        self,
        job: DownloadJob,
        manifest: DownloadManifest | DownloadedAsset,
        requests: tuple[OrganizationRequest, ...] | str,
        checkpoint_callback: CheckpointCallback | None = None,
    ):
        """Organize all requests using the OpenList storage driver.

        The ``DownloadedAsset``/string branch only exists so persisted v1 jobs
        and integrations can finish after an upgrade.  New jobs always use a
        manifest plus a tuple of requests.
        """

        if isinstance(manifest, DownloadedAsset):
            if not isinstance(requests, str):
                raise TypeError("legacy organizer target filename must be a string")
            legacy_asset = manifest
            converted_manifest = DownloadManifest(
                root_path=legacy_asset.directory_path,
                files=(
                    DownloadedFile(legacy_asset.filename),
                    *(
                        DownloadedFile(sidecar.filename)
                        for sidecar in legacy_asset.sidecars
                    ),
                ),
                checkpoint=dict(legacy_asset.checkpoint),
                legacy_materialized=True,
            )
            converted_request = OrganizationRequest(
                item_key="legacy",
                video_relative_path=legacy_asset.filename,
                sidecars=tuple(
                    OrganizationSidecar(sidecar.filename, sidecar.suffix)
                    for sidecar in legacy_asset.sidecars
                ),
                target_directory_path=legacy_asset.directory_path,
                target_filename=requests,
                metadata=job.metadata,
            )
            results = await self._executor.organize(
                job,
                converted_manifest,
                (converted_request,),
                checkpoint_callback,
            )
            result = results[0]
            if result.state != "completed" or not result.final_path:
                raise RuntimeError(result.error or "Legacy organization failed")
            directory_path, filename = result.final_path.rsplit("/", 1)
            return OrganizedAsset(
                directory_path,
                filename,
                tuple(path.rsplit("/", 1)[-1] for path in result.sidecar_paths),
            )

        if isinstance(requests, str):
            raise TypeError("organization requests must be a tuple")
        return await self._executor.organize(
            job,
            manifest,
            requests,
            checkpoint_callback,
        )
