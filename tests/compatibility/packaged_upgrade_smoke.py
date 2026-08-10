"""Black-box upgrade smoke test for a released wheel.

The normal mode builds the legacy baseline, creates state through the installed
legacy package, performs an ordinary package upgrade (without force reinstall),
then validates and starts the installed current package. Hidden phase commands
run inside the temporary virtual environment so imports always come from the
wheel under test rather than this source checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path

ACTIVE_STATES = (
    "pending",
    "downloading",
    "downloaded",
    "renaming",
    "renamed",
    "notifying",
)
LEGACY_BASELINE = "5458661923335a43b427e022e2fc5a33dce349e3"
RESOURCE_COLUMNS = (
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
)


def _legacy_config(port: int) -> str:
    return f"""# preserved production comment
[backend]
host = "127.0.0.1"
port = {port}

[rss]
urls = ["http://127.0.0.1:9/feed.xml"]
interval_time = 3600
strict = false

[rss.filter]
exclude_patterns = ["SP\\\\d+"]
exclude_fansub = ["Blocked Group"]
exclude_quality = ["480p"]
exclude_languages = ["繁"]

[rss.priority]
field_order = ["fansub", "quality", "languages"]
fansub = ["Preferred Group"]
languages = ["简", "日"]
quality = ["2160p", "1080p", "720p"]

[proxy]
http = ""
https = ""

[downloader]
provider = "openlist"

[file_renamer]
provider = "openlist"

[metadata_parser]
provider = "regex"

[metadata_validator]
provider = "none"

[openlist]
url = "http://127.0.0.1:9"
token = "legacy-openlist-secret"
download_path = "/Anime/番剧"
offline_download_tool = "qBittorrent"
rename_format = "{{anime_name}} S{{season:02d}}E{{episode:02d}} {{languages}}"

[llm]
provider_type = "openai"
openai_api_key = "legacy-ai-secret"
openai_base_url = "https://api.example.test/v1"
openai_model = "legacy-model"
tmdb_api_key = "legacy-tmdb-secret"
tmdb_language = "ja-JP"

[notification]
enabled = false
batch_interval = 0.0

[assistant]
enabled = true
max_context_tokens = 64000
session_compact_threshold = 48000
skills_dir = "skills"
data_dir = "data/assistant"

[assistant.telegram]
enabled = true
bot_token = "legacy-telegram-secret"
allowed_users = [123456789]

[assistant.wechat]
enabled = false
account_id = ""
token = ""
base_url = "https://ilinkai.weixin.qq.com"
home_channel = ""
dm_policy = "open"
allowed_users = []

[assistant.feishu]
enabled = false
app_id = ""
app_secret = ""
domain = "feishu"
connection_mode = "websocket"
webhook_host = "127.0.0.1"
webhook_port = 8765
webhook_path = "/feishu/webhook"
bot_open_id = ""
require_mention = true
state_dir = "data/messaging"
allowed_users = []

[assistant.auto_dream]
enabled = true
min_hours = 12.0
min_sessions = 3

[bangumi]
access_token = "legacy-bangumi-secret"

[mikan]
username = "legacy-user"
password = "legacy-password"

[log]
level = "INFO"
rotation = "00:00"
retention = "1 week"
"""


async def _create_legacy_library() -> None:
    from openlist_ani.adapters.outbound.persistence import (
        SqliteAnimeLibraryRepository,
    )
    from openlist_ani.domain.anime_release import (
        AnimeRelease,
        LanguageType,
        VideoQuality,
    )

    repository = SqliteAnimeLibraryRepository()
    await repository.init()
    await repository.add_release(
        AnimeRelease(
            title="历史番剧 01",
            download_url="magnet:?xt=urn:btih:legacy-resource-1",
            anime_name="历史番剧",
            season=1,
            episode=1,
            fansub="Preferred Group",
            quality=VideoQuality.Q1080P,
            languages=[LanguageType.CHS, LanguageType.JP],
            version=1,
        )
    )
    await repository.add_release(
        AnimeRelease(
            title="Legacy Unknown 02",
            download_url="magnet:?xt=urn:btih:legacy-resource-2",
            anime_name=None,
            season=None,
            episode=None,
            quality=VideoQuality.UNKNOWN,
            languages=[LanguageType.UNKNOWN],
        )
    )


def _prepare_legacy_state(runtime: Path, port: int) -> None:
    os.chdir(runtime)
    config_bytes = _legacy_config(port).encode("utf-8")
    (runtime / "config.toml").write_bytes(config_bytes)

    from openlist_ani.adapters.outbound.configuration import (
        ConfigManager,
        ConfigValidator,
    )
    from openlist_ani.adapters.outbound.persistence import SqliteTaskMementoStore
    from openlist_ani.domain.anime_release import (
        AnimeRelease,
        LanguageType,
        VideoQuality,
    )
    from openlist_ani.domain.download_task.downloader import DownloaderMemento
    from openlist_ani.domain.download_task.memento import (
        PipelineMemento,
        RetryMemento,
        TaskMemento,
    )
    from openlist_ani.domain.download_task.task import DownloadState

    manager = ConfigManager("config.toml")
    assert not manager.load_failed
    assert ConfigValidator(manager.data, manager.load_failed).validate()

    asyncio.run(_create_legacy_library())
    store = SqliteTaskMementoStore(runtime / "data/task_mementos.db")
    languages = (
        LanguageType.CHS,
        LanguageType.CHT,
        LanguageType.JP,
        LanguageType.ENG,
        LanguageType.UNKNOWN,
        LanguageType.CHS,
    )
    qualities = (
        VideoQuality.Q2160P,
        VideoQuality.Q1080P,
        VideoQuality.Q720P,
        VideoQuality.Q480P,
        VideoQuality.Q360P,
        VideoQuality.UNKNOWN,
    )
    for index, state_name in enumerate(ACTIVE_STATES, start=1):
        state = DownloadState(state_name)
        directory = f"/Anime/番剧/Show {index}/Season 1"
        filename = f"legacy-{index:02d}.mkv"
        renamed = f"{directory}/Show {index} S01E{index:02d}.mkv"
        pipeline = PipelineMemento()
        output_path = None
        if state_name in {"downloaded", "renaming", "renamed", "notifying"}:
            pipeline.next_buffer = "rename"
            pipeline.downloaded_directory_path = directory
            pipeline.downloaded_filename = filename
        if state_name in {"renamed", "notifying"}:
            pipeline.next_buffer = "notify"
            pipeline.renamed_path = renamed
            output_path = renamed
        store.save(
            TaskMemento(
                task_id=f"legacy-{state_name}",
                state=state,
                release=AnimeRelease(
                    title=f"Legacy Task {index:02d}",
                    download_url=f"magnet:?xt=urn:btih:legacy-task-{index}",
                    anime_name=f"Show {index}",
                    season=1,
                    episode=index,
                    fansub="Preferred Group",
                    quality=qualities[index - 1],
                    languages=[languages[index - 1]],
                    version=2 if index == 6 else 1,
                ),
                base_path="/Anime/番剧",
                downloader=DownloaderMemento(
                    downloader_type="openlist",
                    payload={"remote_id": f"remote-{index}", "progress": index * 10},
                ),
                pipeline=pipeline,
                retry=RetryMemento(
                    retry_count=index - 1,
                    max_retries=9,
                    last_error="transient failure" if index % 2 == 0 else None,
                ),
                output_path=output_path,
                created_at=f"2026-01-{index:02d}T00:00:00",
                updated_at=f"2026-01-{index:02d}T00:01:00",
                started_at=f"2026-01-{index:02d}T00:00:30",
            )
        )

    with closing(sqlite3.connect(runtime / "data/data.db")) as connection:
        connection.row_factory = sqlite3.Row
        resources = [
            dict(row)
            for row in connection.execute(
                f"SELECT {', '.join(RESOURCE_COLUMNS)} FROM resources ORDER BY id"
            ).fetchall()
        ]
    with closing(sqlite3.connect(runtime / "data/task_mementos.db")) as connection:
        tasks = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload FROM task_mementos ORDER BY task_id"
            ).fetchall()
        ]
    (runtime / "legacy-state-manifest.json").write_text(
        json.dumps({"resources": resources, "tasks": tasks}, ensure_ascii=False),
        encoding="utf-8",
    )


def _verify_current_state(runtime: Path) -> None:
    os.chdir(runtime)
    from openlist_ani.adapters.configuration import ConfigManager
    from openlist_ani.adapters.configuration.validator import ConfigValidator
    from openlist_ani.adapters.persistence import LegacyMigrationRunner

    manager = ConfigManager("config.toml")
    assert not manager.load_failed
    assert ConfigValidator(manager.data, manager.load_failed).validate()
    assert manager.data.config_version == 2
    assert manager.data.downloader.download_path == "/Anime/番剧"
    assert manager.data.downloader.openlist.token == "legacy-openlist-secret"
    assert manager.data.metadata.pipeline == ["regex"]
    assert manager.data.metadata.tmdb.api_key == "legacy-tmdb-secret"
    assert manager.data.metadata.tmdb.language == "ja-JP"
    assert manager.data.assistant.backend == "legacy-llm"
    assert manager.data.assistant.telegram.allowed_users == [123456789]
    assert manager.data.bangumi.access_token == "legacy-bangumi-secret"
    assert manager.data.mikan.password == "legacy-password"

    # Idempotency must hold through both the console entry point and API runner.
    LegacyMigrationRunner().run()
    LegacyMigrationRunner().run()

    expected_steps = {
        "legacy-pending": "download",
        "legacy-downloading": "download",
        "legacy-downloaded": "organize",
        "legacy-renaming": "organize",
        "legacy-renamed": "finalize",
        "legacy-notifying": "finalize",
    }
    manifest = json.loads(
        (runtime / "legacy-state-manifest.json").read_text(encoding="utf-8")
    )
    legacy_tasks = {task["task_id"]: task for task in manifest["tasks"]}
    with closing(sqlite3.connect(runtime / "data/data.db")) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 5
        )
        resources = [
            dict(row)
            for row in connection.execute(
                f"SELECT {', '.join(RESOURCE_COLUMNS)} FROM resources ORDER BY id"
            ).fetchall()
        ]
        assert resources == manifest["resources"]
        jobs = connection.execute(
            "SELECT id, source_name, source_url, title, download_url, "
            "candidate_json, metadata_json, status, step, downloader_name, "
            "checkpoint_version, checkpoint_json, artifact_json, attempt_count, "
            "next_attempt_at, last_error, output_path, created_at, updated_at, "
            "started_at, completed_at, lease_token, lease_expires_at "
            "FROM jobs ORDER BY id"
        ).fetchall()
        assert len(jobs) == len(ACTIVE_STATES)
        for row in jobs:
            legacy = legacy_tasks[row["id"]]
            release = legacy["release"]
            index = ACTIVE_STATES.index(row["id"].removeprefix("legacy-")) + 1
            assert row["status"] == "pending"
            assert row["step"] == expected_steps[row["id"]]
            assert row["source_name"] == "legacy"
            assert row["source_url"] == ""
            assert row["title"] == release["title"]
            assert row["download_url"] == release["download_url"]
            candidate = json.loads(row["candidate_json"])
            assert candidate["title"] == release["title"]
            assert candidate["download_url"] == release["download_url"]
            values = json.loads(row["metadata_json"])["values"]
            for field in (
                "anime_name",
                "season",
                "episode",
                "fansub",
                "quality",
                "languages",
                "version",
            ):
                expected = release[field]
                if field == "quality" and expected == "unknown":
                    expected = None
                if field == "languages":
                    expected = [item for item in expected if item != "未知"]
                assert values[field] == expected, (row["id"], field)
            evidence = json.loads(row["metadata_json"])["evidence"]
            assert all(
                evidence[field][0]["source"] == "legacy"
                for field in (
                    "anime_name",
                    "season",
                    "episode",
                    "fansub",
                    "quality",
                    "languages",
                    "version",
                )
            )
            assert row["downloader_name"] == legacy["downloader"]["downloader_type"]
            assert row["checkpoint_version"] == 1
            assert json.loads(row["checkpoint_json"]) == legacy["downloader"]["payload"]
            artifact = json.loads(row["artifact_json"])
            assert artifact["base_path"] == legacy["base_path"]
            pipeline = legacy["pipeline"]
            if pipeline.get("downloaded_directory_path"):
                assert (
                    artifact["directory_path"] == pipeline["downloaded_directory_path"]
                )
                assert artifact["filename"] == pipeline["downloaded_filename"]
            if pipeline.get("renamed_path"):
                assert artifact["renamed_path"] == pipeline["renamed_path"]
            assert row["attempt_count"] == index - 1
            assert row["last_error"] == legacy["retry"]["last_error"]
            assert row["output_path"] == legacy["output_path"]
            assert row["created_at"] == legacy["created_at"]
            assert row["updated_at"] == legacy["updated_at"]
            assert row["started_at"] == legacy["started_at"]
            assert row["completed_at"] == legacy["completed_at"]
            assert row["next_attempt_at"] is None
            assert row["lease_token"] is None
            assert row["lease_expires_at"] is None

    assert len(list(runtime.glob("config.toml.bak.v1.*"))) == 1
    database_backups = list((runtime / "data/backups").glob("data-v1-*.db"))
    assert len(database_backups) == 1
    with closing(sqlite3.connect(database_backups[0])) as connection:
        connection.row_factory = sqlite3.Row
        backup_resources = [
            dict(row)
            for row in connection.execute(
                f"SELECT {', '.join(RESOURCE_COLUMNS)} FROM resources ORDER BY id"
            ).fetchall()
        ]
    assert backup_resources == manifest["resources"]
    assert not (runtime / "data/.data.db.migrating").exists()


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_script(venv: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    directory = "Scripts" if os.name == "nt" else "bin"
    return venv / directory / f"{name}{suffix}"


def _single_wheel(directory: Path) -> Path:
    wheels = list(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one wheel in {directory}, found {len(wheels)}")
    return wheels[0]


def _verify_wheel_contents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        unsafe = [
            name
            for name in archive.namelist()
            if name.endswith(".log")
            or Path(name).suffix in {".db", ".sqlite", ".tmp", ".pyc", ".pyo"}
            or "__pycache__" in Path(name).parts
            or "logs" in Path(name).parts
        ]
    if unsafe:
        sample = ", ".join(unsafe[:5])
        raise RuntimeError(f"Wheel contains runtime artifacts: {sample}")


def _installed_version(python: Path) -> str:
    result = subprocess.run(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('openlist-ani'))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise RuntimeError(f"Could not identify wheel metadata in {wheel}")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
    for line in metadata.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise RuntimeError(f"Wheel version is missing from {wheel}")


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_backend(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    url = f"http://127.0.0.1:{port}/health/live"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Backend exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"Backend did not become live at {url}")


def _start_installed_backend(venv: Path, runtime: Path, port: int) -> None:
    executable = _venv_script(venv, "openlist-ani")
    log_path = runtime / "packaged-backend-smoke.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [str(executable)],
            cwd=runtime,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_backend(port, process)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def _orchestrate(args: argparse.Namespace) -> None:
    repository = Path(args.repository).resolve()
    wheel_path = Path(args.wheel).resolve()
    current_wheel = _single_wheel(wheel_path) if wheel_path.is_dir() else wheel_path
    _verify_wheel_contents(current_wheel)
    script = Path(__file__).resolve()
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the packaged upgrade smoke test")

    with tempfile.TemporaryDirectory(prefix="oani-packaged-upgrade-") as temporary:
        root = Path(temporary)
        legacy_source = root / "legacy-source"
        legacy_dist = root / "legacy-dist"
        runtime = root / "runtime"
        venv = root / "venv"
        legacy_source.mkdir()
        legacy_dist.mkdir()
        (runtime / "data").mkdir(parents=True)

        archive = root / "legacy.tar"
        with archive.open("wb") as handle:
            subprocess.run(
                ["git", "archive", args.baseline],
                cwd=repository,
                stdout=handle,
                check=True,
            )
        shutil.unpack_archive(archive, legacy_source, format="tar")

        _run(
            [
                uv,
                "build",
                "--project",
                str(legacy_source),
                "--out-dir",
                str(legacy_dist),
            ]
        )
        legacy_wheel = _single_wheel(legacy_dist)
        _run([uv, "venv", "--python", args.python, str(venv)])
        python = _venv_python(venv)

        # Install current dependencies once, then swap only the project wheel.
        # This keeps the test fast on Windows where the legacy ripgrep package
        # otherwise needs a Rust source build.
        _run([uv, "pip", "install", "--python", str(python), str(current_wheel)])
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--reinstall",
                "--no-deps",
                str(legacy_wheel),
            ]
        )

        port = args.port or _available_port()
        _run(
            [str(python), str(script), "_prepare", str(runtime), str(port)], cwd=runtime
        )
        original_config = (runtime / "config.toml").read_bytes()

        # Deliberately omit --force-reinstall: a real upgrade must be selected
        # by its higher package version.
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--upgrade",
                str(current_wheel),
            ]
        )
        _run([str(_venv_script(venv, "openlist-ani-migrate"))], cwd=runtime)
        _run([str(python), str(script), "_verify", str(runtime)], cwd=runtime)

        backups = list(runtime.glob("config.toml.bak.v1.*"))
        assert len(backups) == 1 and backups[0].read_bytes() == original_config
        current_version = _installed_version(python)
        expected_version = args.expected_version or _wheel_version(current_wheel)
        assert current_version == expected_version, (current_version, expected_version)
        _start_installed_backend(venv, runtime, port)
        print(
            f"Packaged upgrade passed: baseline={args.baseline}, "
            f"version={current_version}, python={args.python}",
            flush=True,
        )


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "_prepare":
        _prepare_legacy_state(Path(sys.argv[2]).resolve(), int(sys.argv[3]))
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "_verify":
        _verify_current_state(Path(sys.argv[2]).resolve())
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--repository", default=Path(__file__).parents[2])
    parser.add_argument("--baseline", default=LEGACY_BASELINE)
    parser.add_argument("--python", default="3.11")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--expected-version", default="")
    _orchestrate(parser.parse_args())


if __name__ == "__main__":
    main()
