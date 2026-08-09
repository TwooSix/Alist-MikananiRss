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
