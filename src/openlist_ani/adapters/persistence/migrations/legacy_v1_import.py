"""Strict conversion of v1 task mementos into durable jobs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openlist_ani.domain import MetadataDocument, MetadataEvidence, ReleaseMetadata
from openlist_ani.domain.release import ReleaseCandidate


@dataclass(frozen=True)
class LegacyImportReport:
    discovered: int
    inserted: int
    preserved: int
    task_ids: tuple[str, ...]


@dataclass(frozen=True)
class _LegacyTask:
    task_id: str
    state: str
    release: dict[str, Any]
    base_path: str
    downloader: dict[str, Any] | None
    pipeline: dict[str, Any]
    retry: dict[str, Any]
    output_path: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


def import_legacy_tasks(
    connection: sqlite3.Connection,
    task_database: Path,
    task_json: Path,
) -> LegacyImportReport:
    payloads = _sqlite_payloads(task_database)
    if payloads is None:
        payloads = _json_payloads(task_json)

    inserted = 0
    preserved = 0
    task_ids: list[str] = []
    for index, payload in enumerate(payloads):
        try:
            task = _decode_legacy_task(payload)
            row = _task_row(task)
            task_ids.append(task.task_id)
            existing = connection.execute(
                "SELECT id, source_key FROM jobs WHERE id = ? OR source_key = ?",
                (task.task_id, row["source_key"]),
            ).fetchone()
            if existing is not None:
                if existing[0] != task.task_id:
                    raise ValueError(
                        "source identity collides with existing job " f"{existing[0]}"
                    )
                preserved += 1
                continue
            connection.execute(
                """
                INSERT INTO jobs (
                    id, source_key, source_name, source_url, title, download_url,
                    candidate_json, metadata_json, status, step, downloader_name,
                    checkpoint_version, checkpoint_json, artifact_json,
                    attempt_count, last_error, output_path,
                    created_at, updated_at, started_at, completed_at
                ) VALUES (
                    :id, :source_key, :source_name, :source_url, :title,
                    :download_url, :candidate_json, :metadata_json, :status,
                    :step, :downloader_name, 1, :checkpoint_json, :artifact_json,
                    :attempt_count, :last_error, :output_path,
                    :created_at, :updated_at, :started_at, :completed_at
                )
                """,
                row,
            )
            inserted += 1
        except Exception as error:
            task_ref = payload.get("task_id") if isinstance(payload, dict) else None
            raise RuntimeError(
                "Legacy task migration failed at "
                f"index={index}, task_id={task_ref or '<unknown>'}: {error}"
            ) from error
    return LegacyImportReport(
        discovered=len(payloads),
        inserted=inserted,
        preserved=preserved,
        task_ids=tuple(task_ids),
    )


def _sqlite_payloads(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path)) as source:
            rows = source.execute(
                "SELECT task_id, payload FROM task_mementos"
            ).fetchall()
        payloads = []
        for task_id, raw_payload in rows:
            payload = json.loads(raw_payload)
            if isinstance(payload, dict):
                payload = dict(payload)
                payload.setdefault("task_id", task_id)
            payloads.append(payload)
        return payloads
    except Exception as error:
        raise RuntimeError(
            f"Cannot read legacy task database {path}: {error}"
        ) from error


def _json_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        tasks = value.get("tasks") if isinstance(value, dict) else None
        if tasks is None:
            raise ValueError("expected an object containing a 'tasks' list")
        if not isinstance(tasks, list):
            raise ValueError("'tasks' must be a list")
        return list(tasks)
    except Exception as error:
        raise RuntimeError(f"Cannot read legacy task JSON {path}: {error}") from error


def _decode_legacy_task(payload: dict[str, Any]) -> _LegacyTask:
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported memento schema: {payload.get('schema_version')}")
    release = payload.get("release")
    if not isinstance(release, dict):
        raise ValueError("legacy task release must be an object")
    downloader = payload.get("downloader")
    if downloader is not None and not isinstance(downloader, dict):
        raise ValueError("legacy task downloader must be an object")
    now = datetime.now().isoformat()
    return _LegacyTask(
        task_id=str(payload["task_id"]),
        state=str(payload["state"]),
        release=dict(release),
        base_path=str(payload["base_path"]),
        downloader=dict(downloader) if downloader else None,
        pipeline=dict(payload.get("pipeline") or {}),
        retry=dict(payload.get("retry") or {}),
        output_path=payload.get("output_path"),
        created_at=str(payload.get("created_at") or now),
        updated_at=str(payload.get("updated_at") or now),
        started_at=payload.get("started_at"),
        completed_at=payload.get("completed_at"),
    )


def _task_row(task: _LegacyTask) -> dict[str, Any]:
    release = task.release
    candidate = ReleaseCandidate.create(
        source_name="legacy",
        source_url="",
        title=str(release["title"]),
        download_url=str(release["download_url"]),
    )
    metadata_values = ReleaseMetadata.from_dict(
        {
            "anime_name": release.get("anime_name"),
            "season": release.get("season"),
            "episode": release.get("episode"),
            "fansub": release.get("fansub"),
            "quality": release.get("quality"),
            "languages": release.get("languages") or [],
            "version": release.get("version") or 1,
        }
    )
    document = MetadataDocument(values=metadata_values)
    for field_name in (
        "anime_name",
        "season",
        "episode",
        "fansub",
        "quality",
        "languages",
        "version",
    ):
        document.evidence[field_name] = [MetadataEvidence(source="legacy")]

    status, step = _map_state(task.state)
    artifact = {"base_path": task.base_path}
    if task.pipeline.get("downloaded_directory_path"):
        artifact["directory_path"] = task.pipeline["downloaded_directory_path"]
    if task.pipeline.get("downloaded_filename"):
        artifact["filename"] = task.pipeline["downloaded_filename"]
    if task.pipeline.get("renamed_path"):
        artifact["renamed_path"] = task.pipeline["renamed_path"]

    checkpoint = task.downloader.get("payload", {}) if task.downloader else {}
    downloader_name = (
        str(task.downloader.get("downloader_type") or "openlist")
        if task.downloader
        else "openlist"
    )
    return {
        "id": task.task_id,
        "source_key": candidate.source_key,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "title": candidate.title,
        "download_url": candidate.download_url,
        "candidate_json": json.dumps(_candidate_dict(candidate), ensure_ascii=False),
        "metadata_json": json.dumps(document.to_dict(), ensure_ascii=False),
        "status": status,
        "step": step,
        "downloader_name": downloader_name,
        "checkpoint_json": json.dumps(checkpoint, ensure_ascii=False),
        "artifact_json": json.dumps(artifact, ensure_ascii=False),
        "attempt_count": int(task.retry.get("retry_count", 0)),
        "last_error": task.retry.get("last_error"),
        "output_path": task.output_path,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


def _map_state(state: str) -> tuple[str, str]:
    mapping = {
        "pending": ("pending", "download"),
        "downloading": ("pending", "download"),
        "downloaded": ("pending", "organize"),
        "renaming": ("pending", "organize"),
        "renamed": ("pending", "finalize"),
        "notifying": ("pending", "finalize"),
        # Terminal rows are not normally persisted by v1, but accepting the
        # known values makes hand-crafted/older stores deterministic.
        "failed": ("failed", "download"),
        "cancelled": ("cancelled", "download"),
        "completed": ("completed", "finalize"),
    }
    try:
        return mapping[state]
    except KeyError as error:
        raise ValueError(f"Unsupported legacy task state: {state!r}") from error


def _candidate_dict(candidate: ReleaseCandidate) -> dict[str, Any]:
    return {
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "title": candidate.title,
        "download_url": candidate.download_url,
        "source_key": candidate.source_key,
        "guid": candidate.guid,
        "source_metadata": candidate.source_metadata.to_dict(),
    }
