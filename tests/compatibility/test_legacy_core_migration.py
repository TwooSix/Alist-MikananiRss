import json
import sqlite3
from contextlib import closing

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
            == 3
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
            == 3
        )
