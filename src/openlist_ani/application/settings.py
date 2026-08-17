"""Canonical settings consumed by the core workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetadataFilterSettings:
    exclude_fansub: list[str] = field(default_factory=list)
    exclude_quality: list[str] = field(default_factory=list)
    exclude_languages: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrioritySettings:
    field_order: list[str] = field(
        default_factory=lambda: ["fansub", "quality", "languages"]
    )
    fansub: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    quality: list[str] = field(
        default_factory=lambda: ["2160p", "1080p", "720p", "480p", "360p"]
    )


@dataclass(frozen=True)
class CoreSettings:
    download_path: str
    rename_format: str
    rss_interval_seconds: float
    metadata_providers: tuple[str, ...]
    download_backend: str = "openlist"
    strict_filtering: bool = False
    metadata_filter: MetadataFilterSettings = field(
        default_factory=MetadataFilterSettings
    )
    priority: PrioritySettings = field(default_factory=PrioritySettings)
    feed_concurrency: int = 4
    metadata_concurrency: int = 8
    metadata_batch_size: int = 20
    download_concurrency: int = 3
    notification_concurrency: int = 2
    job_lease_seconds: float = 300.0
    job_heartbeat_seconds: float = 60.0
    shutdown_timeout_seconds: float = 30.0
