from types import SimpleNamespace
from unittest.mock import AsyncMock

from openlist_ani.adapters.download_backends.openlist import OpenListOrganizerAdapter
from openlist_ani.application.ports import DownloadedAsset, DownloadedSidecar
from openlist_ani.domain import DownloadJob, ReleaseCandidate


def _job() -> DownloadJob:
    return DownloadJob(
        id="workflow-1",
        candidate=ReleaseCandidate.create(
            source_name="test",
            source_url="https://example.test/rss",
            title="Example 01",
            download_url="magnet:?xt=urn:btih:example",
        ),
    )


async def test_organizer_only_renames_inside_target_directory():
    client = AsyncMock()
    client.list_files = AsyncMock(
        return_value=[SimpleNamespace(name="raw episode.mkv")]
    )
    client.rename_file = AsyncMock(return_value=True)
    client.move_file = AsyncMock(return_value=True)
    organizer = OpenListOrganizerAdapter(client, sleep=AsyncMock())

    organized = await organizer.organize(
        _job(),
        DownloadedAsset("/anime/Example/Season 1", "raw episode.mkv"),
        "Example S01E01 1080p.mkv",
    )

    assert organized.filename == "Example S01E01 1080p.mkv"
    client.rename_file.assert_awaited_once_with(
        "/anime/Example/Season 1/raw episode.mkv",
        "Example S01E01 1080p.mkv",
    )
    client.move_file.assert_not_awaited()


async def test_organizer_recovers_completed_remote_rename():
    client = AsyncMock()
    client.list_files = AsyncMock(
        return_value=[SimpleNamespace(name="Example S01E01.mkv")]
    )
    organizer = OpenListOrganizerAdapter(client, sleep=AsyncMock())

    organized = await organizer.organize(
        _job(),
        DownloadedAsset("/anime/Example/Season 1", "raw.mkv"),
        "Example S01E01.mkv",
    )

    assert organized.filename == "Example S01E01.mkv"
    client.rename_file.assert_not_awaited()


class _StatefulClient:
    def __init__(self, names):
        self.names = set(names)
        self.renames = []

    async def list_files(self, _path):
        return [SimpleNamespace(name=name) for name in sorted(self.names)]

    async def rename_file(self, source_path, target):
        source = source_path.rsplit("/", 1)[-1]
        if source not in self.names or target in self.names:
            return False
        self.names.remove(source)
        self.names.add(target)
        self.renames.append((source, target))
        return True


async def test_organizer_renames_video_and_preserves_sidecar_suffixes():
    client = _StatefulClient(
        {"raw.mkv", "raw.ass", "raw.zh-CN.ass", "raw_CHS.srt"}
    )
    organizer = OpenListOrganizerAdapter(client, sleep=AsyncMock())
    checkpoints = []

    async def checkpoint(payload):
        checkpoints.append(payload)

    organized = await organizer.organize(
        _job(),
        DownloadedAsset(
            "/anime/Example/Season 1",
            "raw.mkv",
            sidecars=(
                DownloadedSidecar("raw.ass", ""),
                DownloadedSidecar("raw.zh-CN.ass", ".zh-CN"),
                DownloadedSidecar("raw_CHS.srt", "_CHS"),
            ),
        ),
        "Example S01E01.mkv",
        checkpoint,
    )

    assert organized.filename == "Example S01E01.mkv"
    assert organized.sidecar_filenames == (
        "Example S01E01.ass",
        "Example S01E01.zh-CN.ass",
        "Example S01E01_CHS.srt",
    )
    assert set(organized.sidecar_filenames) <= client.names
    assert checkpoints[0]["files"][0]["target"] == "Example S01E01.mkv"


async def test_organizer_uses_video_conflict_suffix_for_sidecars():
    client = _StatefulClient({"raw.mkv", "raw.ass", "Example S01E01.mkv"})
    organizer = OpenListOrganizerAdapter(client, sleep=AsyncMock())

    organized = await organizer.organize(
        _job(),
        DownloadedAsset(
            "/anime/Example/Season 1",
            "raw.mkv",
            sidecars=(DownloadedSidecar("raw.ass", ""),),
        ),
        "Example S01E01.mkv",
    )

    assert organized.filename == "Example S01E01 (1).mkv"
    assert organized.sidecar_filenames == ("Example S01E01 (1).ass",)


async def test_organizer_resumes_partially_applied_persisted_plan():
    client = _StatefulClient({"Example S01E01.mkv", "raw.zh.ass"})
    organizer = OpenListOrganizerAdapter(client, sleep=AsyncMock())
    job = _job()
    job.artifact["organize_plan"] = {
        "files": [
            {
                "kind": "video",
                "source": "raw.mkv",
                "target": "Example S01E01.mkv",
            },
            {
                "kind": "subtitle",
                "source": "raw.zh.ass",
                "target": "Example S01E01.zh.ass",
            },
        ]
    }

    organized = await organizer.organize(
        job,
        DownloadedAsset(
            "/anime/Example/Season 1",
            "raw.mkv",
            sidecars=(DownloadedSidecar("raw.zh.ass", ".zh"),),
        ),
        "Example S01E01.mkv",
    )

    assert organized.sidecar_filenames == ("Example S01E01.zh.ass",)
    assert client.renames == [("raw.zh.ass", "Example S01E01.zh.ass")]
