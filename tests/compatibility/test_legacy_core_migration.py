import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from openlist_ani.adapters.persistence import LegacyMigrationRunner


def test_legacy_resources_and_checkpoint_are_imported_once(tmp_path):
    data_path = tmp_path / "data.db"
    task_path = tmp_path / "task_mementos.db"
    with closing(sqlite3.connect(data_path)) as connection:
        connection.execute("""
            CREATE TABLE resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT UNIQUE NOT NULL,
                anime_name TEXT,
                season INTEGER,
                episode INTEGER,
                fansub TEXT,
                quality TEXT,
                languages TEXT,
                version INTEGER,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        connection.execute(
            "INSERT INTO resources (url, title, anime_name, season, episode) "
            "VALUES (?, ?, ?, ?, ?)",
            ("magnet:old", "Old 01", "Old", 1, 1),
        )
        connection.commit()

    task = {
        "task_id": "legacy-task",
        "state": "downloaded",
        "release": {
            "title": "Legacy 02",
            "download_url": "magnet:legacy",
            "anime_name": "Legacy",
            "season": 1,
            "episode": 2,
            "fansub": None,
            "quality": "unknown",
            "languages": [],
            "version": 1,
        },
        "base_path": "/anime",
        "downloader": {
            "downloader_type": "openlist",
            "payload": {"remote_id": "abc"},
        },
        "pipeline": {
            "next_buffer": "rename",
            "downloaded_directory_path": "/anime/Legacy/Season 1",
            "downloaded_filename": "raw.mkv",
        },
        "retry": {"retry_count": 0, "max_retries": 3, "last_error": None},
        "schema_version": 1,
    }
    with closing(sqlite3.connect(task_path)) as connection:
        connection.execute(
            "CREATE TABLE task_mementos "
            "(task_id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO task_mementos VALUES (?, ?, ?)",
            (task["task_id"], task["state"], json.dumps(task)),
        )
        connection.commit()

    runner = LegacyMigrationRunner(data_path, task_path, tmp_path / "missing.json")
    runner.run()
    runner.run()

    with closing(sqlite3.connect(data_path)) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
        job = connection.execute(
            "SELECT * FROM jobs WHERE id = 'legacy-task'"
        ).fetchone()
        assert job["step"] == "organize"
        assert json.loads(job["checkpoint_json"])["remote_id"] == "abc"
        assert json.loads(job["artifact_json"])["base_path"] == "/anime"
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 4
        )
    assert len(list((tmp_path / "backups").glob("data-v1-*.db"))) == 1


def test_invalid_legacy_task_aborts_without_switching_database(tmp_path):
    data_path = tmp_path / "data.db"
    task_path = tmp_path / "task_mementos.db"
    with closing(sqlite3.connect(data_path)) as connection:
        connection.execute("""
            CREATE TABLE resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT UNIQUE NOT NULL,
                anime_name TEXT,
                season INTEGER,
                episode INTEGER,
                fansub TEXT,
                quality TEXT,
                languages TEXT,
                version INTEGER,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        connection.execute(
            "INSERT INTO resources (url, title) VALUES ('magnet:keep', 'keep-me')"
        )
        connection.commit()
    with closing(sqlite3.connect(task_path)) as connection:
        connection.execute(
            "CREATE TABLE task_mementos "
            "(task_id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO task_mementos VALUES (?, ?, ?)",
            ("broken-task", "pending", json.dumps({"broken": True})),
        )
        connection.commit()

    runner = LegacyMigrationRunner(data_path, task_path, tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="broken-task"):
        runner.run()

    with closing(sqlite3.connect(data_path)) as connection:
        assert (
            connection.execute("SELECT title FROM resources").fetchone()[0] == "keep-me"
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'schema_migrations'"
            ).fetchone()
            is None
        )
    assert not data_path.with_name(".data.db.migrating").exists()


def test_unknown_legacy_task_state_is_not_silently_finalized(tmp_path):
    task_path = tmp_path / "task_mementos.json"
    task_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "unknown-state",
                        "state": "future-state",
                        "release": {
                            "title": "Unknown state",
                            "download_url": "magnet:unknown-state",
                        },
                        "base_path": "/anime",
                        "schema_version": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    data_path = tmp_path / "data.db"
    runner = LegacyMigrationRunner(data_path, tmp_path / "missing.db", task_path)

    with pytest.raises(RuntimeError, match="Unsupported legacy task state"):
        runner.run()

    assert not data_path.exists()
    assert not data_path.with_name(".data.db.migrating").exists()


def test_existing_broken_task_database_does_not_fall_back_to_json(tmp_path):
    task_path = tmp_path / "task_mementos.db"
    with closing(sqlite3.connect(task_path)) as connection:
        connection.execute("CREATE TABLE unexpected (payload TEXT)")
        connection.commit()
    json_path = tmp_path / "task_mementos.json"
    json_path.write_text('{"tasks": []}', encoding="utf-8")

    runner = LegacyMigrationRunner(tmp_path / "data.db", task_path, json_path)
    with pytest.raises(RuntimeError, match="Cannot read legacy task database"):
        runner.run()


def test_v2_database_is_upgraded_with_lease_columns(tmp_path):
    data_path = tmp_path / "data.db"
    runner = LegacyMigrationRunner(
        data_path,
        tmp_path / "missing.db",
        tmp_path / "missing.json",
    )
    runner.run()
    with closing(sqlite3.connect(data_path)) as connection:
        connection.execute("DROP INDEX idx_jobs_lease")
        connection.execute("DROP INDEX idx_outbox_lease")
        connection.execute("ALTER TABLE jobs DROP COLUMN lease_token")
        connection.execute("ALTER TABLE jobs DROP COLUMN lease_expires_at")
        connection.execute("ALTER TABLE notification_outbox DROP COLUMN lease_token")
        connection.execute(
            "ALTER TABLE notification_outbox DROP COLUMN lease_expires_at"
        )
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            "INSERT INTO schema_migrations VALUES (2, '2026-01-01', 'v2')"
        )
        connection.commit()

    runner.run()

    with closing(sqlite3.connect(data_path)) as connection:
        job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        outbox_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(notification_outbox)")
        }
        assert {"lease_token", "lease_expires_at"} <= job_columns
        assert {"lease_token", "lease_expires_at"} <= outbox_columns
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 4
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'notification_deliveries'"
            ).fetchone()
            is not None
        )


def test_concurrent_database_migrations_are_serialized(tmp_path):
    data_path = tmp_path / "data.db"
    runners = [
        LegacyMigrationRunner(
            data_path,
            tmp_path / "missing.db",
            tmp_path / "missing.json",
        )
        for _ in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda runner: runner.run(), runners))

    with closing(sqlite3.connect(data_path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 4
        )
    assert len(list((tmp_path / "backups").glob("data-v1-*.db"))) == 0


def test_current_version_with_incomplete_schema_is_repaired(tmp_path):
    data_path = tmp_path / "data.db"
    runner = LegacyMigrationRunner(
        data_path,
        tmp_path / "missing.db",
        tmp_path / "missing.json",
    )
    runner.run()
    with closing(sqlite3.connect(data_path)) as connection:
        connection.execute("DROP TABLE notification_deliveries")
        connection.commit()

    runner.run()

    with closing(sqlite3.connect(data_path)) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'notification_deliveries'"
            ).fetchone()
            is not None
        )
    assert len(list((tmp_path / "backups").glob("data-v1-*.db"))) == 1


def test_future_database_version_is_rejected_without_modification(tmp_path):
    data_path = tmp_path / "data.db"
    with closing(sqlite3.connect(data_path)) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT, description TEXT)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (999, 'future', 'future')"
        )
        connection.commit()

    runner = LegacyMigrationRunner(
        data_path,
        tmp_path / "missing.db",
        tmp_path / "missing.json",
    )
    with pytest.raises(RuntimeError, match="unsupported downgrade"):
        runner.run()

    with closing(sqlite3.connect(data_path)) as connection:
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 999
        )
    assert not (tmp_path / "backups").exists()


def test_failed_database_replace_restores_wal_sidecars(tmp_path, monkeypatch):
    data_path = tmp_path / "data.db"
    temporary = tmp_path / ".data.db.migrating"
    data_path.write_bytes(b"old-database")
    temporary.write_bytes(b"new-database")
    wal_path = tmp_path / "data.db-wal"
    shm_path = tmp_path / "data.db-shm"
    wal_path.write_bytes(b"committed-wal")
    shm_path.write_bytes(b"shared-memory")
    real_replace = os.replace

    def fail_database_switch(source, destination):
        if Path(source) == temporary and Path(destination) == data_path:
            raise OSError("simulated replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_database_switch)

    with pytest.raises(OSError, match="simulated replace failure"):
        LegacyMigrationRunner._replace_database(temporary, data_path)

    assert data_path.read_bytes() == b"old-database"
    assert temporary.read_bytes() == b"new-database"
    assert wal_path.read_bytes() == b"committed-wal"
    assert shm_path.read_bytes() == b"shared-memory"
    assert not list(tmp_path.glob(".*.pre-migration-*"))
