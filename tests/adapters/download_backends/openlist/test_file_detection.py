from types import SimpleNamespace
from unittest.mock import AsyncMock

from openlist_ani.adapters.download_backends.openlist.file_detection import (
    OpenListFileDetector,
)


async def test_detector_returns_only_sidecars_related_to_selected_video():
    entries = [
        SimpleNamespace(name="foo.mkv", is_dir=False, size=1000),
        SimpleNamespace(name="foo.ass", is_dir=False, size=10),
        SimpleNamespace(name="foo.zh-CN.ASS", is_dir=False, size=10),
        SimpleNamespace(name="foo_CHS.srt", is_dir=False, size=10),
        SimpleNamespace(name="foo2.ass", is_dir=False, size=10),
        SimpleNamespace(name="other.srt", is_dir=False, size=10),
        SimpleNamespace(name="foo.txt", is_dir=False, size=10),
    ]
    client = AsyncMock()
    client.list_files = AsyncMock(return_value=entries)
    detector = OpenListFileDetector(client, sleep=AsyncMock())

    detected = await detector.detect("/tmp/job")

    assert detected is not None
    assert detected.video_relative_path == "foo.mkv"
    assert [(item.relative_path, item.suffix) for item in detected.sidecars] == [
        ("foo.ass", ""),
        ("foo.zh-CN.ASS", ".zh-CN"),
        ("foo_CHS.srt", "_CHS"),
    ]


async def test_detector_matches_subtitles_only_in_nested_video_directory():
    client = AsyncMock()

    async def list_files(path):
        if path == "/tmp/job":
            return [SimpleNamespace(name="release", is_dir=True, size=0)]
        return [
            SimpleNamespace(name="episode.mkv", is_dir=False, size=1000),
            SimpleNamespace(name="episode [CHS].ass", is_dir=False, size=10),
        ]

    client.list_files = AsyncMock(side_effect=list_files)
    detector = OpenListFileDetector(client, sleep=AsyncMock())

    detected = await detector.detect("/tmp/job")

    assert detected is not None
    assert detected.video_relative_path == "release/episode.mkv"
    assert detected.sidecars[0].relative_path == "release/episode [CHS].ass"
    assert detected.sidecars[0].suffix == " [CHS]"
