from __future__ import annotations

from contextlib import closing
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
from openlist_ani.domain import (
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
async def test_duplicate_resource_title_does_not_emit_false_completion(tmp_path):
    _, database, jobs, _ = await _repositories(tmp_path)
    first = await _claim_with_metadata(jobs, "Conflicting title", "magnet:first")
    await jobs.complete_with_resource(first, "/anime/first.mkv")
    second = await _claim_with_metadata(jobs, "Conflicting title", "magnet:second")

    await jobs.complete_with_resource(second, "/anime/second.mkv")

    stored = await jobs.get(second.id)
    assert stored is not None
    assert stored.status.value == "skipped"
    assert stored.last_error == "duplicate_resource_title"
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
