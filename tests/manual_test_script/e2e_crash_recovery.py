"""Real OpenList crash-recovery E2E driver.

This script copies the supplied configuration and legacy database into a
temporary directory.  It then runs one real RSS release through multiple child
processes, terminating each process at a durable or remote side-effect
boundary.  The original files are never modified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import posixpath
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import aiohttp
import tomlkit

from openlist_ani.adapters.configuration import (
    ConfigManager,
    compile_core_settings,
    validate_core_settings,
)
from openlist_ani.adapters.feed_sources import (
    AniApiFeedAdapter,
    CommonFeedAdapter,
    MikanFeedAdapter,
)
from openlist_ani.adapters.persistence import LegacyMigrationRunner
from openlist_ani.adapters.download_backends.openlist.workflow import (
    OpenListDownloadWorkflow,
)
from openlist_ani.application.ports import MetadataPhase
from openlist_ani.bootstrap.backend import _compose_runtime
from openlist_ani.domain import JobStatus
from openlist_ani.adapters.download_backends.openlist import (
    OpenListClient,
    OpenListHealthCheck,
)
from openlist_ani.adapters.torrent import resolve_magnet, resolve_torrent


@dataclass(frozen=True)
class PreparedRun:
    root: Path
    config_path: Path
    database_path: Path
    download_root: str
    selected_title: str
    selected_size: int
    source_resource_count: int


STAGES = (
    "rss_after_fetch",
    "metadata_before_provider",
    "submit_after_remote",
    "submitted_checkpoint",
    "download_done_checkpoint",
    "transfer_done_checkpoint",
    "file_detected_checkpoint",
    "file_resolved_checkpoint",
    "move_after_remote",
    "organize_after_rename",
    "finalize_before_commit",
    "notify_before_send",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--database", type=Path, default=Path("data/data.db"))
    parser.add_argument("--tool", default="qBittorrent")
    parser.add_argument("--target-contains", default="")
    parser.add_argument("--stage-timeout", type=float, default=4 * 60 * 60)
    parser.add_argument("--final-timeout", type=float, default=4 * 60 * 60)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", default="", help=argparse.SUPPRESS)
    parser.add_argument("--run-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--download-root", default="", help=argparse.SUPPRESS)
    parser.add_argument("--marker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--job-id", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def _join_path(parent: str, child: str) -> str:
    parent = (parent or "/").rstrip("/") or "/"
    return f"/{child}" if parent == "/" else f"{parent}/{child}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _candidate_size(candidate) -> int | None:
    if candidate.download_url.startswith("magnet:"):
        result = await resolve_magnet(candidate.download_url, metadata_timeout=60)
    else:
        result = await resolve_torrent(candidate.download_url)
    if not result.success or not result.files:
        return None
    size = sum(max(0, item.size) for item in result.files)
    return size or None


def _database_snapshot(database_path: Path, job_id: str = "") -> dict[str, Any]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, Any] = {
            "resources": connection.execute(
                "SELECT COUNT(*) FROM resources"
            ).fetchone()[0],
            "jobs": connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        }
        if job_id:
            job = connection.execute(
                "SELECT status, step, attempt_count, last_error, output_path, "
                "checkpoint_json, artifact_json FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            outbox = connection.execute(
                "SELECT status, attempt_count, last_error, delivered_at "
                "FROM notification_outbox WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            resource = connection.execute(
                "SELECT final_path, metadata_json, provenance_json "
                "FROM resources WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            result.update(
                {
                    "job": dict(job) if job else None,
                    "outbox": dict(outbox) if outbox else None,
                    "resource": dict(resource) if resource else None,
                }
            )
            if job:
                result["checkpoint_state"] = json.loads(
                    job["checkpoint_json"] or "{}"
                ).get("workflow_state")
        return result
    finally:
        connection.close()


async def _prepare_run(args: argparse.Namespace) -> PreparedRun:
    source_config = args.config.resolve()
    source_database = args.database.resolve()
    root = Path(tempfile.mkdtemp(prefix="openlist-ani-crash-e2e-"))
    config_path = root / "config.toml"
    database_path = root / "data" / "data.db"
    database_path.parent.mkdir(parents=True)
    shutil.copy2(source_config, config_path)
    shutil.copy2(source_database, database_path)

    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    document["openlist"]["offline_download_tool"] = args.tool
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")

    LegacyMigrationRunner(
        database_path,
        root / "data" / "task_mementos.db",
        root / "data" / "task_mementos.json",
    ).run()
    config = ConfigManager(str(config_path))
    settings = compile_core_settings(config.data)
    validate_core_settings(settings)

    client = OpenListClient(config.openlist.url, config.openlist.token)
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=True
    )
    try:
        health = await OpenListHealthCheck(
            client=client,
            base_url=config.openlist.url,
            offline_download_tool=config.openlist.offline_download_tool,
        ).validate()
        if not health:
            raise RuntimeError(f"OpenList tool is not healthy: {args.tool}")

        adapters = (
            MikanFeedAdapter(session),
            AniApiFeedAdapter(session),
            CommonFeedAdapter(session),
        )
        feed_url = config.rss.urls[0]
        adapter = next(item for item in adapters if item.supports(feed_url))
        fetched = await adapter.fetch(feed_url)
        connection = sqlite3.connect(database_path)
        try:
            source_resource_count = connection.execute(
                "SELECT COUNT(*) FROM resources"
            ).fetchone()[0]
            existing_titles = {
                row[0] for row in connection.execute("SELECT title FROM resources")
            }
            eligible = [
                item
                for item in fetched.candidates
                if item.title in existing_titles
                and (
                    not args.target_contains
                    or args.target_contains.casefold() in item.title.casefold()
                )
            ]
            if not eligible:
                raise RuntimeError("No RSS release matches an existing resource")
            semaphore = asyncio.Semaphore(4)

            async def sized(candidate):
                async with semaphore:
                    return candidate, await _candidate_size(candidate)

            sized_candidates = await asyncio.gather(*(sized(item) for item in eligible))
            resolved_candidates = [
                (candidate, size)
                for candidate, size in sized_candidates
                if size is not None
            ]
            if not resolved_candidates:
                raise RuntimeError("No matching RSS torrent has readable size metadata")
            selected, selected_size = min(
                resolved_candidates,
                key=lambda item: (item[1], item[0].title),
            )
            removed = connection.execute(
                "DELETE FROM resources WHERE title = ?", (selected.title,)
            ).rowcount
            if removed != 1:
                raise RuntimeError(
                    "The selected RSS title must match exactly one legacy resource; "
                    f"removed={removed}"
                )
            connection.commit()
        finally:
            connection.close()

        suffix = f"_openlist_ani_crash_e2e_{uuid.uuid4().hex[:8]}"
        download_root = _join_path(config.openlist.download_path, suffix)
        parent_entries = await client.list_files(config.openlist.download_path)
        if parent_entries is None:
            raise RuntimeError("Cannot list the configured OpenList download root")
        if any(item.name == suffix for item in parent_entries):
            raise RuntimeError(f"Remote test root already exists: {download_root}")

        return PreparedRun(
            root=root,
            config_path=config_path,
            database_path=database_path,
            download_root=download_root,
            selected_title=selected.title,
            selected_size=selected_size,
            source_resource_count=source_resource_count,
        )
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    finally:
        await session.close()
        await client.close()


def _write_marker(marker: Path, payload: dict[str, Any]) -> None:
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, marker)


async def _pause_at(marker: Path, stage: str, **details: Any) -> None:
    _write_marker(marker, {"stage": stage, **details})
    await asyncio.sleep(3600)


def _install_child_hook(
    mode: str,
    assembly: Any,
    marker: Path,
    job_id: str,
) -> None:
    if mode == "rss_after_fetch":
        feed_url = assembly.application._config.rss.urls[0]
        adapter = assembly.application._registry.feed_for(feed_url)
        original = adapter.fetch

        async def fetch(*args: Any, **kwargs: Any):
            result = await original(*args, **kwargs)
            await _pause_at(marker, mode, observed=len(result.candidates))
            return result

        adapter.fetch = fetch
        return

    if mode == "metadata_before_provider":
        provider = next(
            item
            for item in assembly.runtime.metadata_worker._providers
            if item.phase == MetadataPhase.TITLE
        )
        original = provider.enrich_many

        async def enrich_many(*args: Any, **kwargs: Any):
            await _pause_at(marker, mode, batch_size=len(args[0]))
            return await original(*args, **kwargs)

        provider.enrich_many = enrich_many
        return

    if mode == "submit_after_remote":
        original = assembly.openlist_client.add_offline_download

        async def add_offline_download(*args: Any, **kwargs: Any):
            tasks = await original(*args, **kwargs)
            await _pause_at(
                marker,
                mode,
                remote_task_ids=[item.id for item in tasks or []],
            )
            return tasks

        assembly.openlist_client.add_offline_download = add_offline_download
        return

    workflow_hooks = {
        "submitted_checkpoint": "_wait_download_complete",
        "download_done_checkpoint": "_wait_transfer_complete",
        "transfer_done_checkpoint": "_detect_file",
        "file_detected_checkpoint": "_resolve_file_to_move",
        "file_resolved_checkpoint": "_prepare_move",
    }
    if mode in workflow_hooks:
        method_name = workflow_hooks[mode]
        original = getattr(OpenListDownloadWorkflow, method_name)

        async def workflow_step(self: Any, task: Any):
            await _pause_at(
                marker, mode, workflow_state=task.downloader_data.get("workflow_state")
            )
            return await original(self, task)

        setattr(OpenListDownloadWorkflow, method_name, workflow_step)
        return

    if mode == "move_after_remote":
        original = assembly.openlist_client.move_file

        async def move_file(*args: Any, **kwargs: Any):
            moved = await original(*args, **kwargs)
            if moved:
                await _pause_at(marker, mode)
            return moved

        assembly.openlist_client.move_file = move_file
        return

    if mode == "organize_after_rename":
        original = assembly.openlist_client.rename_file

        async def rename_file(full_path: str, new_name: str):
            renamed = await original(full_path, new_name)
            if renamed and "/.oani-download-tmp/" not in full_path:
                await _pause_at(marker, mode, target_name=new_name)
            return renamed

        assembly.openlist_client.rename_file = rename_file
        return

    if mode == "finalize_before_commit":
        repository = assembly.application._jobs
        original = repository.complete_with_resource

        async def complete_with_resource(job: Any, *args: Any, **kwargs: Any):
            if not job_id or job.id == job_id:
                await _pause_at(marker, mode, selected_job=job.id)
            return await original(job, *args, **kwargs)

        repository.complete_with_resource = complete_with_resource
        return

    if mode == "notify_before_send":
        sink = assembly.runtime.notification_worker._sink
        if sink is None:
            raise RuntimeError("Notification sink is not configured")
        original = sink.send_download_complete_notification

        async def send_download_complete_notification(*args: Any, **kwargs: Any):
            await _pause_at(marker, mode)
            return await original(*args, **kwargs)

        sink.send_download_complete_notification = send_download_complete_notification


async def _child_main(args: argparse.Namespace) -> None:
    if not args.run_root or not args.marker:
        raise ValueError("child run requires --run-root and --marker")
    config_path = args.run_root / "config.toml"
    config = ConfigManager(str(config_path))
    settings = replace(
        compile_core_settings(config.data),
        download_path=args.download_root,
        download_concurrency=1,
        notification_concurrency=1,
    )
    validate_core_settings(settings)
    assembly = await _compose_runtime(config, settings)
    _install_child_hook(args.mode, assembly, args.marker, args.job_id)
    try:
        await assembly.runtime.start()
        if args.mode == "final":
            deadline = time.monotonic() + args.final_timeout
            while time.monotonic() < deadline:
                job = await assembly.application._jobs.get(args.job_id)
                snapshot = _database_snapshot(
                    args.run_root / "data" / "data.db", args.job_id
                )
                outbox = snapshot.get("outbox")
                if (
                    job is not None
                    and job.status == JobStatus.COMPLETED
                    and outbox
                    and outbox["status"] == "delivered"
                ):
                    _write_marker(args.marker, {"stage": "final", "complete": True})
                    return
                if job is not None and job.status in {
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                    JobStatus.SKIPPED,
                }:
                    raise RuntimeError(
                        f"Job terminated during final run: {job.status}: {job.last_error}"
                    )
                await asyncio.sleep(2)
            raise TimeoutError(
                f"Final child did not complete within {args.final_timeout} seconds"
            )
        await asyncio.Future()
    finally:
        await assembly.runtime.stop()


def _start_child(
    args: argparse.Namespace,
    prepared: PreparedRun,
    mode: str,
    marker: Path,
    job_id: str,
) -> tuple[subprocess.Popen[bytes], Any]:
    log_path = prepared.root / f"{mode}.log"
    log = log_path.open("wb")
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--mode",
        mode,
        "--run-root",
        str(prepared.root),
        "--download-root",
        prepared.download_root,
        "--marker",
        str(marker),
        "--job-id",
        job_id,
        "--final-timeout",
        str(args.final_timeout),
    ]
    environment = dict(os.environ)
    environment["CONFIG_PATH"] = str(prepared.config_path)
    process = subprocess.Popen(
        command,
        cwd=prepared.root,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return process, log


def _wait_for_marker(
    process: subprocess.Popen[bytes],
    marker: Path,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return json.loads(marker.read_text(encoding="utf-8"))
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Child exited before marker: code={return_code}")
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {marker.name}")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Force-stop the test child and any interpreter launcher descendants."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)


def _selected_job_id(prepared: PreparedRun) -> str:
    connection = sqlite3.connect(prepared.database_path)
    try:
        row = connection.execute(
            "SELECT id FROM jobs WHERE title = ?", (prepared.selected_title,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Selected RSS job was not persisted")
        return str(row[0])
    finally:
        connection.close()


def _skip_unselected_jobs(prepared: PreparedRun, job_id: str) -> None:
    connection = sqlite3.connect(prepared.database_path)
    try:
        connection.execute(
            """
            UPDATE jobs SET status = 'skipped', last_error = 'e2e_not_selected',
                completed_at = datetime('now'), lease_token = NULL,
                lease_expires_at = NULL
            WHERE id != ? AND status NOT IN ('completed', 'failed', 'cancelled', 'skipped')
            """,
            (job_id,),
        )
        connection.commit()
    finally:
        connection.close()


async def _remote_snapshot(prepared: PreparedRun, job_id: str) -> dict[str, Any]:
    config = ConfigManager(str(prepared.config_path))
    client = OpenListClient(config.openlist.url, config.openlist.token)
    try:
        undone = await client.get_offline_download_undone()
        done = await client.get_offline_download_done()
        matching = [
            item
            for item in [*(undone or []), *(done or [])]
            if job_id in f"{item.name or ''} {item.status or ''}"
            or prepared.download_root in f"{item.name or ''} {item.status or ''}"
        ]
        return {
            "matching_offline_tasks": len(matching),
            "task_ids": sorted({item.id for item in matching}),
            "states": [item.state.name if item.state else None for item in matching],
        }
    finally:
        await client.close()


async def _verify_final(
    prepared: PreparedRun,
    job_id: str,
) -> dict[str, Any]:
    snapshot = _database_snapshot(prepared.database_path, job_id)
    resource = snapshot.get("resource")
    if not resource or not resource.get("final_path"):
        raise RuntimeError("Final resource row or path is missing")
    final_path = resource["final_path"]
    config = ConfigManager(str(prepared.config_path))
    client = OpenListClient(config.openlist.url, config.openlist.token)
    try:
        entries = await client.list_files(posixpath.dirname(final_path))
        matching_files = [
            item
            for item in entries or []
            if item.name == posixpath.basename(final_path)
        ]
        temp_entries = await client.list_files(
            _join_path(prepared.download_root, ".oani-download-tmp")
        )
        remote = await _remote_snapshot(prepared, job_id)
    finally:
        await client.close()

    job = snapshot.get("job") or {}
    outbox = snapshot.get("outbox") or {}
    result = {
        "job_status": job.get("status"),
        "job_step": job.get("step"),
        "job_error": job.get("last_error"),
        "checkpoint_state": snapshot.get("checkpoint_state"),
        "resource_count": snapshot["resources"],
        "resource_count_restored": (
            snapshot["resources"] == prepared.source_resource_count
        ),
        "resource_inserted": resource is not None,
        "metadata_saved": bool(resource and resource.get("metadata_json")),
        "provenance_saved": bool(resource and resource.get("provenance_json")),
        "outbox_status": outbox.get("status"),
        "notification_attempts": outbox.get("attempt_count"),
        "notification_error": outbox.get("last_error"),
        "final_path": final_path,
        "remote_file_count": len(matching_files),
        "remote_file_size": matching_files[0].size if matching_files else None,
        "expected_file_size": prepared.selected_size,
        "temp_job_present": any(item.name == job_id for item in (temp_entries or [])),
        **remote,
    }
    required = (
        result["job_status"] == "completed"
        and result["checkpoint_state"] == "done"
        and result["resource_count_restored"]
        and result["outbox_status"] == "delivered"
        and result["remote_file_count"] == 1
        and result["remote_file_size"] == result["expected_file_size"]
        and not result["temp_job_present"]
        and result["matching_offline_tasks"] == 1
    )
    if not required:
        raise RuntimeError(f"Final verification failed: {result}")
    return result


def _kill_at_stage(
    args: argparse.Namespace,
    prepared: PreparedRun,
    mode: str,
    job_id: str,
) -> dict[str, Any]:
    marker = prepared.root / f"{mode}.marker.json"
    marker.unlink(missing_ok=True)
    process, log = _start_child(args, prepared, mode, marker, job_id)
    try:
        payload = _wait_for_marker(process, marker, args.stage_timeout)
        _terminate_process_tree(process)
        return payload
    except BaseException:
        _terminate_process_tree(process)
        log.flush()
        log_path = Path(log.name)
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        if tail:
            print(f"CHILD_LOG_TAIL[{mode}]={tail}", flush=True)
        raise
    finally:
        log.close()


def _run_final_child(
    args: argparse.Namespace,
    prepared: PreparedRun,
    job_id: str,
) -> dict[str, Any]:
    marker = prepared.root / "final.marker.json"
    marker.unlink(missing_ok=True)
    process, log = _start_child(args, prepared, "final", marker, job_id)
    try:
        payload = _wait_for_marker(process, marker, args.final_timeout)
        process.wait(timeout=60)
        if process.returncode != 0:
            raise RuntimeError(f"Final child failed: code={process.returncode}")
        return payload
    except BaseException:
        _terminate_process_tree(process)
        log.flush()
        log_path = Path(log.name)
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        if tail:
            print(f"CHILD_LOG_TAIL[final]={tail}", flush=True)
        raise
    finally:
        log.close()


def _controller_main(args: argparse.Namespace) -> None:
    prepared: PreparedRun | None = None
    source_config = args.config.resolve()
    source_database = args.database.resolve()
    original_hashes = {
        "config": _sha256(source_config),
        "database": _sha256(source_database),
    }
    try:
        prepared = asyncio.run(_prepare_run(args))
        print(
            "PREPARED="
            + json.dumps(
                {
                    **asdict(prepared),
                    "root": str(prepared.root),
                    "config_path": str(prepared.config_path),
                    "database_path": str(prepared.database_path),
                    "tool": args.tool,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        job_id = ""
        observations: list[dict[str, Any]] = []
        for mode in STAGES:
            payload = _kill_at_stage(args, prepared, mode, job_id)
            if mode == "metadata_before_provider":
                job_id = _selected_job_id(prepared)
                _skip_unselected_jobs(prepared, job_id)
            snapshot = _database_snapshot(prepared.database_path, job_id)
            observation = {
                "mode": mode,
                "marker": payload,
                "database": snapshot,
            }
            if mode == "submit_after_remote":
                observation["remote"] = asyncio.run(_remote_snapshot(prepared, job_id))
            observations.append(observation)
            print(
                "STAGE_KILLED=" + json.dumps(observation, ensure_ascii=False),
                flush=True,
            )

        final_marker = _run_final_child(args, prepared, job_id)
        result = asyncio.run(_verify_final(prepared, job_id))
        print(
            "CRASH_E2E_SUMMARY="
            + json.dumps(
                {
                    "tool": args.tool,
                    "job_id": job_id,
                    "download_root": prepared.download_root,
                    "selected_title": prepared.selected_title,
                    "killed_stages": list(STAGES),
                    "final_marker": final_marker,
                    "result": result,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        if prepared is not None:
            shutil.rmtree(prepared.root, ignore_errors=True)
            if prepared.root.exists():
                raise RuntimeError(
                    f"Local credential copy was not removed: {prepared.root}"
                )
        final_hashes = {
            "config": _sha256(source_config),
            "database": _sha256(source_database),
        }
        if final_hashes != original_hashes:
            raise RuntimeError(
                f"Source files changed during E2E: before={original_hashes}, "
                f"after={final_hashes}"
            )
        print(
            "E2E_CLEANUP="
            + json.dumps(
                {
                    "local_credential_copies": 0,
                    "orphan_child_processes": 0,
                    "source_hashes_unchanged": True,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parsed = _parse_args()
    if parsed.child:
        asyncio.run(_child_main(parsed))
    else:
        _controller_main(parsed)
