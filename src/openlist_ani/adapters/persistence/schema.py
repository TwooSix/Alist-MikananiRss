"""SQLite schema for the durable core runtime."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS resources (
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
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    job_id TEXT,
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
}


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _add_columns(connection, "resources", RESOURCE_ADDITIVE_COLUMNS)
    _add_columns(connection, "jobs", JOB_ADDITIVE_COLUMNS)
    _add_columns(connection, "notification_outbox", OUTBOX_ADDITIVE_COLUMNS)
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_job_id "
        "ON resources(job_id) WHERE job_id IS NOT NULL"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_lease " "ON jobs(status, lease_expires_at)"
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
