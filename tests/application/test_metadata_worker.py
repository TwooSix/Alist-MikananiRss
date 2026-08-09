import asyncio

import pytest

from openlist_ani.adapters.persistence import (
    Database,
    LegacyMigrationRunner,
    SqliteJobRepository,
    SqliteLibraryRepository,
)
from openlist_ani.application.metadata_worker import MetadataWorker
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import (
    JobStatus,
    JobStep,
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)


@pytest.mark.asyncio
async def test_same_title_is_reserved_before_parallel_download(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    library = SqliteLibraryRepository(database)
    settings = CoreSettings(
        download_path="/anime",
        rename_format="{anime_name} S{season:02d}E{episode:02d}",
        rss_interval_seconds=300,
        metadata_providers=("regex",),
    )
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=settings,
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
    )
    first = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="source-a",
            source_url="https://a.test/rss",
            title="Identical title",
            download_url="magnet:?xt=urn:btih:first",
        )
    )
    second = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="source-b",
            source_url="https://b.test/rss",
            title="Identical title",
            download_url="magnet:?xt=urn:btih:second",
        )
    )
    assert first is not None and second is not None

    claimed = await jobs.claim(JobStep.METADATA, 20)
    for job in claimed:
        job.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        )
    await worker._apply_release_policies(claimed)

    stored = [await jobs.get(first.id), await jobs.get(second.id)]
    assert [job.status for job in stored] == [JobStatus.PENDING, JobStatus.SKIPPED]
    assert stored[0].step == JobStep.DOWNLOAD
    assert stored[1].last_error == "duplicate_active_title"
    await database.close()


@pytest.mark.asyncio
async def test_same_download_url_is_idempotent_across_feed_sources(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    url = "magnet:?xt=urn:btih:shared"

    first = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="source-a",
            source_url="https://a.test/rss",
            title="Example A",
            download_url=url,
        )
    )
    duplicate = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="source-b",
            source_url="https://b.test/rss",
            title="Example B",
            download_url=url,
        )
    )

    assert first is not None
    assert duplicate is None
    await database.close()


def test_feed_unknown_quality_does_not_override_title_resolution():
    candidate = ReleaseCandidate.create(
        source_name="mikan",
        source_url="https://mikan.example/rss",
        title="Example 01 V2 [1080P]",
        download_url="https://mikan.example/release.torrent",
        source_metadata=ReleaseMetadata(
            anime_name="Example",
            season=1,
            quality=VideoQuality.UNKNOWN,
        ),
    )
    document = MetadataDocument()
    document.apply(
        MetadataPatch(
            source="llm",
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                quality=VideoQuality.Q1080P,
                version=2,
            ),
            priority=10,
        )
    )

    MetadataWorker._apply_feed_metadata([candidate], [document])

    assert document.values.quality == VideoQuality.Q1080P
    assert document.values.version == 2
    assert [item.source for item in document.evidence["quality"]] == ["llm"]
    assert [item.source for item in document.evidence["version"]] == ["llm"]
