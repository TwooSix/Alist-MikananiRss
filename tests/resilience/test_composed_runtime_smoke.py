import asyncio
import sqlite3
from contextlib import closing

import pytest

from openlist_ani.adapters.configuration import ConfigManager, compile_core_settings
from openlist_ani.adapters.persistence import LegacyMigrationRunner
from openlist_ani.bootstrap.backend import _compose_runtime


@pytest.mark.asyncio
async def test_composed_runtime_starts_ready_and_releases_database(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[rss]
urls = []

[metadata_parser]
provider = "regex"

[metadata_validator]
provider = "none"

[openlist]
url = "http://127.0.0.1:1"
token = ""
download_path = "/anime"
offline_download_tool = "qBittorrent"
rename_format = "{anime_name} S{season:02d}E{episode:02d}"
""".strip(),
        encoding="utf-8",
    )
    config = ConfigManager(str(config_path))
    settings = compile_core_settings(config.data)
    LegacyMigrationRunner().run()

    assembly = await _compose_runtime(config, settings)
    await assembly.runtime.start()
    try:
        await asyncio.sleep(0)

        health = assembly.runtime.health()
        assert health["status"] == "ready"
        assert health["ready"] is True
        assert health["workers"] == {"running": 6, "expected": 6}
    finally:
        await assembly.runtime.stop()

    with closing(sqlite3.connect(tmp_path / "data" / "data.db")) as connection:
        connection.execute("BEGIN EXCLUSIVE")
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        connection.rollback()
