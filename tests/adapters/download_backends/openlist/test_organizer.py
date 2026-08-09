from types import SimpleNamespace
from unittest.mock import AsyncMock

from openlist_ani.adapters.download_backends.openlist import OpenListOrganizerAdapter
from openlist_ani.application.ports import DownloadedAsset
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
