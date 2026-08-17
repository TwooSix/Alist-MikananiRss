"""Bounded persistent cache for authoritative metadata providers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .database import Database


class SqliteMetadataCacheRepository:
    def __init__(self, database: Database, max_entries: int = 10_000) -> None:
        self._database = database
        self._max_entries = max(1, max_entries)

    async def get(
        self, provider: str, cache_key: str, provider_version: str
    ) -> dict[str, Any] | None:
        async with self._database.operation() as db:
            row = await (
                await db.execute(
                    """
                    SELECT payload FROM metadata_cache
                    WHERE provider = ? AND cache_key = ? AND provider_version = ?
                      AND expires_at > ?
                    """,
                    (
                        provider,
                        cache_key,
                        provider_version,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            ).fetchone()
        return json.loads(row[0]) if row else None

    async def put(
        self,
        provider: str,
        cache_key: str,
        provider_version: str,
        payload: dict[str, Any],
        ttl_seconds: float,
    ) -> None:
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=max(1.0, ttl_seconds))
        ).isoformat()
        async with self._database.operation(write=True) as db:
            await db.execute(
                """
                INSERT INTO metadata_cache (
                    provider, cache_key, provider_version, payload, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, cache_key, provider_version) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at
                """,
                (
                    provider,
                    cache_key,
                    provider_version,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    expires_at,
                ),
            )
            await db.execute(
                "DELETE FROM metadata_cache WHERE expires_at <= ?",
                (datetime.now(UTC).isoformat(),),
            )
            await db.execute(
                """
                DELETE FROM metadata_cache WHERE rowid IN (
                    SELECT rowid FROM metadata_cache
                    ORDER BY expires_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self._max_entries,),
            )


__all__ = ["SqliteMetadataCacheRepository"]
