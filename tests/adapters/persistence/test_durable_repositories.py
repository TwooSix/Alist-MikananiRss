from __future__ import annotations

from contextlib import closing
import json
import sqlite3

import pytest

from openlist_ani.adapters.persistence import (
    Database,
    LegacyMigrationRunner,
    LostJobLease,
    LostOutboxLease,
    SqliteJobRepository,
    SqliteOutboxRepository,
)
from openlist_ani.application.ports import CompletedResource
from openlist_ani.application.manual_policy import (
    MANUAL_PARTIAL_COLLECTION_RETRY_KEY,
)
from openlist_ani.domain import (
    JobStatus,
    JobStep,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
)


async def _repositories(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    return (
        path,
        database,
        SqliteJobRepository(database),
        SqliteOutboxRepository(database),
    )


def _candidate(title: str, url: str) -> ReleaseCandidate:
    return ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title=title,
        download_url=url,
    )


async def _claim_with_metadata(jobs, title: str, url: str):
    created = await jobs.add_candidate(_candidate(title, url))
    assert created is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    claimed.metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )
    return claimed


@pytest.mark.asyncio
async def test_jobs_are_deduplicated_recovered_and_finalized_once(tmp_path):
    path, database, jobs, _ = await _repositories(tmp_path)
    candidate = _candidate("Example 01", "magnet:example")

    created = await jobs.add_candidate(candidate)
    assert created is not None
    assert await jobs.add_candidate(candidate) is None
    assert len(await jobs.claim(JobStep.METADATA, 1)) == 1
    assert await jobs.recover_interrupted() == 1

    recovered = (await jobs.claim(JobStep.METADATA, 1))[0]
    recovered.metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )
    await jobs.complete_with_resource(recovered, "/anime/Example/01.mkv")
    await jobs.complete_with_resource(recovered, "/anime/Example/01.mkv")

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
            == 1
        )
    await database.close()


@pytest.mark.asyncio
async def test_initial_manual_policy_review_is_persisted_before_first_claim(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    candidate = ReleaseCandidate.create(
        source_name="manual",
        source_url="api",
        title="Reviewed release",
        download_url="magnet:reviewed",
    )
    metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Reviewed", season=1, episode=2)
    )

    created = await jobs.add_candidate(
        candidate,
        initial_artifact={"manual_policy_review": {"approved": True}},
        initial_metadata=metadata,
    )
    assert created is not None

    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    assert claimed.artifact["manual_policy_review"]["approved"] is True
    assert claimed.metadata.values.anime_name == "Reviewed"
    assert claimed.metadata.values.episode == 2
    await database.close()


@pytest.mark.asyncio
async def test_approved_manual_retry_revives_legacy_release_policy_skip(tmp_path):
    path, database, jobs, _ = await _repositories(tmp_path)
    candidate = ReleaseCandidate.create(
        source_name="manual",
        source_url="api",
        title="Previously filtered collection",
        download_url="magnet:legacy-filtered",
    )
    created = await jobs.add_candidate(candidate)
    assert created is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    claimed.checkpoint = {"old": True}
    claimed.artifact = {"old": True}
    await jobs.skip(claimed, "release_policy")

    reviewed_metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )
    revived = await jobs.add_candidate(
        candidate,
        initial_artifact={"manual_policy_review": {"approved": True}},
        initial_metadata=reviewed_metadata,
    )

    assert revived is not None
    assert revived.id == created.id
    assert revived.status.value == "pending"
    assert revived.step == JobStep.METADATA
    assert revived.attempt_count == 0
    assert revived.last_error is None
    assert revived.checkpoint == {}
    assert revived.artifact == {"manual_policy_review": {"approved": True}}
    assert revived.metadata.values.anime_name == "Example"
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT COUNT(*), status, last_error, checkpoint_json, artifact_json "
            "FROM jobs WHERE download_url = ?",
            (candidate.download_url,),
        ).fetchone()
    assert row[0] == 1
    assert row[1:4] == ("pending", None, "{}")
    assert json.loads(row[4])["manual_policy_review"]["approved"] is True
    await database.close()


@pytest.mark.asyncio
async def test_approved_manual_request_takes_over_filtered_feed_url(tmp_path):
    path, database, jobs, _ = await _repositories(tmp_path)
    download_url = "magnet:feed-filtered-collection"
    feed_candidate = ReleaseCandidate.create(
        source_name="daily-feed",
        source_url="https://example.test/rss",
        title="Filtered collection from RSS",
        download_url=download_url,
    )
    created = await jobs.add_candidate(feed_candidate)
    assert created is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    await jobs.skip(claimed, "release_policy")

    manual_candidate = ReleaseCandidate.create(
        source_name="manual",
        source_url="api",
        title="Filtered collection from RSS",
        download_url=download_url,
    )
    revived = await jobs.add_candidate(
        manual_candidate,
        initial_artifact={"manual_policy_review": {"approved": True}},
    )

    assert revived is not None
    assert revived.id == created.id
    assert revived.candidate.source_name == "manual"
    assert revived.status.value == "pending"
    assert revived.step == JobStep.METADATA
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT COUNT(*), source_name, status, last_error "
            "FROM jobs WHERE download_url = ?",
            (download_url,),
        ).fetchone()
    assert row == (1, "manual", "pending", None)
    await database.close()


@pytest.mark.parametrize(
    ("incoming_source", "skip_reason", "review"),
    [
        ("manual", "release_policy", {"approved": False}),
        ("manual", "release_policy", {"approved": "true"}),
        ("daily-feed", "release_policy", {"approved": True}),
        ("manual", "already_downloaded", {"approved": True}),
    ],
)
@pytest.mark.asyncio
async def test_policy_skip_revival_requires_literal_approved_manual_request(
    tmp_path,
    incoming_source,
    skip_reason,
    review,
):
    _, database, jobs, _ = await _repositories(tmp_path)
    download_url = "magnet:protected-policy-skip"
    original = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="daily-feed",
            source_url="https://example.test/rss",
            title="Protected historical row",
            download_url=download_url,
        )
    )
    assert original is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    await jobs.skip(claimed, skip_reason)

    duplicate = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name=incoming_source,
            source_url=(
                "api" if incoming_source == "manual" else "https://new.test/rss"
            ),
            title="Protected historical row",
            download_url=download_url,
        ),
        initial_artifact={"manual_policy_review": review},
    )

    assert duplicate is None
    stored = await jobs.get(original.id)
    assert stored is not None
    assert stored.candidate.source_name == "daily-feed"
    assert stored.status == JobStatus.SKIPPED
    assert stored.last_error == skip_reason
    await database.close()


@pytest.mark.asyncio
async def test_manual_insert_atomically_rejects_active_same_title(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    title = "Same active title"
    active = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="daily-feed",
            source_url="https://example.test/rss",
            title=title,
            download_url="magnet:active-title-first",
        )
    )
    assert active is not None

    duplicate = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title=title,
            download_url="magnet:active-title-second",
        ),
        initial_artifact={"manual_policy_review": {"approved": True}},
    )

    assert duplicate is None
    assert len(await jobs.list_active()) == 1
    await database.close()


@pytest.mark.asyncio
async def test_confirmed_collection_retry_revives_visible_policy_failure(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    candidate = ReleaseCandidate.create(
        source_name="manual",
        source_url="api",
        title="Opaque multi-video release",
        download_url="magnet:late-collection-policy",
    )
    created = await jobs.add_candidate(
        candidate,
        initial_artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": False,
                "acknowledged_conflicts": [],
            }
        },
    )
    assert created is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    await jobs.fail(
        claimed,
        "Manual policy confirmation is required for collection contents",
    )

    revived = await jobs.add_candidate(
        candidate,
        initial_artifact={
            "manual_policy_review": {
                "approved": True,
                "override_policy": True,
                "acknowledged_conflicts": ["collection:automatic-release-policy"],
            },
            "collection_hint": True,
        },
    )

    assert revived is not None
    assert revived.id == created.id
    assert revived.status == JobStatus.PENDING
    assert revived.last_error is None
    assert revived.artifact["collection_hint"] is True
    await database.close()


@pytest.mark.asyncio
async def test_partial_completed_collection_allows_separate_durable_manual_retry(
    tmp_path,
):
    path, database, jobs, _ = await _repositories(tmp_path)
    title = "Partially completed collection"
    download_url = "magnet:partial-completed-collection"
    original = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="daily-feed",
            source_url="https://example.test/rss",
            title=title,
            download_url=download_url,
        )
    )
    assert original is not None
    claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    episode_one = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )
    claimed.artifact["summary"] = {
        "collection": True,
        "items": [
            {
                "item_key": "episode-1",
                "state": "completed",
                "anime_name": "Example",
                "season": 1,
                "episode": 1,
            },
            {
                "item_key": "episode-2",
                "state": "skipped",
                "error": "release_policy",
                "anime_name": "Example",
                "season": 1,
                "episode": 2,
            },
        ],
    }
    await jobs.complete_with_resources(
        claimed,
        (
            CompletedResource(
                item_key="episode-1",
                source_path="Example S01E01.mkv",
                title=title,
                metadata=episode_one,
                final_path="/anime/Example/Example S01E01.mkv",
            ),
        ),
        claimed.artifact["summary"],
    )

    retry = await jobs.add_candidate(
        ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title=title,
            download_url=download_url,
            guid="manual-partial-retry:test",
        ),
        initial_artifact={
            "manual_policy_review": {"approved": True},
            MANUAL_PARTIAL_COLLECTION_RETRY_KEY: {
                "source_job_ids": [original.id],
                "completed_item_keys": ["episode-1"],
                "completed_episode_keys": [
                    {"anime_name": "Example", "season": 1, "episode": 1}
                ],
            },
        },
    )

    assert retry is not None
    assert retry.id != original.id
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT id, status FROM jobs WHERE download_url = ? ORDER BY created_at",
            (download_url,),
        ).fetchall()
    assert rows == [(original.id, "completed"), (retry.id, "pending")]
    await database.close()


@pytest.mark.asyncio
async def test_expired_leases_are_reclaimed_and_stale_workers_are_rejected(tmp_path):
    _, database, jobs, outbox = await _repositories(tmp_path)
    claimed = await _claim_with_metadata(jobs, "Lease Example", "magnet:lease")
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE id = ?",
            (claimed.id,),
        )

    reclaimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    with pytest.raises(LostJobLease):
        await jobs.reschedule(claimed, "stale worker", 0)
    reclaimed.metadata = claimed.metadata
    await jobs.complete_with_resource(reclaimed, "/anime/Lease/01.mkv")

    notification = (await outbox.claim(1))[0]
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE notification_outbox "
            "SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (notification.id,),
        )
    reclaimed_notification = (await outbox.claim(1))[0]
    with pytest.raises(LostOutboxLease):
        await outbox.delivered(notification)
    await outbox.delivered(reclaimed_notification)
    await database.close()


@pytest.mark.asyncio
async def test_duplicate_resource_titles_are_allowed_across_jobs(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    first = await _claim_with_metadata(jobs, "Conflicting title", "magnet:first")
    await jobs.complete_with_resource(first, "/anime/first.mkv")
    second = await _claim_with_metadata(jobs, "Conflicting title", "magnet:second")

    await jobs.complete_with_resource(second, "/anime/second.mkv")

    stored = await jobs.get(second.id)
    assert stored is not None
    assert stored.status.value == "completed"
    assert stored.last_error is None
    async with database.operation() as connection:
        resources = await (
            await connection.execute("SELECT COUNT(*) FROM resources")
        ).fetchone()
        notifications = await (
            await connection.execute("SELECT COUNT(*) FROM notification_outbox")
        ).fetchone()
    assert resources[0] == 2
    assert notifications[0] == 2
    await database.close()


@pytest.mark.asyncio
async def test_collection_resources_and_summary_are_committed_once(tmp_path):
    _, database, jobs, outbox = await _repositories(tmp_path)
    job = await _claim_with_metadata(jobs, "Example collection", "magnet:batch")
    episode_two = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=2)
    )
    episode_one = MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
    )
    resources = (
        CompletedResource(
            item_key="episode-2",
            source_path="disc/02.mkv",
            title="Example 02",
            metadata=episode_two,
            final_path="/anime/Example/Season 1/Example S01E02.mkv",
        ),
        CompletedResource(
            item_key="episode-1",
            source_path="disc/01.mkv",
            title="Example 01",
            metadata=episode_one,
            final_path="/anime/Example/Season 1/Example S01E01.mkv",
        ),
    )
    summary = {"success_count": 2, "warning_count": 1, "episodes": [1, 2]}

    await jobs.complete_with_resources(job, resources, summary)
    await jobs.complete_with_resources(job, resources, summary)

    stored = await jobs.get(job.id)
    assert stored is not None
    assert stored.status.value == "completed"
    assert stored.output_path == resources[1].final_path
    async with database.operation() as connection:
        rows = await (
            await connection.execute(
                "SELECT title, item_key, source_path, final_path, metadata_json "
                "FROM resources WHERE job_id = ? ORDER BY item_key",
                (job.id,),
            )
        ).fetchall()
        outbox_row = await (
            await connection.execute(
                "SELECT summary_json FROM notification_outbox WHERE job_id = ?",
                (job.id,),
            )
        ).fetchone()
    assert [row["item_key"] for row in rows] == ["episode-1", "episode-2"]
    assert [row["title"] for row in rows] == ["Example 01", "Example 02"]
    assert rows[0]["source_path"] == "disc/01.mkv"
    assert json.loads(rows[0]["metadata_json"])["episode"] == 1
    assert json.loads(outbox_row["summary_json"]) == summary

    notification = (await outbox.claim(1))[0]
    assert notification.summary == summary
    await database.close()


@pytest.mark.asyncio
async def test_collection_resource_replay_must_match_persisted_content(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    job = await _claim_with_metadata(jobs, "Example collection", "magnet:batch")
    original = CompletedResource(
        item_key="episode-1",
        source_path="disc/01.mkv",
        title="Example 01",
        metadata=MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        ),
        final_path="/anime/Example/Season 1/Example S01E01.mkv",
    )
    await jobs.complete_with_resources(job, (original,), {})
    conflicting = CompletedResource(
        item_key=original.item_key,
        source_path=original.source_path,
        title=original.title,
        metadata=MetadataDocument(
            values=ReleaseMetadata(anime_name="Other", season=1, episode=1)
        ),
        final_path=original.final_path,
    )

    with pytest.raises(RuntimeError, match="conflicts with an existing item"):
        await jobs.complete_with_resources(job, (conflicting,), {})

    await database.close()


@pytest.mark.asyncio
async def test_collection_completion_replay_must_match_persisted_summary(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    job = await _claim_with_metadata(jobs, "Example collection", "magnet:batch")
    resource = CompletedResource(
        item_key="episode-1",
        source_path="01.mkv",
        title="Example 01",
        metadata=MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        ),
        final_path="/anime/Example/Season 1/Example S01E01.mkv",
    )
    await jobs.complete_with_resources(job, (resource,), {"success_count": 1})

    with pytest.raises(RuntimeError, match="Notification completion conflicts"):
        await jobs.complete_with_resources(job, (resource,), {"success_count": 9})

    await database.close()


@pytest.mark.asyncio
async def test_resolve_files_jobs_are_claimed_as_download_work(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    created = await jobs.add_candidate(_candidate("Collection", "magnet:resolve"))
    assert created is not None
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE jobs SET step = 'resolve_files' WHERE id = ?", (created.id,)
        )

    claimed = await jobs.claim_download_work(1)

    assert [job.id for job in claimed] == [created.id]
    assert claimed[0].step == JobStep.RESOLVE_FILES
    await database.close()


@pytest.mark.asyncio
async def test_notification_delivery_is_tracked_independently_per_target(tmp_path):
    _, database, jobs, outbox = await _repositories(tmp_path)
    for title, url in (("first", "magnet:first"), ("second", "magnet:second")):
        job = await _claim_with_metadata(jobs, title, url)
        job.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name=title, season=1, episode=1)
        )
        await jobs.complete_with_resource(job, f"/anime/{title}.mkv")
    await outbox.initialize_targets(("paid", "free"))

    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE notification_outbox SET created_at = '2020-01-01T00:00:00+00:00'"
        )
    paid = await outbox.claim_due("paid", 300)
    free = await outbox.claim_due("free", 300)
    assert {item.title for item in paid} == {"first", "second"}
    assert {item.title for item in free} == {"first", "second"}

    await outbox.delivery_succeeded(paid)
    await outbox.delivery_retry(free, "channel unavailable")
    async with database.operation() as connection:
        states = await (
            await connection.execute(
                "SELECT target_key, status FROM notification_deliveries"
            )
        ).fetchall()
    assert {(row["target_key"], row["status"]) for row in states} == {
        ("paid", "delivered"),
        ("free", "retry_wait"),
    }
    await database.close()
