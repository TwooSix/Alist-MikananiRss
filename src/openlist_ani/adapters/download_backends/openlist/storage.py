"""OpenList implementation of backend-neutral storage primitives."""

from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Awaitable, Callable

from openlist_ani.application.organization import (
    OrganizationError,
    StorageEntry,
)

from .client import OpenListClient
from .workflow import (
    _directory_creation_paths,
    _join_openlist_path,
    _temp_root_path,
)


class OpenListStorageOperations:
    backend_name = "openlist"

    def __init__(
        self,
        client: OpenListClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        *,
        cache_refresh_seconds: float = 5,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._cache_refresh_seconds = cache_refresh_seconds

    def join(self, root: str, *parts: str) -> str:
        return _join_openlist_path(root, *parts)

    async def list_directory(self, path: str) -> tuple[StorageEntry, ...]:
        entries = await self._client.list_files(path)
        if entries is None:
            raise OrganizationError(f"Cannot inspect OpenList directory: {path}")
        return tuple(
            StorageEntry(
                name=entry.name,
                is_directory=bool(getattr(entry, "is_dir", False)),
                size=(
                    entry.size if isinstance(getattr(entry, "size", None), int) else 0
                ),
            )
            for entry in entries
        )

    async def ensure_directory(self, base_path: str, target_path: str) -> None:
        for directory in _directory_creation_paths(base_path, target_path):
            if not await self._client.mkdir(directory):
                # OpenList may report an error for mkdir on an already existing
                # directory.  Reconcile that response before failing.
                parent, name = posixpath.split(directory.rstrip("/"))
                parent = parent or "/"
                entries = await self._client.list_files(parent)
                if entries is not None and any(
                    entry.name == name and bool(entry.is_dir) for entry in entries
                ):
                    continue
                raise OrganizationError(f"Failed to create directory: {directory}")

    async def rename(self, full_path: str, new_name: str) -> None:
        if await self._client.rename_file(full_path, new_name):
            await self._refresh_wait()
            return

        parent, old_name = posixpath.split(full_path.rstrip("/"))
        entries = await self._client.list_files(parent or "/")
        names = {entry.name for entry in entries or ()}
        if old_name not in names and new_name in names:
            return
        raise OrganizationError(f"Failed to rename '{old_name}' to '{new_name}'")

    async def move(
        self,
        source_directory: str,
        target_directory: str,
        filenames: tuple[str, ...],
    ) -> None:
        if not filenames:
            return
        if await self._client.move_file(
            source_directory,
            target_directory,
            list(filenames),
        ):
            await self._refresh_wait()
            return

        source = await self._client.list_files(source_directory)
        target = await self._client.list_files(target_directory)
        source_names = {entry.name for entry in source or ()}
        target_names = {entry.name for entry in target or ()}
        if all(name not in source_names and name in target_names for name in filenames):
            return
        raise OrganizationError(
            f"Failed to move files from {source_directory} to {target_directory}"
        )

    async def remove_files(
        self,
        directory: str,
        filenames: tuple[str, ...],
    ) -> None:
        if not filenames:
            return
        if any(not name or "/" in name or "\\" in name for name in filenames):
            raise OrganizationError("Refusing to remove an unsafe OpenList filename")
        before = await self._client.list_files(directory)
        if before is None:
            raise OrganizationError(f"Cannot inspect delete directory: {directory}")
        names_before = {entry.name for entry in before}
        present = tuple(name for name in filenames if name in names_before)
        if not present:
            return
        if await self._client.remove_path(directory, list(present)):
            await self._refresh_wait()
        after = await self._client.list_files(directory)
        if after is None:
            raise OrganizationError(f"Cannot verify deleted files in: {directory}")
        remaining = {entry.name for entry in after}
        unresolved = [name for name in present if name in remaining]
        if unresolved:
            raise OrganizationError(
                f"Failed to remove files from {directory}: {', '.join(unresolved)}"
            )

    async def remove_staging_tree(
        self,
        path: str,
        *,
        job_id: str,
        base_path: str,
    ) -> None:
        normalized = "/" + path.replace("\\", "/").strip("/")
        expected = _join_openlist_path(_temp_root_path(base_path), job_id)
        parent, name = posixpath.split(normalized)
        if not job_id or normalized != expected:
            raise OrganizationError(
                f"Refusing to remove unsafe OpenList staging path: {path}"
            )
        removed = await self._client.remove_path(parent, [name])
        if removed:
            await self._refresh_wait()
        # API success is not enough: OpenList views can lag behind mutations.
        # Only checkpoint cleanup after the exact job directory is absent.
        entries = await self._client.list_files(parent)
        if entries is None or any(entry.name == name for entry in entries):
            raise OrganizationError(f"Failed to remove staging path: {path}")

    async def _refresh_wait(self) -> None:
        if self._cache_refresh_seconds > 0:
            await self._sleep(self._cache_refresh_seconds)
