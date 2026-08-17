from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from openlist_ani.adapters.configuration import ConfigManager
from openlist_ani.adapters.configuration import migration as migration_module
from openlist_ani.adapters.configuration.validator import ConfigValidator

LEGACY_CONFIG = b"""# keep me
[downloader]
provider = "openlist"

[file_renamer]
provider = "openlist"

[metadata_parser]
provider = "llm"

[openlist]
url = "https://openlist.example"
token = "secret"
download_path = "/Anime"
rename_format = "{anime_name} S{season:02d}E{episode:02d}"

[llm]
provider_type = "openai"
openai_api_key = "sk-test"
openai_model = "model-name"

[assistant]
enabled = true
"""


def test_v1_config_is_backed_up_and_migrated_to_a_runnable_v2(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    manager = ConfigManager(path)

    backups = list(tmp_path.glob("config.toml.bak.v1.*"))
    assert manager.load_failed is False
    assert len(backups) == 1
    assert backups[0].read_bytes() == LEGACY_CONFIG
    assert manager.data.config_version == 2
    assert manager.data.downloader.download_path == "/Anime"
    assert manager.data.metadata.pipeline == ["ai", "tmdb"]


def test_v1_torrent_to_magnet_setting_moves_to_rss_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(
        LEGACY_CONFIG.replace(
            b'token = "secret"\n',
            b'token = "secret"\ntorrent_to_magnet = true\n',
        )
    )

    manager = ConfigManager(path)

    assert manager.load_failed is False
    assert manager.data.rss.torrent_to_magnet is True
    migrated = path.read_text(encoding="utf-8")
    assert "[rss]" in migrated
    assert "torrent_to_magnet = true" in migrated


def test_concurrent_loaders_do_not_duplicate_or_corrupt_migration(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    with ThreadPoolExecutor(max_workers=2) as executor:
        managers = list(executor.map(lambda _: ConfigManager(path), range(2)))

    assert all(not manager.load_failed for manager in managers)
    assert len(list(tmp_path.glob("config.toml.bak.v1.*"))) == 1
    assert re.search(r"(?m)^config_version = 2$", path.read_text(encoding="utf-8"))


def test_invalid_migration_preserves_the_original_and_its_backup(tmp_path):
    path = tmp_path / "config.toml"
    original = LEGACY_CONFIG.replace(
        b'rename_format = "{anime_name} S{season:02d}E{episode:02d}"',
        b'rename_format = "{unknown}"',
    )
    path.write_bytes(original)

    manager = ConfigManager(path)

    assert manager.load_failed is True
    assert path.read_bytes() == original
    backups = list(tmp_path.glob("config.toml.bak.v1.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_failed_atomic_replace_uses_validated_in_memory_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)
    monkeypatch.setattr(
        migration_module.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace failed")),
    )

    manager = ConfigManager(path)

    assert manager.load_failed is False
    assert manager.data.config_version == 2
    assert path.read_bytes() == LEGACY_CONFIG
    assert len(list(tmp_path.glob("config.toml.bak.v1.*"))) == 1


def test_enabled_v1_nested_frontend_is_migrated_to_runnable_v2(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(
        LEGACY_CONFIG.replace(
            b"enabled = true\n",
            b"enabled = true\nmax_context_tokens = 128000\n",
        )
        + b'\n[rss]\nurls = ["https://example.test/feed.xml"]\n'
        + b'\n[assistant.telegram]\nbot_token = "bot-token"\nallowed_users = [123456789]\n'
    )

    manager = ConfigManager(path)

    assert manager.load_failed is False
    assert manager.data.assistant.backend == "legacy-llm"
    assert manager.data.assistant.telegram.allowed_users == [123456789]
    assert ConfigValidator(manager.data).validate() is True
    migrated = path.read_text(encoding="utf-8")
    assert "max_context_tokens" not in migrated


def test_enabled_v1_frontend_with_empty_allowlist_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        LEGACY_CONFIG
        + b'\n[assistant.telegram]\nbot_token = "bot-token"\nallowed_users = []\n'
    )
    path.write_bytes(original)

    manager = ConfigManager(path)

    assert manager.load_failed is False
    assert manager.data.assistant.backend == "legacy-llm"
    assert manager.data.assistant.telegram.allowed_users == []
    assert ConfigValidator(manager.data).validate() is False
    assert "legacy_allow_all_users" not in path.read_text(encoding="utf-8")
    backups = list(tmp_path.glob("config.toml.bak.v1.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
