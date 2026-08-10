"""Gating tests for user configuration behavior and failure handling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest
from pydantic import ValidationError

from openlist_ani.adapters.configuration import (
    ConfigManager,
    ConfigValidator,
    compile_core_settings,
    validate_core_settings,
)
from openlist_ani.adapters.configuration.models import (
    BotConfig,
    DownloaderConfig,
    MetadataFilterConfig,
    NotificationConfig,
    OpenListConfig,
    UserConfig,
)


def _valid_config(**overrides) -> UserConfig:
    payload = {
        "rss": {"urls": ["https://example.test/feed.xml"]},
        "downloader": {
            "openlist": {
                "url": "http://localhost:5244",
                "token": "token",
            }
        },
    }
    payload.update(overrides)
    return UserConfig.model_validate(payload)


def test_minimal_user_config_is_ready_to_run():
    config = _valid_config()

    assert config.metadata_provider_names() == ("regex", "tmdb")
    assert config.rss.torrent_to_magnet is False
    assert ConfigValidator(config).validate() is True


def test_core_settings_select_one_bound_download_backend():
    settings = compile_core_settings(_valid_config())

    assert settings.download_backend == "openlist"
    assert not hasattr(settings, "downloader")
    assert not hasattr(settings, "organizer")

    with pytest.raises(ValueError, match="A download backend is required"):
        validate_core_settings(replace(settings, download_backend=" "))


def test_torrent_to_magnet_can_be_enabled_in_rss_config():
    config = _valid_config(
        rss={
            "urls": ["https://example.test/feed.xml"],
            "torrent_to_magnet": True,
        }
    )

    assert config.rss.torrent_to_magnet is True


def test_metadata_pipeline_rejects_unrunnable_configurations():
    for pipeline in (["tmdb"], ["tmdb", "ai"], ["regex", "unknown"]):
        with pytest.raises(ValidationError):
            UserConfig.model_validate({"metadata": {"pipeline": pipeline}})


def test_config_file_round_trip_and_rss_update(tmp_path):
    config_path = tmp_path / "config.toml"
    manager = ConfigManager(config_path)

    manager.add_rss_url("https://example.test/feed.xml")
    manager.add_rss_url("https://example.test/feed.xml")

    reloaded = ConfigManager(config_path)
    assert reloaded.rss.urls == ["https://example.test/feed.xml"]


def test_corrupt_config_fails_closed(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("not valid [[[ toml", encoding="utf-8")

    manager = ConfigManager(config_path)

    assert manager.load_failed is True
    assert ConfigValidator(manager.data, manager.load_failed).validate() is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"rss": {"urls": ["https://example.test/feed.xml"]}},
        {
            "rss": {"urls": ["https://example.test/feed.xml"]},
            "downloader": {"openlist": {"url": "", "token": "token"}},
        },
    ],
    ids=["missing-rss", "missing-token", "missing-url"],
)
def test_missing_required_runtime_settings_are_rejected(payload):
    assert ConfigValidator(UserConfig.model_validate(payload)).validate() is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"notification": {"enabled": True, "bots": []}},
        {
            "notification": {
                "enabled": True,
                "bots": [{"type": "telegram", "enabled": False}],
            }
        },
        {"assistant": {"enabled": True}},
    ],
    ids=[
        "notification-without-channel",
        "notification-with-disabled-channel",
        "assistant-without-frontend",
    ],
)
def test_enabled_optional_features_require_a_usable_configuration(overrides):
    assert ConfigValidator(_valid_config(**overrides)).validate() is False


@pytest.mark.parametrize(
    "build",
    [
        lambda: OpenListConfig(offline_download_tool=""),
        lambda: DownloaderConfig(rename_format="{unsupported}"),
        lambda: MetadataFilterConfig(exclude_patterns=["[invalid"]),
        lambda: NotificationConfig(batch_interval=-1),
        lambda: UserConfig.model_validate({"metdata": {"pipeline": ["regex"]}}),
        lambda: BotConfig(type="telegram", config={"bot_tokn": "typo"}),
    ],
    ids=[
        "empty-tool",
        "bad-rename-field",
        "bad-filter-regex",
        "negative-batch",
        "unknown-config-key",
        "unknown-notification-key",
    ],
)
def test_invalid_user_input_is_rejected_by_the_config_model(
    build: Callable[[], object],
):
    with pytest.raises(ValidationError):
        build()
