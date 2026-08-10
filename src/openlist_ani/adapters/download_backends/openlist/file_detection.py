"""Downloaded file detection for OpenList temporary directories."""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .client import OpenListClient
from openlist_ani.logger import logger

_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".mpg",
    ".mpeg",
}

_SUBTITLE_EXTENSIONS = {".ass", ".ssa", ".srt", ".vtt", ".sub", ".idx", ".sup"}
_SUBTITLE_SUFFIX_BOUNDARIES = frozenset("._- [(")


@dataclass(frozen=True)
class DetectedSidecar:
    relative_path: str
    suffix: str


@dataclass(frozen=True)
class DetectedFiles:
    video_relative_path: str
    sidecars: tuple[DetectedSidecar, ...] = ()


@dataclass(frozen=True)
class InventoryFile:
    relative_path: str
    size: int = 0


class _IncompleteInventorySnapshot(RuntimeError):
    """Raised when any directory in a recursive inventory cannot be listed."""


def _is_video_file(name: str) -> bool:
    _, ext = os.path.splitext(name)
    return ext.lower() in _VIDEO_EXTENSIONS


class OpenListFileDetector:
    """Find the most likely downloaded video in an OpenList directory."""

    def __init__(
        self,
        client: OpenListClient,
        sleep: Callable[[float], Awaitable[None]],
        timeout_seconds: float = 30,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds

    async def detect(
        self,
        temp_path: str,
    ) -> DetectedFiles | None:
        start_time = time.monotonic()
        logger.debug(f"Detecting downloaded file in {temp_path}")

        while True:
            candidates = await self._collect_video_files(temp_path, "")
            if candidates:
                candidates.sort(key=lambda item: item[1], reverse=True)
                selected = candidates[0][0]
                logger.debug(
                    f"Detected downloaded file in {temp_path}: "
                    f"{selected} ({len(candidates)} video candidate(s))"
                )
                sidecars = await self._detect_sidecars(temp_path, selected)
                return DetectedFiles(selected, tuple(sidecars))

            if time.monotonic() - start_time >= self._timeout_seconds:
                logger.debug(f"Downloaded file detection timed out in {temp_path}")
                return None

            await self._sleep(10)

    async def inventory(self, temp_path: str) -> tuple[InventoryFile, ...]:
        """Recursively inventory every leaf file below ``temp_path``.

        Transfer completion can become visible before the destination listing is
        refreshed.  A snapshot is therefore accepted only after three consecutive,
        complete recursive scans agree.  If any nested listing fails, the whole
        scan is discarded so a partial manifest can never drive staging cleanup.
        """

        start_time = time.monotonic()
        previous_snapshot: tuple[InventoryFile, ...] | None = None
        stable_scans = 0
        logger.debug(f"Inventorying downloaded files in {temp_path}")
        while True:
            try:
                collected = await self._collect_leaf_files(temp_path, "")
            except _IncompleteInventorySnapshot as exc:
                previous_snapshot = None
                stable_scans = 0
                logger.debug(f"Discarding incomplete inventory for {temp_path}: {exc}")
            else:
                collected.sort(key=lambda item: item.relative_path.casefold())
                snapshot = tuple(collected)
                if snapshot and snapshot == previous_snapshot:
                    stable_scans += 1
                elif snapshot:
                    stable_scans = 1
                else:
                    stable_scans = 0
                if stable_scans >= 3:
                    logger.debug(
                        f"Inventoried {len(snapshot)} stable downloaded file(s) "
                        f"in {temp_path}"
                    )
                    return snapshot
                previous_snapshot = snapshot if snapshot else None

            if time.monotonic() - start_time >= self._timeout_seconds:
                logger.warning(
                    f"Complete stable file inventory timed out in {temp_path}"
                )
                return ()
            await self._sleep(10)

    async def _collect_leaf_files(
        self,
        current_path: str,
        relative_prefix: str,
    ) -> list[InventoryFile]:
        try:
            entries = await self._client.list_files(current_path)
        except Exception as exc:
            raise _IncompleteInventorySnapshot(
                f"listing raised for {current_path}: {exc}"
            ) from exc
        if entries is None:
            raise _IncompleteInventorySnapshot(f"listing failed for {current_path}")
        if not entries:
            return []

        collected: list[InventoryFile] = []
        for entry in entries:
            name = str(entry.name or "").replace("\\", "/").strip("/")
            if not name or name in {".", ".."} or "/" in name:
                logger.warning(f"Ignoring unsafe OpenList entry name: {entry.name!r}")
                continue
            relative_name = f"{relative_prefix}/{name}" if relative_prefix else name
            if entry.is_dir:
                collected.extend(
                    await self._collect_leaf_files(
                        f"{current_path.rstrip('/')}/{name}",
                        relative_name,
                    )
                )
                continue
            size = entry.size if isinstance(entry.size, int) else 0
            collected.append(InventoryFile(relative_name, size))
        return collected

    async def _detect_sidecars(
        self,
        temp_path: str,
        video_relative_path: str,
    ) -> list[DetectedSidecar]:
        parent, video_name = os.path.split(video_relative_path)
        directory_path = f"{temp_path.rstrip('/')}/{parent}" if parent else temp_path
        entries = await self._client.list_files(directory_path)
        if not entries:
            return []

        video_stem = os.path.splitext(video_name)[0]
        matched: list[DetectedSidecar] = []
        for entry in entries:
            if entry.is_dir:
                continue
            subtitle_stem, extension = os.path.splitext(entry.name)
            if extension.lower() not in _SUBTITLE_EXTENSIONS:
                continue
            suffix = _subtitle_suffix(video_stem, subtitle_stem)
            if suffix is None:
                continue
            relative_path = f"{parent}/{entry.name}" if parent else entry.name
            matched.append(DetectedSidecar(relative_path, suffix))
        return sorted(matched, key=lambda item: item.relative_path.casefold())

    async def _collect_video_files(
        self,
        current_path: str,
        relative_prefix: str,
    ) -> list[tuple[str, int]]:
        files = await self._client.list_files(current_path)
        if not files:
            logger.debug(f"No files found while scanning {current_path}")
            return []

        candidates: list[tuple[str, int]] = []
        for file_info in files:
            name = file_info.name
            relative_name = f"{relative_prefix}/{name}" if relative_prefix else name

            if file_info.is_dir:
                next_path = f"{current_path.rstrip('/')}/{name}"
                candidates.extend(
                    await self._collect_video_files(next_path, relative_name)
                )
                continue

            if _is_video_file(name):
                size = file_info.size if isinstance(file_info.size, int) else 0
                candidates.append((relative_name, size))

        return candidates


def _subtitle_suffix(video_stem: str, subtitle_stem: str) -> str | None:
    folded_video = video_stem.casefold()
    folded_subtitle = subtitle_stem.casefold()
    if folded_subtitle == folded_video:
        return ""
    if not folded_subtitle.startswith(folded_video):
        return None
    suffix = subtitle_stem[len(video_stem) :]
    if not suffix or suffix[0] not in _SUBTITLE_SUFFIX_BOUNDARIES:
        return None
    return suffix
