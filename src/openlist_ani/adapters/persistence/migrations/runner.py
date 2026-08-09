"""Atomic first-run migration into the unified runtime database."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from openlist_ani.logger import logger

from ..schema import SCHEMA_VERSION, apply_schema
from .legacy_v1_import import import_legacy_tasks


class LegacyMigrationRunner:
    def __init__(
        self,
        database_path: str | Path = "data/data.db",
        task_database_path: str | Path = "data/task_mementos.db",
        task_json_path: str | Path = "data/task_mementos.json",
    ) -> None:
        self.database_path = Path(database_path)
        self.task_database_path = Path(task_database_path)
        self.task_json_path = Path(task_json_path)

    def run(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if self._is_current(self.database_path):
            return

        temporary = self.database_path.with_name(
            f".{self.database_path.name}.migrating"
        )
        if temporary.exists():
            temporary.unlink()

        resource_count = self._table_count(self.database_path, "resources")
        if self.database_path.exists():
            backup = self._backup_path()
            self._sqlite_copy(self.database_path, backup)
            self._sqlite_copy(self.database_path, temporary)
        else:
            sqlite3.connect(temporary).close()

        try:
            with closing(sqlite3.connect(temporary)) as connection:
                apply_schema(connection)
                import_report = import_legacy_tasks(
                    connection,
                    self.task_database_path,
                    self.task_json_path,
                )
                connection.execute(
                    "INSERT OR REPLACE INTO schema_migrations "
                    "(version, applied_at, description) VALUES (?, ?, ?)",
                    (
                        SCHEMA_VERSION,
                        datetime.now(UTC).isoformat(),
                        "unified durable job runtime",
                    ),
                )
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError(f"SQLite migration check failed: {result}")
                migrated_resources = self._connection_table_count(
                    connection, "resources"
                )
                if migrated_resources != resource_count:
                    raise RuntimeError(
                        "SQLite migration resource count mismatch: "
                        f"before={resource_count}, after={migrated_resources}"
                    )
                migrated_jobs = self._connection_table_count(connection, "jobs")
                if migrated_jobs < import_report.discovered:
                    raise RuntimeError(
                        "SQLite migration job count mismatch: "
                        f"legacy={import_report.discovered}, stored={migrated_jobs}"
                    )
                self._verify_task_ids(connection, import_report.task_ids)
                connection.commit()
            self._remove_sidecars(self.database_path)
            os.replace(temporary, self.database_path)
            logger.info(
                f"Database schema migrated to v{SCHEMA_VERSION}; "
                f"legacy tasks discovered={import_report.discovered}, "
                f"inserted={import_report.inserted}, "
                f"preserved={import_report.preserved}"
            )
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise

    @staticmethod
    def _is_current(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()
            return bool(row and row[0] and int(row[0]) >= SCHEMA_VERSION)
        except sqlite3.Error:
            return False

    def _backup_path(self) -> Path:
        backup_dir = self.database_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return backup_dir / f"data-v1-{stamp}.db"

    @staticmethod
    def _table_count(path: Path, table: str) -> int:
        if not path.exists():
            return 0
        try:
            with closing(sqlite3.connect(path)) as connection:
                return LegacyMigrationRunner._connection_table_count(connection, table)
        except sqlite3.Error:
            return 0

    @staticmethod
    def _connection_table_count(connection: sqlite3.Connection, table: str) -> int:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not exists:
            return 0
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    @staticmethod
    def _verify_task_ids(
        connection: sqlite3.Connection,
        task_ids: tuple[str, ...],
    ) -> None:
        for offset in range(0, len(task_ids), 900):
            chunk = task_ids[offset : offset + 900]
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT id FROM jobs WHERE id IN ({placeholders})",
                chunk,
            ).fetchall()
            stored = {row[0] for row in rows}
            missing = [task_id for task_id in chunk if task_id not in stored]
            if missing:
                sample = ", ".join(missing[:5])
                raise RuntimeError(
                    "SQLite migration lost legacy task IDs: "
                    f"{sample} (missing={len(missing)})"
                )

    @staticmethod
    def _sqlite_copy(source: Path, destination: Path) -> None:
        with (
            closing(sqlite3.connect(source)) as source_db,
            closing(sqlite3.connect(destination)) as destination_db,
        ):
            source_db.backup(destination_db)

    @staticmethod
    def _remove_sidecars(path: Path) -> None:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
