"""SQLite schema for the durable core runtime."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 5

RESOURCE_TABLE_SQL = """
CREATE TABLE resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    anime_name TEXT,
    season INTEGER,
    episode INTEGER,
    fansub TEXT,
    quality TEXT,
    languages TEXT,
    version INTEGER,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    job_id TEXT,
    item_key TEXT NOT NULL,
    source_path TEXT NOT NULL,
    final_path TEXT,
    metadata_json TEXT,
    provenance_json TEXT
)
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    anime_name TEXT,
    season INTEGER,
    episode INTEGER,
    fansub TEXT,
    quality TEXT,
    languages TEXT,
    version INTEGER,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    job_id TEXT,
    item_key TEXT NOT NULL,
    source_path TEXT NOT NULL,
    final_path TEXT,
    metadata_json TEXT,
    provenance_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_title ON resources(title);
CREATE INDEX IF NOT EXISTS idx_anime_episode
    ON resources(anime_name, season, episode);
CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(url);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_key TEXT UNIQUE NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    download_url TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    step TEXT NOT NULL,
    downloader_name TEXT NOT NULL,
    checkpoint_version INTEGER NOT NULL DEFAULT 1,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    artifact_json TEXT NOT NULL DEFAULT '{}',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    output_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    lease_token TEXT,
    lease_expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON jobs(step, status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_download_url ON jobs(download_url);

CREATE TABLE IF NOT EXISTS feed_state (
    url TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    etag TEXT,
    last_modified TEXT,
    next_poll_at TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feed_state_due
    ON feed_state(enabled, next_poll_at);

CREATE TABLE IF NOT EXISTS metadata_cache (
    provider TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY(provider, cache_key, provider_version)
);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    anime_name TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(job_id),
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_outbox_claim
    ON notification_outbox(status, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id INTEGER NOT NULL,
    target_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    UNIQUE(outbox_id, target_key),
    FOREIGN KEY(outbox_id) REFERENCES notification_outbox(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notification_delivery_claim
    ON notification_deliveries(target_key, status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_notification_delivery_lease
    ON notification_deliveries(status, lease_expires_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);
"""

RESOURCE_ADDITIVE_COLUMNS: dict[str, str] = {
    "job_id": "TEXT",
    "final_path": "TEXT",
    "metadata_json": "TEXT",
    "provenance_json": "TEXT",
}

JOB_ADDITIVE_COLUMNS: dict[str, str] = {
    "lease_token": "TEXT",
    "lease_expires_at": "TEXT",
}

OUTBOX_ADDITIVE_COLUMNS: dict[str, str] = {
    "lease_token": "TEXT",
    "lease_expires_at": "TEXT",
    "summary_json": "TEXT NOT NULL DEFAULT '{}'",
}


def apply_schema(connection: sqlite3.Connection) -> None:
    _rebuild_resources_for_v5(connection)
    connection.executescript(SCHEMA_SQL)
    _add_columns(connection, "resources", RESOURCE_ADDITIVE_COLUMNS)
    _add_columns(connection, "jobs", JOB_ADDITIVE_COLUMNS)
    _add_columns(connection, "notification_outbox", OUTBOX_ADDITIVE_COLUMNS)
    connection.execute("DROP INDEX IF EXISTS idx_resources_job_id")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_job_item "
        "ON resources(job_id, item_key)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(status, lease_expires_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_lease "
        "ON notification_outbox(status, lease_expires_at)"
    )


def _add_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, sql_type in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def _rebuild_resources_for_v5(connection: sqlite3.Connection) -> None:
    """Rebuild the v4 table to remove constraints SQLite cannot alter in place."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'resources'"
    ).fetchone()
    if not exists or _resources_constraints_are_v5(connection):
        return

    legacy_table = "resources__v4_migration"
    collision = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (legacy_table,),
    ).fetchone()
    if collision:
        raise RuntimeError(
            f"Cannot migrate resources: reserved table {legacy_table!r} already exists"
        )

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(resources)").fetchall()
    }
    required_legacy = {"id", "url", "title"}
    if not required_legacy <= columns:
        missing = ", ".join(sorted(required_legacy - columns))
        raise RuntimeError(f"Cannot migrate resources: missing columns: {missing}")

    connection.execute(f"ALTER TABLE resources RENAME TO {legacy_table}")
    connection.execute(RESOURCE_TABLE_SQL)
    target_columns = (
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
        "item_key",
        "source_path",
        "final_path",
        "metadata_json",
        "provenance_json",
    )
    expressions = {
        "id": "id",
        "url": "url",
        "title": "title",
        "anime_name": _column_or_null(columns, "anime_name"),
        "season": _column_or_null(columns, "season"),
        "episode": _column_or_null(columns, "episode"),
        "fansub": _column_or_null(columns, "fansub"),
        "quality": _column_or_null(columns, "quality"),
        "languages": _column_or_null(columns, "languages"),
        "version": _column_or_null(columns, "version"),
        "downloaded_at": (
            "COALESCE(downloaded_at, CURRENT_TIMESTAMP)"
            if "downloaded_at" in columns
            else "CURRENT_TIMESTAMP"
        ),
        "job_id": _column_or_null(columns, "job_id"),
        "item_key": (
            "COALESCE(NULLIF(item_key, ''), 'legacy-' || id)"
            if "item_key" in columns
            else "'legacy-' || id"
        ),
        "source_path": _legacy_source_path_expression(columns),
        "final_path": _column_or_null(columns, "final_path"),
        "metadata_json": _column_or_null(columns, "metadata_json"),
        "provenance_json": _column_or_null(columns, "provenance_json"),
    }
    connection.execute(
        f"INSERT INTO resources ({', '.join(target_columns)}) "
        f"SELECT {', '.join(expressions[name] for name in target_columns)} "
        f"FROM {legacy_table}"
    )
    connection.execute(f"DROP TABLE {legacy_table}")


def _resources_constraints_are_v5(connection: sqlite3.Connection) -> bool:
    column_info = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info(resources)").fetchall()
    }
    if not {"item_key", "source_path"} <= set(column_info):
        return False
    if not all(column_info[name][3] for name in ("item_key", "source_path")):
        return False

    unique_columns = _resource_unique_indexes(connection)
    return (
        ("job_id", "item_key") in unique_columns
        and ("title",) not in unique_columns
        and ("job_id",) not in unique_columns
    )


def _resource_unique_indexes(connection: sqlite3.Connection) -> set[tuple[str, ...]]:
    indexes: set[tuple[str, ...]] = set()
    for row in connection.execute("PRAGMA index_list(resources)").fetchall():
        if not row[2]:
            continue
        escaped = str(row[1]).replace("'", "''")
        columns = tuple(
            info[2]
            for info in connection.execute(f"PRAGMA index_info('{escaped}')").fetchall()
        )
        indexes.add(columns)
    return indexes


def _column_or_null(columns: set[str], name: str) -> str:
    return name if name in columns else "NULL"


def _legacy_source_path_expression(columns: set[str]) -> str:
    candidates = [
        name for name in ("source_path", "final_path", "title") if name in columns
    ]
    if len(candidates) == 1:
        return candidates[0]
    return f"COALESCE({', '.join(candidates)})"
