from types import SimpleNamespace
from unittest.mock import AsyncMock

from openlist_ani.adapters.download_backends.openlist.file_detection import (
    OpenListFileDetector,
)


def _entry(name: str, *, is_dir: bool = False, size: int = 0):
    return SimpleNamespace(name=name, is_dir=is_dir, size=size)


async def test_inventory_discards_failed_nested_scan_then_returns_complete_snapshot():
    client = AsyncMock()
    root = [_entry("Season 1", is_dir=True), _entry("readme.txt", size=3)]
    season = [_entry("01.mkv", size=100), _entry("01.ass", size=4)]
    client.list_files = AsyncMock(
        side_effect=[
            root,
            None,
            root,
            season,
            root,
            season,
            root,
            season,
        ]
    )
    detector = OpenListFileDetector(client, AsyncMock(), timeout_seconds=1)

    result = await detector.inventory("/staging/job-1")

    assert [(item.relative_path, item.size) for item in result] == [
        ("readme.txt", 3),
        ("Season 1/01.ass", 4),
        ("Season 1/01.mkv", 100),
    ]
    assert client.list_files.await_count == 8


async def test_inventory_waits_for_transient_empty_nested_directory_to_fill():
    client = AsyncMock()
    root = [_entry("Season 1", is_dir=True), _entry("readme.txt", size=3)]
    season = [_entry("01.mkv", size=100)]
    client.list_files = AsyncMock(
        side_effect=[
            root,
            [],
            root,
            season,
            root,
            season,
            root,
            season,
        ]
    )
    detector = OpenListFileDetector(client, AsyncMock(), timeout_seconds=1)

    result = await detector.inventory("/staging/job-1")

    assert [item.relative_path for item in result] == [
        "readme.txt",
        "Season 1/01.mkv",
    ]
    assert client.list_files.await_count == 8


async def test_inventory_timeout_never_returns_partial_nested_scan(monkeypatch):
    client = AsyncMock()
    root_path = "/staging/job-1"

    async def persistently_incomplete(path):
        if path == root_path:
            return [_entry("Season 1", is_dir=True), _entry("readme.txt", size=3)]
        return None

    client.list_files = AsyncMock(side_effect=persistently_incomplete)
    monotonic = iter((100.0, 100.1, 100.2, 101.0))
    monkeypatch.setattr(
        "openlist_ani.adapters.download_backends.openlist.file_detection.time",
        SimpleNamespace(monotonic=lambda: next(monotonic)),
    )
    sleep = AsyncMock()
    detector = OpenListFileDetector(client, sleep, timeout_seconds=0.5)

    result = await detector.inventory(root_path)

    assert result == ()
    assert client.list_files.await_count == 6
    assert sleep.await_count == 2
