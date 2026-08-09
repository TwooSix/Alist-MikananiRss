import pytest

from openlist_ani.adapters.download_backends.openlist import OpenListOrganizerAdapter
from openlist_ani.application.ports import DownloadedAsset
from openlist_ani.domain import DownloadJob, ReleaseCandidate


class _Entry:
    def __init__(self, name):
        self.name = name


class _Client:
    async def list_files(self, _path):
        return [_Entry("Example S01E01.mkv")]


class _ClientMustNotRename(_Client):
    async def rename_file(self, *_args):
        raise AssertionError("completed remote rename must be detected")


@pytest.mark.asyncio
async def test_organizer_recovers_after_remote_rename_before_checkpoint():
    candidate = ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="Example 01",
        download_url="magnet:example",
    )
    adapter = OpenListOrganizerAdapter(_ClientMustNotRename())

    result = await adapter.organize(
        DownloadJob(id="job", candidate=candidate),
        DownloadedAsset("/anime/Example", "raw.mkv"),
        "Example S01E01.mkv",
    )

    assert result.path == "/anime/Example/Example S01E01.mkv"
