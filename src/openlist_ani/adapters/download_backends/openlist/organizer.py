"""OpenList video and sidecar rename organizer."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from openlist_ani.application.ports import (
    CheckpointCallback,
    DownloadedAsset,
    OrganizedAsset,
)
from openlist_ani.domain import DownloadJob
from openlist_ani.logger import logger

from .client import OpenListClient
from .file_conflicts import OpenListFileConflictResolver


class OpenListOrganizerAdapter:
    def __init__(
        self,
        client: OpenListClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep

    async def organize(
        self,
        job: DownloadJob,
        asset: DownloadedAsset,
        target_filename: str,
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> OrganizedAsset:
        saved_plan = job.artifact.get("organize_plan")
        if saved_plan:
            plan = [dict(item) for item in saved_plan.get("files", [])]
        else:
            plan = await self._build_plan(asset, target_filename)
            if checkpoint_callback is not None:
                await checkpoint_callback({"files": plan})

        if not plan or plan[0].get("kind") != "video":
            raise RuntimeError("Organizer rename plan has no video")

        renamed_any = False
        for item in plan:
            source = item["source"]
            target = item["target"]
            entries = await self._client.list_files(asset.directory_path)
            if entries is None:
                raise RuntimeError(
                    f"Cannot inspect organizer directory: {asset.directory_path}"
                )
            names = {entry.name for entry in entries}
            if source == target and source in names:
                continue
            if source not in names and target in names:
                continue
            if source not in names:
                raise RuntimeError(
                    f"Rename source is missing: {asset.directory_path}/{source}"
                )
            if target in names:
                raise RuntimeError(
                    f"Rename source and target both exist: {source} -> {target}"
                )

            source_path = f"{asset.directory_path.rstrip('/')}/{source}"
            logger.debug(
                f"OpenList rename: job={job.id}, source={source}, target={target}"
            )
            if not await self._client.rename_file(source_path, target):
                refreshed = await self._client.list_files(asset.directory_path)
                refreshed_names = {entry.name for entry in refreshed or []}
                if source not in refreshed_names and target in refreshed_names:
                    continue
                raise RuntimeError(f"Failed to rename '{source}' to '{target}'")
            renamed_any = True

        if renamed_any:
            await self._sleep(5)

        video = plan[0]["target"]
        sidecars = tuple(
            item["target"] for item in plan if item.get("kind") == "subtitle"
        )
        return OrganizedAsset(asset.directory_path, video, sidecars)

    async def _build_plan(
        self,
        asset: DownloadedAsset,
        target_filename: str,
    ) -> list[dict[str, str]]:
        entries = await self._client.list_files(asset.directory_path)
        if entries is None:
            raise RuntimeError(
                f"Cannot inspect organizer directory: {asset.directory_path}"
            )
        names = {entry.name for entry in entries}
        source_names = {asset.filename, *(item.filename for item in asset.sidecars)}
        occupied = names - source_names
        resolver = OpenListFileConflictResolver(self._client, self._sleep)

        if asset.filename not in names and target_filename in names:
            resolved_video = target_filename
        elif asset.filename not in names:
            raise RuntimeError(
                f"Rename source is missing: {asset.directory_path}/{asset.filename}"
            )
        elif target_filename in occupied:
            resolved_video = resolver.next_available_name(target_filename, occupied)
        else:
            resolved_video = target_filename

        plan = [
            {
                "kind": "video",
                "source": asset.filename,
                "target": resolved_video,
            }
        ]
        resolved_stem = os.path.splitext(resolved_video)[0]
        reserved = occupied | {resolved_video}
        for sidecar in asset.sidecars:
            extension = os.path.splitext(sidecar.filename)[1]
            desired = f"{resolved_stem}{sidecar.suffix}{extension}"
            target = (
                resolver.next_available_name(desired, reserved)
                if desired in reserved
                else desired
            )
            reserved.add(target)
            plan.append(
                {
                    "kind": "subtitle",
                    "source": sidecar.filename,
                    "target": target,
                }
            )
        return plan
