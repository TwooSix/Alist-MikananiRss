"""Bounded, explicitly owned aiosqlite connection."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


class Database:
    def __init__(self, path: str | Path = "data/data.db") -> None:
        self.path = Path(path)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._connection is not None:
            return
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA synchronous=NORMAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._connection.execute("PRAGMA busy_timeout=30000")
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @asynccontextmanager
    async def operation(
        self, *, write: bool = False
    ) -> AsyncIterator[aiosqlite.Connection]:
        if self._connection is None:
            raise RuntimeError("Database is not started")
        async with self._lock:
            if write:
                await self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                if write:
                    await self._connection.commit()
            except BaseException:
                if write:
                    await self._connection.rollback()
                raise
