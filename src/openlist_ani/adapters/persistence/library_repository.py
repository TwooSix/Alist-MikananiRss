"""Read side of the legacy-compatible anime library."""

from __future__ import annotations

from .database import Database

SQLITE_PARAMETER_CHUNK_SIZE = 900


class SqliteLibraryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def is_downloaded(self, title: str) -> bool:
        async with self._database.operation() as db:
            row = await (
                await db.execute("SELECT 1 FROM resources WHERE title = ?", (title,))
            ).fetchone()
        return row is not None

    async def find_existing_titles(self, titles: list[str]) -> set[str]:
        unique = list(dict.fromkeys(titles))
        result: set[str] = set()
        async with self._database.operation() as db:
            for offset in range(0, len(unique), SQLITE_PARAMETER_CHUNK_SIZE):
                chunk = unique[offset : offset + SQLITE_PARAMETER_CHUNK_SIZE]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = await (
                    await db.execute(
                        f"SELECT title FROM resources WHERE title IN ({placeholders})",
                        tuple(chunk),
                    )
                ).fetchall()
                result.update(row[0] for row in rows)
        return result

    async def find_releases_by_episodes(
        self, keys: list[tuple[str, int, int]]
    ) -> dict[tuple[str, int, int], list[dict]]:
        unique = list(dict.fromkeys(keys))
        output = {key: [] for key in unique}
        if not unique:
            return output
        chunk_size = SQLITE_PARAMETER_CHUNK_SIZE // 3
        async with self._database.operation() as db:
            for offset in range(0, len(unique), chunk_size):
                chunk = unique[offset : offset + chunk_size]
                clauses = " OR ".join(
                    "(anime_name = ? AND season = ? AND episode = ?)" for _ in chunk
                )
                params = tuple(value for key in chunk for value in key)
                rows = await (
                    await db.execute(
                        "SELECT anime_name, season, episode, fansub, quality, "
                        f"languages, version FROM resources WHERE {clauses}",
                        params,
                    )
                ).fetchall()
                for row in rows:
                    key = (row["anime_name"], row["season"], row["episode"])
                    output.setdefault(key, []).append(
                        {
                            "fansub": row["fansub"],
                            "quality": row["quality"],
                            "languages": row["languages"],
                            "version": row["version"],
                        }
                    )
        return output
