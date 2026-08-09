"""Narrow contracts between the core workflow and concrete adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from openlist_ani.domain import (
    DownloadJob,
    JobStep,
    MetadataDocument,
    ReleaseCandidate,
)


@dataclass(frozen=True)
class MetadataResolution:
    document: MetadataDocument
    retryable_error: str | None = None
    permanent_error: str | None = None
    degraded: bool = False


@dataclass(frozen=True)
class FeedFetchResult:
    candidates: list[ReleaseCandidate]
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass(frozen=True)
class DownloadedAsset:
    directory_path: str
    filename: str
    checkpoint: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"{self.directory_path.rstrip('/')}/{self.filename}"


@dataclass(frozen=True)
class OrganizedAsset:
    directory_path: str
    filename: str

    @property
    def path(self) -> str:
        return f"{self.directory_path.rstrip('/')}/{self.filename}"


CheckpointCallback = Callable[[dict[str, Any]], Awaitable[None]]


class MetadataPhase(StrEnum):
    TITLE = "title"
    ENRICHMENT = "enrichment"


class FeedAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def supports(self, url: str) -> bool: ...

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult: ...


class FeedResolver(Protocol):
    def feed_for(self, url: str) -> FeedAdapter: ...


class MetadataProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def phase(self) -> MetadataPhase: ...

    async def enrich_many(
        self,
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
        attempt_counts: list[int],
    ) -> list[MetadataResolution]: ...

    async def close(self) -> None: ...


class DownloadAdapter(Protocol):
    @property
    def name(self) -> str: ...

    async def start_or_resume(
        self,
        job: DownloadJob,
        target_directory_path: str,
        checkpoint_callback: CheckpointCallback,
    ) -> DownloadedAsset: ...


class Organizer(Protocol):
    async def organize(
        self,
        job: DownloadJob,
        asset: DownloadedAsset,
        target_filename: str,
    ) -> OrganizedAsset: ...


class JobRepository(Protocol):
    async def recover_interrupted(self) -> int: ...

    async def add_candidate(
        self, candidate: ReleaseCandidate
    ) -> DownloadJob | None: ...

    async def claim(self, step: JobStep, limit: int) -> list[DownloadJob]: ...

    async def claim_download_work(self, limit: int) -> list[DownloadJob]: ...

    async def save(self, job: DownloadJob) -> None: ...

    async def renew_lease(self, job: DownloadJob) -> None: ...

    async def reschedule(self, job: DownloadJob, error: str, delay: float) -> None: ...

    async def fail(self, job: DownloadJob, error: str) -> None: ...

    async def skip(self, job: DownloadJob, reason: str) -> None: ...

    async def get(self, job_id: str) -> DownloadJob | None: ...

    async def list_visible(self) -> list[DownloadJob]: ...

    async def list_active(self) -> list[DownloadJob]: ...

    async def complete_with_resource(
        self,
        job: DownloadJob,
        final_path: str,
    ) -> None: ...


class FeedStateRepository(Protocol):
    async def sync_urls(self, urls: list[str]) -> None: ...

    async def list_due(self, limit: int) -> list[str]: ...

    async def cache_headers(self, url: str) -> tuple[str | None, str | None]: ...

    async def mark_feed_success(
        self,
        url: str,
        interval_seconds: float,
        etag: str | None,
        last_modified: str | None,
    ) -> None: ...

    async def mark_feed_failure(self, url: str, error: str) -> None: ...


class LibraryRepository(Protocol):
    async def is_downloaded(self, title: str) -> bool: ...

    async def find_existing_titles(self, titles: list[str]) -> set[str]: ...

    async def find_releases_by_episodes(
        self, keys: list[tuple[str, int, int]]
    ) -> dict[tuple[str, int, int], list[dict]]: ...


class MetadataCacheRepository(Protocol):
    async def get(
        self, provider: str, cache_key: str, provider_version: str
    ) -> dict[str, Any] | None: ...

    async def put(
        self,
        provider: str,
        cache_key: str,
        provider_version: str,
        payload: dict[str, Any],
        ttl_seconds: float,
    ) -> None: ...


class NotificationSink(Protocol):
    async def send_download_complete_notification(
        self, anime_name: str, title: str
    ) -> dict[str, bool]: ...


class OutboxRepository(Protocol):
    async def recover_interrupted(self) -> int: ...

    async def claim(self, limit: int) -> list[Any]: ...

    async def delivered(self, item: Any) -> None: ...

    async def retry(self, item: Any, error: str) -> None: ...
