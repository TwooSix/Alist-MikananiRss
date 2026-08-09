"""Atomic first-run migration into the unified runtime database."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

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
        with self._migration_lock():
            self._run_locked()

    def _run_locked(self) -> None:
        version = self._schema_version(self.database_path)
        if version is not None and version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database {self.database_path} uses schema v{version}, but this "
                f"application supports up to v{SCHEMA_VERSION}. Refusing to "
                "start an unsupported downgrade."
            )
        if version == SCHEMA_VERSION and self._is_current(self.database_path):
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
            self._replace_database(temporary, self.database_path)
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
                if not row or row[0] is None or int(row[0]) != SCHEMA_VERSION:
                    return False
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    return False
                return LegacyMigrationRunner._schema_is_complete(connection)
        except sqlite3.Error:
            return False

    @staticmethod
    def _schema_version(path: Path) -> int | None:
        if not path.exists():
            return None
        try:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()
            return int(row[0]) if row and row[0] is not None else None
        except (sqlite3.Error, TypeError, ValueError):
            return None

    @staticmethod
    def _schema_is_complete(connection: sqlite3.Connection) -> bool:
        required_columns: dict[str, frozenset[str]] = {
            "resources": frozenset(
                {
                    "id",
                    "url",
                    "title",
                    "anime_name",
                    "season",
                    "episode",
                    "fansub",
                    "quality",
                    "languages",
                    "version",
                    "downloaded_at",
                    "job_id",
                    "final_path",
                    "metadata_json",
                    "provenance_json",
                }
            ),
            "jobs": frozenset(
                {
                    "id",
                    "source_key",
                    "source_name",
                    "source_url",
                    "title",
                    "download_url",
                    "candidate_json",
                    "metadata_json",
                    "status",
                    "step",
                    "downloader_name",
                    "checkpoint_version",
                    "checkpoint_json",
                    "artifact_json",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error",
                    "output_path",
                    "created_at",
                    "updated_at",
                    "started_at",
                    "completed_at",
                    "lease_token",
                    "lease_expires_at",
                }
            ),
            "feed_state": frozenset(
                {
                    "url",
                    "enabled",
                    "etag",
                    "last_modified",
                    "next_poll_at",
                    "failure_count",
                    "last_error",
                    "updated_at",
                }
            ),
            "metadata_cache": frozenset(
                {"provider", "cache_key", "provider_version", "payload", "expires_at"}
            ),
            "notification_outbox": frozenset(
                {
                    "id",
                    "job_id",
                    "anime_name",
                    "title",
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error",
                    "created_at",
                    "updated_at",
                    "delivered_at",
                    "lease_token",
                    "lease_expires_at",
                }
            ),
            "notification_deliveries": frozenset(
                {
                    "id",
                    "outbox_id",
                    "target_key",
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error",
                    "created_at",
                    "updated_at",
                    "delivered_at",
                    "lease_token",
                    "lease_expires_at",
                }
            ),
            "schema_migrations": frozenset({"version", "applied_at", "description"}),
        }
        for table, required in required_columns.items():
            actual = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not required <= actual:
                return False

        required_indexes = {
            "idx_title",
            "idx_anime_episode",
            "idx_resources_url",
            "idx_resources_job_id",
            "idx_jobs_claim",
            "idx_jobs_download_url",
            "idx_jobs_lease",
            "idx_feed_state_due",
            "idx_outbox_claim",
            "idx_outbox_lease",
            "idx_notification_delivery_claim",
            "idx_notification_delivery_lease",
        }
        actual_indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        return required_indexes <= actual_indexes

    @contextmanager
    def _migration_lock(self, timeout: float = 30.0) -> Iterator[None]:
        lock_path = self.database_path.with_name(
            f".{self.database_path.name}.migrate.lock"
        )
        try:
            handle = lock_path.open("a+b")
        except OSError as error:
            raise RuntimeError(
                f"Cannot create database migration lock {lock_path}: {error}"
            ) from error
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._lock_handle(handle)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeError(
                        f"Timed out waiting for database migration lock: {lock_path}"
                    ) from error
                time.sleep(0.05)
        try:
            yield
        finally:
            self._unlock_handle(handle)
            handle.close()

    @staticmethod
    def _lock_handle(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_handle(handle) -> None:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

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
    def _replace_database(temporary: Path, destination: Path) -> None:
        """Replace a database without destroying old WAL state on failure."""
        parked: list[tuple[Path, Path]] = []
        nonce = f"{os.getpid()}-{time.time_ns()}"
        try:
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{destination}{suffix}")
                if not sidecar.exists():
                    continue
                holding = destination.with_name(
                    f".{destination.name}{suffix}.pre-migration-{nonce}"
                )
                os.replace(sidecar, holding)
                parked.append((sidecar, holding))
            os.replace(temporary, destination)
        except Exception:
            for sidecar, holding in reversed(parked):
                if holding.exists() and not sidecar.exists():
                    os.replace(holding, sidecar)
            raise
        else:
            for _sidecar, holding in parked:
                try:
                    holding.unlink()
                except OSError:
                    # The parked name is not recognized by SQLite and is safe
                    # to clean during a later maintenance pass.
                    pass
