"""Compile the stable public config into the core's canonical settings."""

from __future__ import annotations

from openlist_ani.application.settings import (
    CoreSettings,
    MetadataFilterSettings,
    PrioritySettings,
)
from .models import UserConfig


def compile_core_settings(config: UserConfig) -> CoreSettings:
    return CoreSettings(
        download_path=config.downloader.download_path,
        rename_format=config.downloader.rename_format,
        rss_interval_seconds=config.rss.interval_time,
        metadata_providers=config.metadata_provider_names(),
        downloader="openlist",
        organizer="openlist",
        strict_filtering=config.rss.strict,
        metadata_filter=MetadataFilterSettings(
            exclude_fansub=list(config.rss.filter.exclude_fansub),
            exclude_quality=list(config.rss.filter.exclude_quality),
            exclude_languages=list(config.rss.filter.exclude_languages),
            exclude_patterns=list(config.rss.filter.exclude_patterns),
        ),
        priority=PrioritySettings(
            field_order=list(config.rss.priority.field_order),
            fansub=list(config.rss.priority.fansub),
            languages=list(config.rss.priority.languages),
            quality=list(config.rss.priority.quality),
        ),
    )
