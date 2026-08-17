"""Durable notification outbox."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboxDelivery:
    id: int
    outbox_id: int
    job_id: str
    target_key: str
    anime_name: str
    title: str
    attempt_count: int
    lease_token: str
    created_at: str
    summary: dict[str, Any] = field(default_factory=dict)


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
            delivery_cursor = await db.execute(
                """
                UPDATE notification_deliveries
                SET status = 'retry_wait', next_attempt_at = ?,
                    last_error = COALESCE(last_error, 'process interrupted'),
                    updated_at = ?, lease_token = NULL, lease_expires_at = NULL
                WHERE status = 'sending'
                """,
                (now, now),
            )
            return max(0, cursor.rowcount) + max(0, delivery_cursor.rowcount)

    async def initialize_targets(self, target_keys: tuple[str, ...]) -> None:
        """Snapshot current targets for outbox events that have not started delivery."""
        now = utc_now()
        active_targets = tuple(dict.fromkeys(target_keys))
        async with self._database.operation(write=True) as db:
            rows = await (await db.execute("""
                    SELECT o.id
                    FROM notification_outbox o
                    WHERE o.status != 'delivered'
                      AND NOT EXISTS (
                          SELECT 1 FROM notification_deliveries d
                          WHERE d.outbox_id = o.id
                      )
                    ORDER BY o.created_at, o.id
                    """)).fetchall()
            if active_targets:
                for row in rows:
                    for target_key in active_targets:
                        await db.execute(
                            """
                            INSERT OR IGNORE INTO notification_deliveries (
                                outbox_id, target_key, status, created_at, updated_at
                            ) VALUES (?, ?, 'pending', ?, ?)
                            """,
                            (row["id"], target_key, now, now),
                        )
            elif rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                await db.execute(
                    f"UPDATE notification_outbox SET status = 'delivered', "
                    f"delivered_at = ?, updated_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (now, now, *ids),
                )

            if active_targets:
                placeholders = ",".join("?" for _ in active_targets)
                await db.execute(
                    "UPDATE notification_deliveries SET status = 'skipped', "
                    "updated_at = ?, last_error = 'notification target removed', "
                    "lease_token = NULL, lease_expires_at = NULL "
                    f"WHERE status NOT IN ('delivered', 'skipped') "
                    f"AND target_key NOT IN ({placeholders})",
                    (now, *active_targets),
                )
            else:
                await db.execute(
                    "UPDATE notification_deliveries SET status = 'skipped', "
                    "updated_at = ?, last_error = 'notification target removed', "
                    "lease_token = NULL, lease_expires_at = NULL "
                    "WHERE status NOT IN ('delivered', 'skipped')",
                    (now,),
                )
            await self._complete_terminal_outboxes(db, now)

    async def claim_due(
        self,
        target_key: str,
        batch_interval: float,
    ) -> list[OutboxDelivery]:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=self._lease_seconds)).isoformat()
        async with self._database.operation(write=True) as db:
            row = await (
                await db.execute(
                    """
                    SELECT d.status, d.next_attempt_at, d.lease_expires_at,
                           o.created_at
                    FROM notification_deliveries d
                    JOIN notification_outbox o ON o.id = d.outbox_id
                    WHERE d.target_key = ? AND (
                        (d.status IN ('pending', 'retry_wait')
                         AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?))
                        OR (d.status = 'sending' AND d.lease_expires_at <= ?)
                    )
                    ORDER BY o.created_at, o.id LIMIT 1
                    """,
                    (target_key, now, now),
                )
            ).fetchone()
            if row is None or self._delivery_due_at(row, batch_interval) > now_dt:
                return []

            limit_clause = "LIMIT 1" if batch_interval <= 0 else ""
            rows = await (
                await db.execute(
                    f"""
                    SELECT d.id, d.outbox_id, d.target_key, d.attempt_count,
                            o.job_id, o.anime_name, o.title, o.created_at,
                            o.summary_json
                    FROM notification_deliveries d
                    JOIN notification_outbox o ON o.id = d.outbox_id
                    WHERE d.target_key = ? AND (
                        (d.status IN ('pending', 'retry_wait')
                         AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?))
                        OR (d.status = 'sending' AND d.lease_expires_at <= ?)
                    )
                    ORDER BY o.created_at, o.id {limit_clause}
                    """,
                    (target_key, now, now),
                )
            ).fetchall()
            tokens: dict[int, str] = {}
            for item in rows:
                token = str(uuid.uuid4())
                tokens[item["id"]] = token
                await db.execute(
                    "UPDATE notification_deliveries SET status = 'sending', "
                    "attempt_count = attempt_count + 1, next_attempt_at = NULL, "
                    "updated_at = ?, lease_token = ?, lease_expires_at = ? "
                    "WHERE id = ?",
                    (now, token, expires_at, item["id"]),
                )
        return [
            OutboxDelivery(
                id=item["id"],
                outbox_id=item["outbox_id"],
                job_id=item["job_id"],
                target_key=item["target_key"],
                anime_name=item["anime_name"],
                title=item["title"],
                attempt_count=item["attempt_count"] + 1,
                lease_token=tokens[item["id"]],
                created_at=item["created_at"],
                summary=_decode_summary(item["summary_json"]),
            )
            for item in rows
        ]

    async def next_due_delay(
        self,
        target_keys: tuple[str, ...],
        batch_interval: float,
    ) -> float | None:
        if not target_keys:
            return None
        placeholders = ",".join("?" for _ in target_keys)
        async with self._database.operation() as db:
            rows = await (
                await db.execute(
                    f"""
                    SELECT d.status, d.next_attempt_at, d.lease_expires_at,
                           o.created_at
                    FROM notification_deliveries d
                    JOIN notification_outbox o ON o.id = d.outbox_id
                    WHERE d.target_key IN ({placeholders})
                      AND d.status IN ('pending', 'retry_wait', 'sending')
                    """,
                    target_keys,
                )
            ).fetchall()
        if not rows:
            return None
        now = datetime.now(UTC)
        due = min(self._delivery_due_at(row, batch_interval) for row in rows)
        return max(0.0, (due - now).total_seconds())

    async def delivery_succeeded(self, items: list[OutboxDelivery]) -> None:
        if not items:
            return
        now = utc_now()
        async with self._database.operation(write=True) as db:
            for item in items:
                cursor = await db.execute(
                    "UPDATE notification_deliveries SET status = 'delivered', "
                    "delivered_at = ?, updated_at = ?, last_error = NULL, "
                    "lease_token = NULL, lease_expires_at = NULL "
                    "WHERE id = ? AND lease_token = ?",
                    (now, now, item.id, item.lease_token),
                )
                if cursor.rowcount != 1:
                    raise LostOutboxLease(f"Delivery lease lost: {item.id}")
            await self._complete_terminal_outboxes(db, now)

    async def delivery_retry(
        self,
        items: list[OutboxDelivery],
        error: str,
    ) -> None:
        if not items:
            return
        now = datetime.now(UTC)
        async with self._database.operation(write=True) as db:
            for item in items:
                delay = self._retry_delay(item.attempt_count)
                cursor = await db.execute(
                    "UPDATE notification_deliveries SET status = 'retry_wait', "
                    "last_error = ?, next_attempt_at = ?, updated_at = ?, "
                    "lease_token = NULL, lease_expires_at = NULL "
                    "WHERE id = ? AND lease_token = ?",
                    (
                        error,
                        (now + timedelta(seconds=delay)).isoformat(),
                        now.isoformat(),
                        item.id,
                        item.lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise LostOutboxLease(f"Delivery lease lost: {item.id}")

    @staticmethod
    def _delivery_due_at(row, batch_interval: float) -> datetime:
        created_at = datetime.fromisoformat(row["created_at"])
        due_at = created_at + timedelta(seconds=max(0.0, batch_interval))
        next_attempt = row["next_attempt_at"]
        if next_attempt:
            due_at = max(due_at, datetime.fromisoformat(next_attempt))
        if row["status"] == "sending" and row["lease_expires_at"]:
            due_at = max(due_at, datetime.fromisoformat(row["lease_expires_at"]))
        return due_at

    @staticmethod
    def _retry_delay(attempt_count: int) -> int:
        return min(21600, 60 * (5 ** min(max(attempt_count - 1, 0), 4)))

    @staticmethod
    async def _complete_terminal_outboxes(db, now: str) -> None:
        await db.execute(
            """
            UPDATE notification_outbox
            SET status = 'delivered', delivered_at = ?, updated_at = ?,
                last_error = NULL, lease_token = NULL, lease_expires_at = NULL
            WHERE status != 'delivered'
              AND EXISTS (
                  SELECT 1 FROM notification_deliveries d
                  WHERE d.outbox_id = notification_outbox.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM notification_deliveries d
                  WHERE d.outbox_id = notification_outbox.id
                    AND d.status NOT IN ('delivered', 'skipped')
              )
            """,
            (now, now),
        )

    async def claim(self, limit: int) -> list[OutboxItem]:
        now = utc_now()
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=self._lease_seconds)
        ).isoformat()
        async with self._database.operation(write=True) as db:
            rows = await (
                await db.execute(
                    """
                    SELECT id, job_id, anime_name, title, attempt_count,
                           summary_json
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
                summary=_decode_summary(row["summary_json"]),
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


def _decode_summary(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
