"""OpenList move/rename organizer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from openlist_ani.application.ports import DownloadedAsset, OrganizedAsset
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
    ) -> OrganizedAsset:
        if target_filename == asset.filename:
            return OrganizedAsset(asset.directory_path, asset.filename)

        files = await self._client.list_files(asset.directory_path)
        if files is not None:
            names = {item.name for item in files}
            if asset.filename not in names and target_filename in names:
                return OrganizedAsset(asset.directory_path, target_filename)
            if asset.filename not in names:
                raise RuntimeError(
                    f"Rename source is missing: {asset.directory_path}/{asset.filename}"
                )

        resolver = OpenListFileConflictResolver(self._client, self._sleep)
        resolved_filename = await resolver.resolve_before_rename(
            asset.directory_path,
            asset.filename,
            target_filename,
        )
        source_path = f"{asset.directory_path.rstrip('/')}/{asset.filename}"
        logger.debug(
            f"OpenList rename: job={job.id}, source={asset.filename}, "
            f"target={resolved_filename}"
        )
        if not await self._client.rename_file(source_path, resolved_filename):
            refreshed = await self._client.list_files(asset.directory_path)
            refreshed_names = {item.name for item in refreshed or []}
            if (
                asset.filename not in refreshed_names
                and resolved_filename in refreshed_names
            ):
                return OrganizedAsset(asset.directory_path, resolved_filename)
            raise RuntimeError(
                f"Failed to rename '{asset.filename}' to '{resolved_filename}'"
            )
        await self._sleep(5)
        return OrganizedAsset(asset.directory_path, resolved_filename)
