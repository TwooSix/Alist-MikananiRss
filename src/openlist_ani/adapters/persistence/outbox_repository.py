"""Durable notification outbox."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from openlist_ani.domain.job import utc_now

from .database import Database


@dataclass(frozen=True)
class OutboxItem:
    id: int
    job_id: str
    anime_name: str
    title: str
    attempt_count: int
    lease_token: str


class LostOutboxLease(RuntimeError):
    """The notification was reclaimed before delivery state was persisted."""


class SqliteOutboxRepository:
    def __init__(self, database: Database, lease_seconds: float = 300.0) -> None:
        self._database = database
        self._lease_seconds = max(1.0, lease_seconds)

    async def recover_interrupted(self) -> int:
        now = utc_now()
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                """
                UPDATE notification_outbox
                SET status = 'retry_wait', next_attempt_at = ?,
                    last_error = COALESCE(last_error, 'process interrupted'),
                    updated_at = ?, lease_token = NULL, lease_expires_at = NULL
                WHERE status = 'sending'
                """,
                (now, now),
            )
            return max(0, cursor.rowcount)

    async def claim(self, limit: int) -> list[OutboxItem]:
        now = utc_now()
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=self._lease_seconds)
        ).isoformat()
        async with self._database.operation(write=True) as db:
            rows = await (
                await db.execute(
                    """
                    SELECT id, job_id, anime_name, title, attempt_count
                    FROM notification_outbox
                    WHERE (
                        status IN ('pending', 'retry_wait')
                        AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    ) OR (
                        status = 'sending'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                    ORDER BY created_at, id LIMIT ?
                    """,
                    (now, now, limit),
                )
            ).fetchall()
            tokens: dict[int, str] = {}
            for row in rows:
                token = str(uuid.uuid4())
                tokens[row["id"]] = token
                await db.execute(
                    "UPDATE notification_outbox SET status = 'sending', "
                    "attempt_count = attempt_count + 1, updated_at = ?, "
                    "next_attempt_at = NULL, lease_token = ?, lease_expires_at = ? "
                    "WHERE id = ?",
                    (now, token, expires_at, row["id"]),
                )
        return [
            OutboxItem(
                id=row["id"],
                job_id=row["job_id"],
                anime_name=row["anime_name"],
                title=row["title"],
                attempt_count=row["attempt_count"] + 1,
                lease_token=tokens[row["id"]],
            )
            for row in rows
        ]

    async def delivered(self, item: OutboxItem) -> None:
        now = utc_now()
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                "UPDATE notification_outbox SET status = 'delivered', "
                "delivered_at = ?, updated_at = ?, last_error = NULL, "
                "lease_token = NULL, lease_expires_at = NULL "
                "WHERE id = ? AND lease_token = ?",
                (now, now, item.id, item.lease_token),
            )
            if cursor.rowcount != 1:
                raise LostOutboxLease(f"Outbox lease lost: {item.id}")

    async def retry(self, item: OutboxItem, error: str) -> None:
        delay = min(21600, 60 * (5 ** min(max(item.attempt_count - 1, 0), 4)))
        now = datetime.now(UTC)
        async with self._database.operation(write=True) as db:
            cursor = await db.execute(
                "UPDATE notification_outbox SET status = 'retry_wait', last_error = ?, "
                "next_attempt_at = ?, updated_at = ?, lease_token = NULL, "
                "lease_expires_at = NULL WHERE id = ? AND lease_token = ?",
                (
                    error,
                    (now + timedelta(seconds=delay)).isoformat(),
                    now.isoformat(),
                    item.id,
                    item.lease_token,
                ),
            )
            if cursor.rowcount != 1:
                raise LostOutboxLease(f"Outbox lease lost: {item.id}")
