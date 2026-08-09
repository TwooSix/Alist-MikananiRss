from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from openlist_ani.adapters.configuration import ConfigManager
from openlist_ani.adapters.configuration import migration as migration_module
from openlist_ani.adapters.configuration.migration import migrate_config

LEGACY_CONFIG = b"""# keep me
[downloader]
provider = "openlist"

[file_renamer]
provider = "openlist"

[metadata_parser]
provider = "llm"

[metadata_validator]
provider = "tmdb"

[openlist]
url = "https://openlist.example"
token = "secret"
download_path = "/Anime"
offline_download_tool = "qBittorrent"
rename_format = "{anime_name} S{season:02d}E{episode:02d}"

[llm]
provider_type = "openai"
openai_api_key = "sk-test"
openai_base_url = "https://gateway.example/v1"
openai_model = "model-name"
tmdb_api_key = "tmdb-key"
tmdb_language = "ja-JP"

[assistant]
enabled = true
"""


def test_v1_is_backed_up_and_persistently_migrated(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    manager = ConfigManager(path)

    assert manager.load_failed is False
    backups = list(tmp_path.glob("config.toml.bak.v1.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == LEGACY_CONFIG
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# keep me\nconfig_version = 2")
    assert "[ai.sources.legacy-llm]" in content
    assert 'type = "api"' in content
    assert 'provider = "openai-compatible"' in content
    assert "[downloader.openlist]" in content
    assert "[llm]" not in content
    assert "[openlist]" not in content
    assert "[file_renamer]" not in content
    assert manager.data.metadata.pipeline == ["ai", "tmdb"]
    assert manager.data.metadata.ai_source == "legacy-llm"
    assert manager.data.assistant.backend == "legacy-llm"
    assert manager.data.downloader.download_path == "/Anime"
    assert manager.data.metadata.tmdb.language == "ja-JP"


def test_current_version_does_not_repeat_backup(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)
    ConfigManager(path)
    first = list(tmp_path.glob("config.toml.bak.v1.*"))

    ConfigManager(path)

    assert list(tmp_path.glob("config.toml.bak.v1.*")) == first


def test_concurrent_loaders_only_persist_one_migration(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    with ThreadPoolExecutor(max_workers=2) as executor:
        managers = list(executor.map(lambda _: ConfigManager(path), range(2)))

    assert all(not item.load_failed for item in managers)
    assert len(list(tmp_path.glob("config.toml.bak.v1.*"))) == 1
    assert re.search(r"(?m)^config_version = 2$", path.read_text(encoding="utf-8"))


def test_invalid_migration_keeps_original_and_backup(tmp_path):
    path = tmp_path / "config.toml"
    original = LEGACY_CONFIG.replace(
        b'openai_model = "model-name"', b'openai_model = ""'
    ).replace(b'openai_api_key = "sk-test"', b'openai_api_key = "sk-test"')
    # Invalid rename syntax is preserved into v2 and rejected before replace.
    original = original.replace(
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


def test_anthropic_v1_source_is_mapped_to_messages_provider(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """[llm]
provider_type = "anthropic"
openai_api_key = "secret-key"
openai_model = "claude-model"
""",
        encoding="utf-8",
    )

    result = migrate_config(path)

    source = result.config.ai.sources["legacy-llm"]
    assert source.provider == "anthropic-messages"
    assert source.base_url == "https://api.anthropic.com"


def test_new_fields_win_and_conflicting_legacy_source_is_not_overwritten(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """[ai.sources.legacy-llm]
type = "agent"
agent = "codex"

[metadata]
pipeline = ["regex", "tmdb"]

[downloader]
download_path = "/New"

[downloader.openlist]
token = "new-token"

[llm]
provider_type = "openai"
openai_api_key = "old-key"
openai_model = "old-model"

[openlist]
token = "old-token"
download_path = "/Old"
""",
        encoding="utf-8",
    )

    result = migrate_config(path)

    assert result.config.ai.sources["legacy-llm"].agent == "codex"
    assert result.config.ai.sources["legacy-llm-2"].api_key == "old-key"
    assert result.config.metadata.pipeline == ["regex", "tmdb"]
    assert result.config.downloader.download_path == "/New"
    assert result.config.downloader.openlist.token == "new-token"


def test_backup_failure_uses_validated_in_memory_migration(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    def fail_backup(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(migration_module, "_create_backup", fail_backup)
    result = migrate_config(path)

    assert result.migrated is True
    assert result.persisted is False
    assert result.config.config_version == 2
    assert path.read_bytes() == LEGACY_CONFIG


def test_atomic_replace_failure_does_not_modify_original(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(LEGACY_CONFIG)

    def fail_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(migration_module.os, "replace", fail_replace)
    manager = ConfigManager(path)

    assert manager.load_failed is True
    assert path.read_bytes() == LEGACY_CONFIG
    assert len(list(tmp_path.glob("config.toml.bak.v1.*"))) == 1
