"""Linux Docker smoke test for upgrading legacy bind-mounted state."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

from packaged_upgrade_smoke import _legacy_config


def _run(command: list[str], *, capture: bool = False) -> str:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )
    return f"{result.stdout}{result.stderr}" if capture else ""


def _prepare_state(root: Path) -> bytes:
    data = root / "data"
    data.mkdir()
    config = _legacy_config(28778).encode("utf-8")
    (root / "config.toml").write_bytes(config)

    with closing(sqlite3.connect(data / "data.db")) as connection:
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
            "INSERT INTO resources "
            "(url, title, anime_name, season, episode, languages) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("magnet:docker-old", "Docker Legacy 01", "Docker Legacy", 1, 1, "简"),
        )
        connection.commit()

    task = {
        "task_id": "docker-legacy-task",
        "state": "downloaded",
        "release": {
            "title": "Docker Legacy 02",
            "download_url": "magnet:docker-task",
            "anime_name": "Docker Legacy",
            "season": 1,
            "episode": 2,
            "fansub": "Group",
            "quality": "1080p",
            "languages": ["简"],
            "version": 1,
        },
        "base_path": "/Anime",
        "downloader": {
            "downloader_type": "openlist",
            "payload": {"remote_id": "docker-remote"},
        },
        "pipeline": {
            "next_buffer": "rename",
            "downloaded_directory_path": "/Anime/Docker Legacy/Season 1",
            "downloaded_filename": "legacy.mkv",
            "renamed_path": None,
        },
        "retry": {"retry_count": 1, "max_retries": 3, "last_error": None},
        "output_path": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:01:00",
        "started_at": "2026-01-01T00:00:30",
        "completed_at": None,
        "schema_version": 1,
    }
    with closing(sqlite3.connect(data / "task_mementos.db")) as connection:
        connection.execute(
            "CREATE TABLE task_mementos "
            "(task_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO task_mementos VALUES (?, ?, ?, ?)",
            (
                task["task_id"],
                task["state"],
                task["updated_at"],
                json.dumps(task, ensure_ascii=False),
            ),
        )
        connection.commit()

    # The production image runs as UID 1000. CI-created fixtures may belong to
    # a different host UID, so grant this disposable directory write access.
    for directory in (root, data):
        directory.chmod(0o777)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o666)
    return config


def _wait_for_runtime(container: str) -> str:
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        logs = _run(["docker", "logs", container], capture=True)
        if "Durable core runtime started" in logs:
            return logs
        status = _run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container],
            capture=True,
        ).strip()
        if status == "exited":
            raise RuntimeError(f"Container exited before startup:\n{logs}")
        time.sleep(0.5)
    raise RuntimeError(f"Container did not start in time:\n{logs}")


def _run_once(image: str, root: Path, *, read_only_config: bool) -> str:
    container = f"oani-upgrade-{uuid.uuid4().hex[:12]}"
    config_mount = f"{root / 'config.toml'}:/config.toml"
    if read_only_config:
        config_mount += ":ro"
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        container,
        "--network",
        "none",
        "--env",
        "ENABLE_ASSISTANT=false",
        "--volume",
        config_mount,
        "--volume",
        f"{root / 'data'}:/data",
        image,
    ]
    try:
        _run(command)
        return _wait_for_runtime(container)
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _verify_state(root: Path, original_config: bytes) -> None:
    assert (root / "config.toml").read_bytes() == original_config
    assert not list(root.glob("config.toml.bak.*"))
    with closing(sqlite3.connect(root / "data/data.db")) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 4
        )
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE id = 'docker-legacy-task'"
            ).fetchone()[0]
            == 1
        )
    assert len(list((root / "data/backups").glob("data-v1-*.db"))) == 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            args.image,
            "-c",
            "openlist-ani-migrate --help >/dev/null 2>&1 || true; "
            "pi --version; rg --version; python --version",
        ]
    )

    with tempfile.TemporaryDirectory(prefix="oani-docker-upgrade-") as temporary:
        root = Path(temporary)
        original_config = _prepare_state(root)

        first_logs = _run_once(args.image, root, read_only_config=True)
        assert "migrated in memory" in first_logs
        assert "Database schema migrated to v4" in first_logs
        _verify_state(root, original_config)

        second_logs = _run_once(args.image, root, read_only_config=False)
        assert "migrated in memory" in second_logs
        assert "Database schema migrated to v4" not in second_logs
        _verify_state(root, original_config)

    print(f"Docker upgrade passed: image={args.image}", flush=True)


if __name__ == "__main__":
    main()
