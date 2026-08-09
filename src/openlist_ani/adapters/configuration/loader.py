"""Explicit configuration loading with no import-time file access."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tomlkit import dumps as toml_dumps

from openlist_ani.logger import FATAL_LEVEL, logger

from .environment import ProxyEnvironmentApplier
from .migration import migrate_config
from .models import (
    AIConfig,
    AssistantConfig,
    BackendConfig,
    BangumiConfig,
    DownloaderConfig,
    FileRenamerConfig,
    LLMConfig,
    LogConfig,
    MetadataParserConfig,
    MetadataPipelineConfig,
    MetadataValidatorConfig,
    MikanConfig,
    NotificationConfig,
    OpenListConfig,
    ProxyConfig,
    RSSConfig,
    UserConfig,
)
from .writer import update_rss_urls


class ConfigManager:
    def __init__(self, config_path: str | Path = "config.toml") -> None:
        path = Path(config_path)
        self.config_path = path if path.is_absolute() else Path.cwd() / path
        self._config = UserConfig()
        self._load_failed = False
        self._load_from_file()

    def _load_from_file(self) -> None:
        if not self.config_path.exists():
            self.save()
            return
        try:
            migration = migrate_config(self.config_path)
            self._config = migration.config
            self._load_failed = False
            ProxyEnvironmentApplier().apply(self._config.proxy)
            if migration.migrated and migration.persisted:
                logger.info(
                    f"Configuration migrated to version "
                    f"{self._config.config_version}. Backup: {migration.backup_path}"
                )
            elif migration.migrated:
                backup_note = (
                    f" A backup was written to {migration.backup_path}."
                    if migration.backup_path
                    else " A verified backup could not be written."
                )
                logger.warning(
                    f"Configuration {self.config_path} was migrated in memory but "
                    "could not be rewritten (the file may be read-only)."
                    f"{backup_note} "
                    "The legacy file will be migrated again on the next start."
                )
        except Exception as error:
            self._load_failed = True
            logger.log(
                FATAL_LEVEL,
                f"Failed to load configuration from {self.config_path}: {error}. "
                "Application will exit.",
            )

    @property
    def data(self) -> UserConfig:
        return self._config

    def save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._config.model_dump(exclude_none=True)
            self.config_path.write_text(toml_dumps(payload), encoding="utf-8")
        except Exception as error:
            logger.error(
                f"Failed to save configuration to {self.config_path}: {error}. "
                "Runtime changes may not persist after restart."
            )

    def save_rss_urls_preserving_comments(self) -> None:
        try:
            update_rss_urls(self.config_path, list(self._config.rss.urls))
        except Exception as error:
            logger.error(
                f"Failed to update RSS URLs in {self.config_path}: {error}. "
                "Runtime changes may not persist after restart."
            )

    def add_rss_url(self, url: str) -> None:
        if url not in self._config.rss.urls:
            self._config.rss.urls.append(url)
            self.save_rss_urls_preserving_comments()

    @property
    def rss(self) -> RSSConfig:
        return self.data.rss

    @property
    def downloader(self) -> DownloaderConfig:
        return self.data.downloader

    @property
    def ai(self) -> AIConfig:
        return self.data.ai

    @property
    def metadata(self) -> MetadataPipelineConfig:
        return self.data.metadata

    @property
    def file_renamer(self) -> FileRenamerConfig:
        return self.data.file_renamer

    @property
    def openlist(self) -> OpenListConfig:
        # Direct Python callers from v1 may still mutate ``data.openlist``.
        # Config files never reach this branch because migration removes the
        # root table before validation.
        legacy = self.data.openlist
        if (
            legacy.token
            or legacy.url != "http://localhost:5244"
            or legacy.offline_download_tool != "qBittorrent"
        ):
            return legacy
        return self.data.downloader.openlist

    @property
    def llm(self) -> LLMConfig:
        return self.data.llm

    @property
    def metadata_parser(self) -> MetadataParserConfig:
        return self.data.metadata_parser

    @property
    def metadata_validator(self) -> MetadataValidatorConfig:
        return self.data.metadata_validator

    @property
    def notification(self) -> NotificationConfig:
        return self.data.notification

    @property
    def log(self) -> LogConfig:
        return self.data.log

    @property
    def assistant(self) -> AssistantConfig:
        return self.data.assistant

    @property
    def proxy(self) -> ProxyConfig:
        return self.data.proxy

    @property
    def bangumi(self) -> BangumiConfig:
        return self.data.bangumi

    @property
    def bangumi_token(self) -> str:
        return os.environ.get("BANGUMI_TOKEN", "") or self.bangumi.access_token

    @property
    def mikan(self) -> MikanConfig:
        return self.data.mikan

    @property
    def backend(self) -> BackendConfig:
        return self.data.backend

    @property
    def backend_url(self) -> str:
        return f"http://{self.backend.host}:{self.backend.port}"

    @property
    def load_failed(self) -> bool:
        return self._load_failed


_config_instance: ConfigManager | None = None


def load_config(config_path: str | Path | None = None) -> ConfigManager:
    return ConfigManager(config_path or os.environ.get("CONFIG_PATH", "config.toml"))


def get_config() -> ConfigManager:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


class LazyConfig:
    """Load process configuration on first attribute access."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_config(), name)

    def __repr__(self) -> str:
        status = "loaded" if _config_instance is not None else "unloaded"
        return f"<LazyConfig {status}>"


config = LazyConfig()

__all__ = ["ConfigManager", "config", "get_config", "load_config"]
