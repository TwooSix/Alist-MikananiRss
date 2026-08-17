import asyncio
from contextlib import closing
import sqlite3
from unittest.mock import AsyncMock

import pytest

from openlist_ani.adapters.persistence import (
    Database,
    LegacyMigrationRunner,
    SqliteJobRepository,
    SqliteLibraryRepository,
)
from openlist_ani.adapters.torrent import TorrentToMagnetCandidateTransformer
from openlist_ani.application.manual_policy import (
    MANUAL_PARTIAL_COLLECTION_RETRY_KEY,
)
from openlist_ani.application.metadata_worker import MetadataWorker
from openlist_ani.application.settings import CoreSettings, MetadataFilterSettings
from openlist_ani.domain import (
    DownloadJob,
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
    assert first is not None
    assert second is not None

    claimed = await jobs.claim(JobStep.METADATA, 20)
    for job in claimed:
        job.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        )
    await worker._apply_release_policies(claimed)

    stored = [await jobs.get(first.id), await jobs.get(second.id)]
    selected = [job for job in stored if job.status == JobStatus.PENDING]
    rejected = [job for job in stored if job.status == JobStatus.SKIPPED]
    assert len(selected) == 1
    assert len(rejected) == 1
    assert selected[0].step == JobStep.DOWNLOAD
    assert rejected[0].last_error == "duplicate_active_title"
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


@pytest.mark.asyncio
async def test_filtered_feed_can_be_reactivated_by_approved_manual_same_url(
    tmp_path,
):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    library = SqliteLibraryRepository(database)
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
            metadata_filter=MetadataFilterSettings(exclude_patterns=["Batch"]),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    download_url = "magnet:?xt=urn:btih:filtered-feed-batch"
    feed_candidate = ReleaseCandidate.create(
        source_name="daily-feed",
        source_url="https://feed.invalid/rss",
        title="Example S01E01-E12 Batch",
        download_url=download_url,
    )
    original = await jobs.add_candidate(feed_candidate)
    assert original is not None

    await worker._process_batch(await jobs.claim(JobStep.METADATA, 1))

    filtered = await jobs.get(original.id)
    assert filtered is not None
    assert filtered.status == JobStatus.SKIPPED
    assert filtered.last_error == "release_policy"
    assert await jobs.list_visible() == []

    manual_candidate = ReleaseCandidate.create(
        source_name="manual",
        source_url="api",
        title=feed_candidate.title,
        download_url=download_url,
    )
    revived = await jobs.add_candidate(
        manual_candidate,
        initial_artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": [
                    "title_pattern:Batch",
                    "collection:automatic-release-policy",
                ],
            }
        },
    )

    assert revived is not None
    assert revived.id == original.id
    assert revived.candidate.source_name == "manual"
    assert revived.candidate.source_key == manual_candidate.source_key
    assert revived.candidate.source_key != feed_candidate.source_key
    visible = await jobs.list_visible()
    assert [job.id for job in visible] == [original.id]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1

    await worker._process_batch(await jobs.claim(JobStep.METADATA, 1))

    queued = await jobs.get(original.id)
    assert queued is not None
    assert queued.status == JobStatus.PENDING
    assert queued.step == JobStep.DOWNLOAD
    assert queued.artifact["manual_policy_review"]["approved"] is True
    assert download_available.is_set()
    await database.close()


@pytest.mark.asyncio
async def test_only_policy_winner_is_transformed_before_download(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    library = SqliteLibraryRepository(database)
    download_available = asyncio.Event()
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    converter = AsyncMock(return_value=magnet)
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=("regex",),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
        candidate_transformers=[TorrentToMagnetCandidateTransformer(converter)],
    )
    original_urls = [
        "https://a.test/release.torrent",
        "https://b.test/release.torrent",
    ]
    created = []
    for source, url in zip(("source-a", "source-b"), original_urls):
        created.append(
            await jobs.add_candidate(
                ReleaseCandidate.create(
                    source_name=source,
                    source_url=f"https://{source}.test/rss",
                    title="Identical title",
                    download_url=url,
                )
            )
        )
    assert all(job is not None for job in created)

    claimed = await jobs.claim(JobStep.METADATA, 20)
    source_keys = {job.id: job.candidate.source_key for job in claimed}
    for job in claimed:
        job.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        )
    await worker._apply_release_policies(claimed)

    stored = [await jobs.get(job.id) for job in claimed]
    winner = next(job for job in stored if job.status == JobStatus.PENDING)
    rejected = next(job for job in stored if job.status == JobStatus.SKIPPED)
    assert winner.step == JobStep.DOWNLOAD
    assert winner.candidate.download_url == magnet
    assert winner.candidate.source_key == source_keys[winner.id]
    assert rejected.candidate.download_url in original_urls
    converter.assert_awaited_once()
    assert download_available.is_set()
    await database.close()


@pytest.mark.asyncio
async def test_candidate_transform_failure_is_rescheduled_before_download(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    library = SqliteLibraryRepository(database)
    download_available = asyncio.Event()
    converter = AsyncMock(side_effect=ValueError("invalid torrent"))
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=("regex",),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
        candidate_transformers=[TorrentToMagnetCandidateTransformer(converter)],
    )
    created = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="source",
            source_url="https://source.test/rss",
            title="Example title",
            download_url="https://source.test/release.torrent",
        )
    )
    assert created is not None
    job = (await jobs.claim(JobStep.METADATA, 1))[0]
    job.metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )

    await worker._apply_release_policies([job])

    stored = await jobs.get(job.id)
    assert stored.status == JobStatus.RETRY_WAIT
    assert stored.step == JobStep.METADATA
    assert stored.last_error == "candidate transform failed: invalid torrent"
    assert not download_available.is_set()
    await database.close()


@pytest.mark.asyncio
async def test_candidate_transform_failure_is_bounded():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    library.find_releases_by_episodes.return_value = {}
    jobs.list_active.return_value = []
    job = DownloadJob(
        id="job-1",
        candidate=ReleaseCandidate.create(
            source_name="source",
            source_url="https://source.test/rss",
            title="Example title",
            download_url="https://source.test/release.torrent",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        ),
        attempt_count=3,
    )
    converter = AsyncMock(side_effect=ValueError("invalid torrent"))
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=("regex",),
        ),
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
        candidate_transformers=[TorrentToMagnetCandidateTransformer(converter)],
    )

    await worker._apply_release_policies([job])

    jobs.fail.assert_awaited_once_with(
        job, "candidate transform failed: invalid torrent"
    )
    jobs.reschedule.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_collection_title_enters_download_without_parent_episode_metadata():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    jobs.list_active.return_value = []
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    job = DownloadJob(
        id="collection-job",
        candidate=ReleaseCandidate.create(
            source_name="feed",
            source_url="https://feed.invalid/rss",
            title="Example S01E01-E12 Batch",
            download_url="magnet:?xt=urn:btih:batch",
        ),
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._process_batch([job])

    assert job.step == JobStep.DOWNLOAD
    assert job.artifact["collection_hint"] is True
    jobs.save.assert_awaited_once_with(job)
    jobs.reschedule.assert_not_awaited()
    assert download_available.is_set()


@pytest.mark.asyncio
async def test_user_pattern_can_explicitly_disable_collection_downloads():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    jobs.list_active.return_value = []
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
            metadata_filter=MetadataFilterSettings(exclude_patterns=["Batch"]),
        ),
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
    )
    job = DownloadJob(
        id="collection-job",
        candidate=ReleaseCandidate.create(
            source_name="feed",
            source_url="https://feed.invalid/rss",
            title="Example S01E01-E12 Batch",
            download_url="magnet:?xt=urn:btih:batch",
        ),
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._process_batch([job])

    jobs.skip.assert_awaited_once_with(job, "release_policy")
    jobs.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_manual_collection_bypasses_rss_title_filter():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    jobs.list_active.return_value = []
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
            metadata_filter=MetadataFilterSettings(exclude_patterns=["Batch"]),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    job = DownloadJob(
        id="manual-collection",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Example S01E01-E12 Batch",
            download_url="magnet:?xt=urn:btih:manual-batch",
        ),
        artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["title_pattern:Batch"],
            }
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._process_batch([job])

    jobs.skip.assert_not_awaited()
    jobs.save.assert_awaited_once_with(job)
    assert job.step == JobStep.DOWNLOAD
    assert job.artifact["collection_hint"] is True
    assert download_available.is_set()


@pytest.mark.asyncio
async def test_multivideo_hint_routes_opaque_manual_title_as_collection():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    jobs.list_active.return_value = []
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    job = DownloadJob(
        id="manual-opaque-collection",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Opaque release title",
            download_url="magnet:?xt=urn:btih:opaque-collection",
        ),
        artifact={
            "collection_hint": True,
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["collection:automatic-release-policy"],
            },
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._process_batch([job])

    jobs.skip.assert_not_awaited()
    jobs.fail.assert_not_awaited()
    jobs.save.assert_awaited_once_with(job)
    assert job.step == JobStep.DOWNLOAD
    assert job.artifact["collection_hint"] is True
    assert download_available.is_set()


@pytest.mark.asyncio
async def test_partial_collection_retry_ignores_parent_title_already_downloaded():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = {"Existing partial collection"}
    jobs.list_active.return_value = []
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    job = DownloadJob(
        id="manual-partial-retry",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Existing partial collection",
            download_url="magnet:?xt=urn:btih:partial-retry",
            guid="manual-partial-retry:test",
        ),
        artifact={
            "collection_hint": True,
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["collection:automatic-release-policy"],
            },
            MANUAL_PARTIAL_COLLECTION_RETRY_KEY: {
                "source_job_ids": ["completed-partial-parent"],
                "completed_item_keys": ["episode-1"],
                "completed_episode_keys": [
                    {"anime_name": "Example", "season": 1, "episode": 1}
                ],
            },
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._process_batch([job])

    jobs.fail.assert_not_awaited()
    jobs.skip.assert_not_awaited()
    jobs.save.assert_awaited_once_with(job)
    assert job.step == JobStep.DOWNLOAD
    assert download_available.is_set()


@pytest.mark.asyncio
async def test_approved_manual_release_bypasses_metadata_filter():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    library.find_releases_by_episodes.return_value = {}
    jobs.list_active.return_value = []
    download_available = asyncio.Event()
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
            metadata_filter=MetadataFilterSettings(exclude_fansub=["Blocked"]),
        ),
        jobs_available=asyncio.Event(),
        download_available=download_available,
    )
    job = DownloadJob(
        id="manual-release",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Example - 01",
            download_url="magnet:?xt=urn:btih:manual-release",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                fansub="Blocked",
                quality=VideoQuality.Q1080P,
            )
        ),
        artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["metadata:fansub=Blocked"],
            }
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._apply_release_policies([job])

    jobs.skip.assert_not_awaited()
    jobs.save.assert_awaited_once_with(job)
    assert job.step == JobStep.DOWNLOAD
    assert download_available.is_set()


@pytest.mark.asyncio
async def test_reviewed_manual_release_fails_visible_for_unacknowledged_filter():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = set()
    library.find_releases_by_episodes.return_value = {}
    jobs.list_active.return_value = []
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
            metadata_filter=MetadataFilterSettings(exclude_fansub=["Blocked"]),
        ),
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
    )
    job = DownloadJob(
        id="manual-unacknowledged-release",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Example - 01",
            download_url="magnet:?xt=urn:btih:manual-unacknowledged-release",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                fansub="Blocked",
            )
        ),
        artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": False,
                "acknowledged_conflicts": [],
            }
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._apply_release_policies([job])

    jobs.skip.assert_not_awaited()
    jobs.fail.assert_awaited_once_with(job, "manual_policy_confirmation_required")


@pytest.mark.asyncio
async def test_reviewed_manual_release_fails_visible_for_late_hard_duplicate():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_existing_titles.return_value = {"Example - 01"}
    library.find_releases_by_episodes.return_value = {}
    jobs.list_active.return_value = []
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
    )
    job = DownloadJob(
        id="manual-late-duplicate",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Example - 01",
            download_url="magnet:?xt=urn:btih:manual-late-duplicate",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        ),
        artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": False,
                "acknowledged_conflicts": [],
            }
        },
        status=JobStatus.RUNNING,
        attempt_count=1,
    )

    await worker._apply_release_policies([job])

    jobs.skip.assert_not_awaited()
    jobs.fail.assert_awaited_once_with(job, "already_downloaded")


@pytest.mark.asyncio
async def test_manual_priority_override_does_not_reject_better_feed_in_same_batch():
    jobs = AsyncMock()
    library = AsyncMock()
    library.find_releases_by_episodes.return_value = {
        ("Example", 1, 1): [
            {
                "fansub": "Known",
                "quality": "1080p",
                "languages": "",
                "version": 1,
            }
        ]
    }
    worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=[],
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        jobs_available=asyncio.Event(),
        download_available=asyncio.Event(),
    )
    manual = DownloadJob(
        id="manual-lower-priority",
        candidate=ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title="Example - 01 manual",
            download_url="magnet:manual-lower-priority",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                quality=VideoQuality.Q720P,
            )
        ),
        artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["priority:dominated"],
            }
        },
    )
    feed = DownloadJob(
        id="feed-higher-priority",
        candidate=ReleaseCandidate.create(
            source_name="daily-feed",
            source_url="https://feed.invalid/rss",
            title="Example - 01 feed",
            download_url="magnet:feed-higher-priority",
        ),
        metadata=MetadataDocument(
            values=ReleaseMetadata(
                anime_name="Example",
                season=1,
                episode=1,
                quality=VideoQuality.Q2160P,
            )
        ),
    )
    rejected: dict[str, str] = {}

    await worker._apply_priority_policy([manual, feed], [], rejected)

    assert rejected == {}
