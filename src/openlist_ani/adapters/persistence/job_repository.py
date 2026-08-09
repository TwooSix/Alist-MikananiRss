"""SQLite repositories for durable jobs and per-feed runtime state."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    JobStep,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
)
from openlist_ani.domain.job import TERMINAL_JOB_STATUSES, utc_now

from .database import Database


class LostJobLease(RuntimeError):
    """The job was reclaimed by another worker before this write."""


class SqliteJobRepository:
    def __init__(
        self,
        database: Database,
        downloader_name: str = "openlist",
        lease_seconds: float = 300.0,
    ) -> None:
        self._database = database
        self._downloader_name = downloader_name
        self._lease_seconds = max(1.0, lease_seconds)

    async def recover_interrupted(self) -> int:
        now = utc_now()
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                """
                UPDATE jobs SET status = 'retry_wait', next_attempt_at = ?,
                    last_error = COALESCE(last_error, 'process interrupted'),
                    updated_at = ?, lease_token = NULL, lease_expires_at = NULL
                WHERE status = 'running'
                """,
                (now, now),
            )
            return max(0, cursor.rowcount)

    async def add_candidate(self, candidate: ReleaseCandidate) -> DownloadJob | None:
        job = DownloadJob(
            id=str(uuid.uuid4()),
            candidate=candidate,
            downloader_name=self._downloader_name,
        )
        async with self._database.operation(write=True) as db:
            duplicate = await (
                await db.execute(
                    "SELECT 1 FROM jobs WHERE source_key = ? OR download_url = ? "
                    "LIMIT 1",
                    (candidate.source_key, candidate.download_url),
                )
            ).fetchone()
            if duplicate:
                return None
            await db.execute(
                """
                INSERT INTO jobs (
                    id, source_key, source_name, source_url, title, download_url,
                    candidate_json, metadata_json, status, step, downloader_name,
                    checkpoint_version, checkpoint_json, artifact_json,
                    attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    candidate.source_key,
                    candidate.source_name,
                    candidate.source_url,
                    candidate.title,
                    candidate.download_url,
                    _json(_candidate_to_dict(candidate)),
                    _json(job.metadata.to_dict()),
                    job.status.value,
                    job.step.value,
                    job.downloader_name,
                    job.checkpoint_version,
                    "{}",
                    "{}",
                    0,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    async def claim(self, step: JobStep, limit: int) -> list[DownloadJob]:
        return await self._claim_steps((step,), limit)

    async def claim_download_work(self, limit: int) -> list[DownloadJob]:
        return await self._claim_steps(
            (JobStep.DOWNLOAD, JobStep.ORGANIZE, JobStep.FINALIZE), limit
        )

    async def _claim_steps(
        self, steps: tuple[JobStep, ...], limit: int
    ) -> list[DownloadJob]:
        if limit <= 0:
            return []
        now = utc_now()
        lease_expires_at = _after_seconds(self._lease_seconds)
        placeholders = ",".join("?" for _ in steps)
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                f"""
                SELECT id, status FROM jobs
                WHERE step IN ({placeholders})
                  AND (
                    (
                      status IN ('pending', 'retry_wait')
                      AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    )
                    OR (
                      status = 'running'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                    )
                  )
                ORDER BY created_at, id
                LIMIT ?
                """,
                (*[item.value for item in steps], now, now, limit),
            )
            selected = await cursor.fetchall()
            if not selected:
                return []
            ids = [row["id"] for row in selected]
            previous_status = {row["id"]: row["status"] for row in selected}
            id_placeholders = ",".join("?" for _ in ids)
            for job_id in ids:
                token = str(uuid.uuid4())
                await db.execute(
                    """
                UPDATE jobs SET
                    status = 'running',
                    attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    next_attempt_at = NULL,
                    lease_token = ?,
                    lease_expires_at = ?,
                    last_error = CASE
                        WHEN ? = 'running' THEN 'worker lease expired'
                        ELSE last_error
                    END
                WHERE id = ?
                    """,
                    (
                        now,
                        now,
                        token,
                        lease_expires_at,
                        previous_status[job_id],
                        job_id,
                    ),
                )
            rows = await (
                await db.execute(
                    f"SELECT * FROM jobs WHERE id IN ({id_placeholders}) "
                    "ORDER BY created_at, id",
                    tuple(ids),
                )
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    async def save(self, job: DownloadJob) -> None:
        job.updated_at = utc_now()
        async with self._database.operation(write=True) as db:
            await self._update_job(db, job, expected_lease=job.lease_token)

    async def renew_lease(self, job: DownloadJob) -> None:
        if not job.lease_token:
            raise LostJobLease(f"Job {job.id} has no active lease")
        now = utc_now()
        expires_at = _after_seconds(self._lease_seconds)
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                """
                UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_token = ?
                """,
                (expires_at, now, job.id, job.lease_token),
            )
            if cursor.rowcount != 1:
                raise LostJobLease(f"Job lease lost: {job.id}")
        job.updated_at = now
        job.lease_expires_at = expires_at

    async def reschedule(self, job: DownloadJob, error: str, delay: float) -> None:
        job.status = JobStatus.RETRY_WAIT
        job.last_error = error
        job.next_attempt_at = (
            datetime.now(UTC) + timedelta(seconds=max(0.0, delay))
        ).isoformat()
        await self.save(job)

    async def fail(self, job: DownloadJob, error: str) -> None:
        job.status = JobStatus.FAILED
        job.last_error = error
        job.next_attempt_at = None
        await self.save(job)

    async def skip(self, job: DownloadJob, reason: str) -> None:
        job.status = JobStatus.SKIPPED
        job.last_error = reason
        job.completed_at = utc_now()
        await self.save(job)

    async def get(self, job_id: str) -> DownloadJob | None:
        async with self._database.operation() as db:
            row = await (
                await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            ).fetchone()
        return _row_to_job(row) if row else None

    async def list_visible(self) -> list[DownloadJob]:
        async with self._database.operation() as db:
            rows = await (
                await db.execute(
                    "SELECT * FROM jobs WHERE status != 'skipped' "
                    "ORDER BY created_at DESC LIMIT 500"
                )
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    async def list_active(self) -> list[DownloadJob]:
        terminal = tuple(item.value for item in TERMINAL_JOB_STATUSES)
        placeholders = ",".join("?" for _ in terminal)
        async with self._database.operation() as db:
            rows = await (
                await db.execute(
                    f"SELECT * FROM jobs WHERE status NOT IN ({placeholders})",
                    terminal,
                )
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    async def complete_with_resource(
        self,
        job: DownloadJob,
        final_path: str,
    ) -> None:
        now = utc_now()
        metadata_payload = job.metadata.to_dict()
        release = job.metadata.values
        title = job.candidate.title
        download_url = job.candidate.download_url
        async with self._database.operation(write=True) as db:
            existing = await (
                await db.execute(
                    """
                    SELECT id, job_id, final_path FROM resources
                    WHERE job_id = ? OR title = ?
                    ORDER BY CASE WHEN job_id = ? THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (job.id, title, job.id),
                )
            ).fetchone()
            if existing is not None:
                job.step = JobStep.FINALIZE
                job.output_path = existing["final_path"] or final_path
                job.completed_at = now
                job.updated_at = now
                if existing["job_id"] == job.id:
                    job.status = JobStatus.COMPLETED
                    job.last_error = None
                else:
                    job.status = JobStatus.SKIPPED
                    job.last_error = "duplicate_resource_title"
                await self._update_job(db, job, expected_lease=job.lease_token)
                return

            await db.execute(
                """
                INSERT INTO resources (
                    url, title, anime_name, season, episode, fansub, quality,
                    languages, version, downloaded_at, job_id, final_path,
                    metadata_json, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    download_url,
                    title,
                    release.anime_name,
                    release.season,
                    release.episode,
                    release.fansub,
                    release.quality.value if release.quality else None,
                    "".join(item.value for item in release.languages),
                    release.version or 1,
                    now,
                    job.id,
                    final_path,
                    _json(metadata_payload.get("values", {})),
                    _json(metadata_payload.get("evidence", {})),
                ),
            )
            await db.execute(
                """
                INSERT INTO notification_outbox (
                    job_id, anime_name, title, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    job.id,
                    release.anime_name or "Unknown",
                    title,
                    now,
                    now,
                ),
            )
            job.status = JobStatus.COMPLETED
            job.step = JobStep.FINALIZE
            job.output_path = final_path
            job.completed_at = now
            job.updated_at = now
            job.last_error = None
            await self._update_job(db, job, expected_lease=job.lease_token)

    async def _update_job(
        self,
        db,
        job: DownloadJob,
        *,
        expected_lease: str | None,
    ) -> None:
        active_lease = job.status == JobStatus.RUNNING
        if active_lease and not expected_lease:
            raise LostJobLease(f"Running job {job.id} has no lease")
        lease_token = expected_lease if active_lease else None
        lease_expires_at = _after_seconds(self._lease_seconds) if active_lease else None
        cursor = await db.execute(
            """
            UPDATE jobs SET
                metadata_json = ?, status = ?, step = ?, downloader_name = ?,
                checkpoint_version = ?, checkpoint_json = ?, artifact_json = ?,
                attempt_count = ?, next_attempt_at = ?, last_error = ?,
                output_path = ?, updated_at = ?, started_at = ?, completed_at = ?,
                lease_token = ?, lease_expires_at = ?
            WHERE id = ? AND lease_token IS ?
            """,
            (
                _json(job.metadata.to_dict()),
                job.status.value,
                job.step.value,
                job.downloader_name,
                job.checkpoint_version,
                _json(job.checkpoint),
                _json(job.artifact),
                job.attempt_count,
                job.next_attempt_at,
                job.last_error,
                job.output_path,
                job.updated_at,
                job.started_at,
                job.completed_at,
                lease_token,
                lease_expires_at,
                job.id,
                expected_lease,
            ),
        )
        if cursor.rowcount != 1:
            raise LostJobLease(f"Job lease lost: {job.id}")
        job.lease_token = lease_token
        job.lease_expires_at = lease_expires_at


class SqliteFeedStateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def sync_urls(self, urls: list[str]) -> None:
        now = utc_now()
        unique_urls = list(dict.fromkeys(urls))
        async with self._database.operation(write=True) as db:
            await db.execute(
                "UPDATE feed_state SET enabled = 0, updated_at = ?", (now,)
            )
            for url in unique_urls:
                await db.execute(
                    """
                    INSERT INTO feed_state (url, enabled, next_poll_at, updated_at)
                    VALUES (?, 1, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET enabled = 1, updated_at = excluded.updated_at
                    """,
                    (url, now, now),
                )

    async def list_due(self, limit: int) -> list[str]:
        async with self._database.operation() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT url FROM feed_state
                    WHERE enabled = 1
                      AND (next_poll_at IS NULL OR next_poll_at <= ?)
                    ORDER BY next_poll_at, url LIMIT ?
                    """,
                    (utc_now(), limit),
                )
            ).fetchall()
        return [row[0] for row in rows]

    async def cache_headers(self, url: str) -> tuple[str | None, str | None]:
        async with self._database.operation() as db:
            row = await (
                await db.execute(
                    "SELECT etag, last_modified FROM feed_state WHERE url = ?",
                    (url,),
                )
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    async def mark_feed_success(
        self,
        url: str,
        interval_seconds: float,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._database.operation(write=True) as db:
            await db.execute(
                """
                UPDATE feed_state SET failure_count = 0, last_error = NULL,
                    etag = COALESCE(?, etag),
                    last_modified = COALESCE(?, last_modified),
                    next_poll_at = ?, updated_at = ? WHERE url = ?
                """,
                (
                    etag,
                    last_modified,
                    (now + timedelta(seconds=max(1.0, interval_seconds))).isoformat(),
                    now.isoformat(),
                    url,
                ),
            )

    async def mark_feed_failure(self, url: str, error: str) -> None:
        async with self._database.operation(write=True) as db:
            row = await (
                await db.execute(
                    "SELECT failure_count FROM feed_state WHERE url = ?", (url,)
                )
            ).fetchone()
            failures = int(row[0] if row else 0) + 1
            delay = min(21600, 60 * (5 ** min(failures - 1, 4)))
            now = datetime.now(UTC)
            await db.execute(
                """
                UPDATE feed_state SET failure_count = ?, last_error = ?,
                    next_poll_at = ?, updated_at = ? WHERE url = ?
                """,
                (
                    failures,
                    error,
                    (now + timedelta(seconds=delay)).isoformat(),
                    now.isoformat(),
                    url,
                ),
            )


def _candidate_to_dict(candidate: ReleaseCandidate) -> dict[str, Any]:
    return {
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "title": candidate.title,
        "download_url": candidate.download_url,
        "source_key": candidate.source_key,
        "guid": candidate.guid,
        "source_metadata": candidate.source_metadata.to_dict(),
    }


def _candidate_from_dict(payload: dict[str, Any]) -> ReleaseCandidate:
    return ReleaseCandidate(
        source_name=payload["source_name"],
        source_url=payload.get("source_url", ""),
        title=payload["title"],
        download_url=payload["download_url"],
        source_key=payload["source_key"],
        guid=payload.get("guid"),
        source_metadata=ReleaseMetadata.from_dict(payload.get("source_metadata")),
    )


def _row_to_job(row) -> DownloadJob:
    return DownloadJob(
        id=row["id"],
        candidate=_candidate_from_dict(json.loads(row["candidate_json"])),
        metadata=MetadataDocument.from_dict(json.loads(row["metadata_json"] or "{}")),
        status=JobStatus(row["status"]),
        step=JobStep(row["step"]),
        downloader_name=row["downloader_name"],
        checkpoint_version=row["checkpoint_version"],
        checkpoint=json.loads(row["checkpoint_json"] or "{}"),
        artifact=json.loads(row["artifact_json"] or "{}"),
        attempt_count=row["attempt_count"],
        next_attempt_at=row["next_attempt_at"],
        last_error=row["last_error"],
        output_path=row["output_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _after_seconds(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(0.0, seconds))).isoformat()


__all__ = ["LostJobLease", "SqliteFeedStateRepository", "SqliteJobRepository"]
