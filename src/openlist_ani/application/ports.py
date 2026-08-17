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
class DownloadedSidecar:
    filename: str
    suffix: str


@dataclass(frozen=True)
class DownloadedAsset:
    directory_path: str
    filename: str
    sidecars: tuple[DownloadedSidecar, ...] = ()
    checkpoint: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"{self.directory_path.rstrip('/')}/{self.filename}"


@dataclass(frozen=True)
class DownloadedFile:
    """One leaf file materialized below a backend-owned download root."""

    relative_path: str
    size: int = 0


@dataclass(frozen=True)
class DownloadManifest:
    """Durable inventory returned after a backend finishes downloading."""

    root_path: str
    files: tuple[DownloadedFile, ...]
    checkpoint: dict[str, Any] = field(default_factory=dict)
    cleanup_root: str | None = None
    legacy_materialized: bool = False


@dataclass(frozen=True)
class OrganizationSidecar:
    relative_path: str
    suffix: str = ""


@dataclass(frozen=True)
class OrganizationRequest:
    item_key: str
    video_relative_path: str
    sidecars: tuple[OrganizationSidecar, ...]
    target_directory_path: str
    target_filename: str
    metadata: MetadataDocument


@dataclass(frozen=True)
class OrganizationResult:
    item_key: str
    state: str
    final_path: str | None = None
    sidecar_paths: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class CompletedResource:
    item_key: str
    source_path: str
    title: str
    metadata: MetadataDocument
    final_path: str


@dataclass(frozen=True)
class OrganizedAsset:
    directory_path: str
    filename: str
    sidecar_filenames: tuple[str, ...] = ()

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


class CandidateTransformer(Protocol):
    """Transform an eligible candidate before it enters the download queue."""

    @property
    def name(self) -> str: ...

    async def transform(self, candidate: ReleaseCandidate) -> ReleaseCandidate: ...


class DownloadAdapter(Protocol):
    @property
    def name(self) -> str: ...

    async def start_or_resume(
        self,
        job: DownloadJob,
        checkpoint_callback: CheckpointCallback,
    ) -> DownloadManifest: ...


class Organizer(Protocol):
    @property
    def backend_name(self) -> str: ...

    async def organize(
        self,
        job: DownloadJob,
        manifest: DownloadManifest,
        requests: tuple[OrganizationRequest, ...],
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> tuple[OrganizationResult, ...]: ...


BackendHealthCheck = Callable[[], Awaitable[bool]]
BackendClose = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class DownloadBackendBundle:
    name: str
    downloader: DownloadAdapter
    organizer: Organizer
    health_check: BackendHealthCheck | None = None
    close: BackendClose | None = None


class DownloadBackendResolver(Protocol):
    def download_backend(self, name: str) -> DownloadBackendBundle: ...


class JobRepository(Protocol):
    async def recover_interrupted(self) -> int: ...

    async def add_candidate(
        self,
        candidate: ReleaseCandidate,
        *,
        initial_artifact: dict[str, Any] | None = None,
        initial_metadata: MetadataDocument | None = None,
    ) -> DownloadJob | None: ...

    async def claim(self, step: JobStep, limit: int) -> list[DownloadJob]: ...

    async def claim_download_work(self, limit: int) -> list[DownloadJob]: ...

    async def save(self, job: DownloadJob) -> None: ...

    async def renew_lease(self, job: DownloadJob) -> None: ...

    async def reschedule(self, job: DownloadJob, error: str, delay: float) -> None: ...

    async def fail(self, job: DownloadJob, error: str) -> None: ...

    async def skip(self, job: DownloadJob, reason: str) -> None: ...

    async def get(self, job_id: str) -> DownloadJob | None: ...

    async def find_history(
        self, download_url: str, title: str
    ) -> list[DownloadJob]: ...

    async def list_visible(self) -> list[DownloadJob]: ...

    async def list_active(self) -> list[DownloadJob]: ...

    async def complete_with_resources(
        self,
        job: DownloadJob,
        resources: tuple[CompletedResource, ...],
        summary: dict[str, Any] | None = None,
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
    def targets(self) -> tuple[NotificationTarget, ...]: ...

    def format_download_batches(
        self,
        target_key: str,
        items: list[Any],
    ) -> list[NotificationBatch]: ...

    async def send_to_target(self, target_key: str, message: str) -> bool: ...


@dataclass(frozen=True)
class NotificationTarget:
    key: str
    message_limit: int


@dataclass(frozen=True)
class NotificationBatch:
    message: str
    items: tuple[Any, ...]


class OutboxRepository(Protocol):
    async def recover_interrupted(self) -> int: ...

    async def claim(self, limit: int) -> list[Any]: ...

    async def delivered(self, item: Any) -> None: ...

    async def retry(self, item: Any, error: str) -> None: ...

    async def initialize_targets(self, target_keys: tuple[str, ...]) -> None: ...

    async def claim_due(self, target_key: str, batch_interval: float) -> list[Any]: ...

    async def next_due_delay(
        self, target_keys: tuple[str, ...], batch_interval: float
    ) -> float | None: ...

    async def delivery_succeeded(self, items: list[Any]) -> None: ...

    async def delivery_retry(self, items: list[Any], error: str) -> None: ...
