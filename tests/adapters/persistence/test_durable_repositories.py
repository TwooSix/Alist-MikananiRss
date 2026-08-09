import json
import sqlite3
from contextlib import closing

import pytest

from openlist_ani.adapters.persistence import (
    Database,
    LegacyMigrationRunner,
    LostJobLease,
    LostOutboxLease,
    SqliteJobRepository,
    SqliteMetadataCacheRepository,
    SqliteOutboxRepository,
)
from openlist_ani.domain import (
    JobStep,
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
)


@pytest.mark.asyncio
async def test_jobs_are_deduplicated_recovered_and_finalized_atomically(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(
        path,
        tmp_path / "missing-tasks.db",
        tmp_path / "missing-tasks.json",
    ).run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    outbox = SqliteOutboxRepository(database)
    candidate = ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="Example 01",
        download_url="magnet:?xt=urn:btih:example",
    )

    job = await jobs.add_candidate(candidate)
    assert job is not None
    assert await jobs.add_candidate(candidate) is None
    claimed = await jobs.claim(JobStep.METADATA, 20)
    assert [item.id for item in claimed] == [job.id]
    assert claimed[0].attempt_count == 1

    assert await jobs.recover_interrupted() == 1
    recovered = (await jobs.claim(JobStep.METADATA, 1))[0]
    recovered.metadata = MetadataDocument()
    recovered.metadata.apply(
        MetadataPatch(
            source="title",
            values=ReleaseMetadata(anime_name="Parsed Example", season=1, episode=1),
            priority=10,
        )
    )
    recovered.metadata.apply(
        MetadataPatch(
            source="tmdb",
            values=ReleaseMetadata(anime_name="Example"),
            authoritative=True,
            priority=30,
        )
    )
    await jobs.complete_with_resource(recovered, "/anime/Example/01.mkv")
    await jobs.complete_with_resource(recovered, "/anime/Example/01.mkv")

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
            == 1
        )
        provenance = json.loads(
            connection.execute(
                "SELECT provenance_json FROM resources WHERE job_id = ?", (job.id,)
            ).fetchone()[0]
        )
        assert provenance["anime_name"] == [
            {
                "source": "title",
                "confidence": None,
                "authoritative": False,
                "degraded": False,
                "priority": 10,
                "value": "Parsed Example",
                "previous_value": None,
                "overrode": False,
            },
            {
                "source": "tmdb",
                "confidence": None,
                "authoritative": True,
                "degraded": False,
                "priority": 30,
                "value": "Example",
                "previous_value": "Parsed Example",
                "overrode": True,
            },
        ]
        connection.execute(
            "UPDATE notification_outbox SET status = 'sending' WHERE job_id = ?",
            (job.id,),
        )
        connection.commit()
    assert await outbox.recover_interrupted() == 1
    await database.close()


@pytest.mark.asyncio
async def test_expired_job_and_outbox_leases_are_reclaimed_safely(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(
        path,
        tmp_path / "missing-tasks.db",
        tmp_path / "missing-tasks.json",
    ).run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database, lease_seconds=60)
    outbox = SqliteOutboxRepository(database, lease_seconds=60)
    candidate = ReleaseCandidate.create(
        source_name="lease-test",
        source_url="https://example.test/rss",
        title="Lease Example 01",
        download_url="magnet:?xt=urn:btih:lease-example",
    )
    created = await jobs.add_candidate(candidate)
    assert created is not None
    first_claim = (await jobs.claim(JobStep.METADATA, 1))[0]
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE id = ?",
            (created.id,),
        )

    reclaimed = (await jobs.claim(JobStep.METADATA, 1))[0]
    assert reclaimed.lease_token != first_claim.lease_token
    with pytest.raises(LostJobLease):
        await jobs.reschedule(first_claim, "stale worker", 0)

    reclaimed.metadata = MetadataDocument(
        values=ReleaseMetadata(anime_name="Lease Example", season=1, episode=1)
    )
    await jobs.complete_with_resource(reclaimed, "/anime/Lease Example/01.mkv")

    first_notification = (await outbox.claim(1))[0]
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE notification_outbox "
            "SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (first_notification.id,),
        )
    reclaimed_notification = (await outbox.claim(1))[0]
    assert reclaimed_notification.lease_token != first_notification.lease_token
    with pytest.raises(LostOutboxLease):
        await outbox.delivered(first_notification)
    await outbox.delivered(reclaimed_notification)
    await database.close()


@pytest.mark.asyncio
async def test_finalize_title_conflict_does_not_report_untracked_completion(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)

    async def create_and_claim(source: str, url: str):
        candidate = ReleaseCandidate.create(
            source_name=source,
            source_url=f"https://{source}.test/rss",
            title="Conflicting title",
            download_url=url,
        )
        created = await jobs.add_candidate(candidate)
        assert created is not None
        claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
        claimed.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name="Conflict", season=1, episode=1)
        )
        return claimed, candidate

    first, _ = await create_and_claim("first", "magnet:first")
    await jobs.complete_with_resource(first, "/anime/first.mkv")

    second, _ = await create_and_claim("second", "magnet:second")
    await jobs.complete_with_resource(second, "/anime/second.mkv")
    stored_second = await jobs.get(second.id)

    assert stored_second is not None
    assert stored_second.status.value == "skipped"
    assert stored_second.last_error == "duplicate_resource_title"
    async with database.operation() as connection:
        resources = await (
            await connection.execute("SELECT COUNT(*) FROM resources")
        ).fetchone()
        notifications = await (
            await connection.execute("SELECT COUNT(*) FROM notification_outbox")
        ).fetchone()
    assert resources[0] == 1
    assert notifications[0] == 1
    await database.close()


@pytest.mark.asyncio
async def test_metadata_cache_is_persistent_and_bounded(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(
        path,
        tmp_path / "missing-tasks.db",
        tmp_path / "missing-tasks.json",
    ).run()
    database = Database(path)
    await database.start()
    cache = SqliteMetadataCacheRepository(database, max_entries=1)

    await cache.put("tmdb", "first", "1", {"id": 1}, 3600)
    await cache.put("tmdb", "second", "1", {"id": 2}, 7200)

    assert await cache.get("tmdb", "first", "1") is None
    assert await cache.get("tmdb", "second", "1") == {"id": 2}
    await database.close()


@pytest.mark.asyncio
async def test_notification_deliveries_batch_by_oldest_event_and_track_targets(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    jobs = SqliteJobRepository(database)
    outbox = SqliteOutboxRepository(database)

    async def complete(title: str, url: str):
        candidate = ReleaseCandidate.create(
            source_name="test",
            source_url="https://example.test/rss",
            title=title,
            download_url=url,
        )
        created = await jobs.add_candidate(candidate)
        assert created is not None
        claimed = (await jobs.claim(JobStep.METADATA, 1))[0]
        claimed.metadata = MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1)
        )
        await jobs.complete_with_resource(claimed, f"/anime/{title}.mkv")

    await complete("first", "magnet:first")
    await complete("second", "magnet:second")
    await outbox.initialize_targets(("paid", "free"))

    assert await outbox.claim_due("paid", 300) == []
    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE notification_outbox SET created_at = "
            "CASE WHEN title = 'first' THEN '2020-01-01T00:00:00+00:00' "
            "ELSE created_at END"
        )

    paid = await outbox.claim_due("paid", 300)
    assert [item.title for item in paid] == ["first", "second"]
    await outbox.delivery_succeeded(paid)

    free = await outbox.claim_due("free", 300)
    assert [item.title for item in free] == ["first", "second"]
    await outbox.delivery_retry(free, "channel unavailable")

    async with database.operation() as connection:
        states = await (
            await connection.execute(
                "SELECT target_key, status FROM notification_deliveries "
                "ORDER BY target_key, outbox_id"
            )
        ).fetchall()
        outbox_states = await (
            await connection.execute(
                "SELECT DISTINCT status FROM notification_outbox"
            )
        ).fetchall()
    assert [(row["target_key"], row["status"]) for row in states] == [
        ("free", "retry_wait"),
        ("free", "retry_wait"),
        ("paid", "delivered"),
        ("paid", "delivered"),
    ]
    assert {row["status"] for row in outbox_states} == {"pending"}

    async with database.operation(write=True) as connection:
        await connection.execute(
            "UPDATE notification_deliveries SET next_attempt_at = "
            "'2020-01-01T00:00:00+00:00' WHERE target_key = 'free'"
        )
    retried = await outbox.claim_due("free", 300)
    await outbox.delivery_succeeded(retried)
    async with database.operation() as connection:
        final = await (
            await connection.execute(
                "SELECT DISTINCT status FROM notification_outbox"
            )
        ).fetchall()
    assert {row["status"] for row in final} == {"delivered"}
    await database.close()


@pytest.mark.asyncio
async def test_removed_notification_target_is_skipped_without_backfill(tmp_path):
    path = tmp_path / "data.db"
    LegacyMigrationRunner(path, tmp_path / "none.db", tmp_path / "none.json").run()
    database = Database(path)
    await database.start()
    async with database.operation(write=True) as connection:
        await connection.execute(
            "INSERT INTO jobs (id, source_key, source_name, source_url, title, "
            "download_url, candidate_json, status, step, downloader_name, "
            "created_at, updated_at) VALUES "
            "('job', 'source', 'test', 'rss', 'title', 'magnet:test', '{}', "
            "'completed', 'finalize', 'openlist', "
            "'2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00')"
        )
        await connection.execute(
            "INSERT INTO notification_outbox "
            "(job_id, anime_name, title, created_at, updated_at) VALUES "
            "('job', 'Example', 'title', "
            "'2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00')"
        )
    outbox = SqliteOutboxRepository(database)
    await outbox.initialize_targets(("old", "kept"))
    await outbox.initialize_targets(("kept", "new"))

    async with database.operation() as connection:
        rows = await (
            await connection.execute(
                "SELECT target_key, status FROM notification_deliveries "
                "ORDER BY target_key"
            )
        ).fetchall()
    assert [(row["target_key"], row["status"]) for row in rows] == [
        ("kept", "pending"),
        ("old", "skipped"),
    ]
    await database.close()
