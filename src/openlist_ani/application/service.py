"""Application facade shared by HTTP and the durable workers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from openlist_ani.application.ports import JobRepository, LibraryRepository
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import (
    DownloadJob,
    LanguageType,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)
from openlist_ani.logger import logger


@dataclass(frozen=True)
class CreateDownloadOutcome:
    success: bool
    message: str
    task: DownloadView | None = None


@dataclass(frozen=True)
class ReleaseView:
    title: str
    download_url: str
    anime_name: str | None = None
    season: int | None = None
    episode: int | None = None
    fansub: str | None = None
    quality: VideoQuality | None = None
    languages: tuple[LanguageType, ...] = ()
    version: int = 1


@dataclass(frozen=True)
class DownloadView(ReleaseView):
    id: str = ""
    state: str = "pending"
    error_message: str | None = None
    retry_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    save_path: str = ""
    final_path: str | None = None


@dataclass(frozen=True)
class ParseRSSOutcome:
    success: bool
    message: str
    total: int = 0
    entries: list[ReleaseView] | None = None


class CoreApplicationService:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        library: LibraryRepository,
        registry,
        settings: CoreSettings,
        config_manager,
        feed_scheduler,
        metadata_available,
        resolve_magnet_func: Callable[..., Awaitable[Any]],
        resolve_torrent_func: Callable[..., Awaitable[Any]],
        health_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self._jobs = jobs
        self._library = library
        self._registry = registry
        self._settings = settings
        self._config = config_manager
        self._feed_scheduler = feed_scheduler
        self._metadata_available = metadata_available
        self._resolve_magnet = resolve_magnet_func
        self._resolve_torrent = resolve_torrent_func
        self._health_provider = health_provider

    def health(self) -> dict[str, Any]:
        return self._health_provider()

    def add_rss_url(self, url: str) -> tuple[bool, str, list[str]]:
        current = list(self._config.rss.urls)
        if url in current:
            return False, f"URL already exists: {url}", current
        self._config.add_rss_url(url)
        self._feed_scheduler.wake()
        updated = list(self._config.rss.urls)
        return True, f"RSS URL added successfully: {url}", updated

    async def create_download(
        self, download_url: str, title: str
    ) -> CreateDownloadOutcome:
        if await self._library.is_downloaded(title):
            return CreateDownloadOutcome(False, f"Already downloaded: {title}")
        for active in await self._jobs.list_active():
            if active.candidate.download_url == download_url:
                return CreateDownloadOutcome(False, f"Already downloading: {title}")

        candidate = ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title=title,
            download_url=download_url,
        )
        job = await self._jobs.add_candidate(candidate)
        if job is None:
            return CreateDownloadOutcome(False, f"Already submitted: {title}")
        self._metadata_available.set()
        logger.info(f"Download job created: job_id={job.id}; title={title}")
        return CreateDownloadOutcome(
            True,
            f"Download started: {title}",
            _job_to_view(job, self._settings.download_path),
        )

    async def list_downloads(self) -> list[DownloadView]:
        return [
            _job_to_view(job, self._settings.download_path)
            for job in await self._jobs.list_visible()
            if job.api_state() not in {"completed", "cancelled"}
        ]

    async def get_download(self, task_id: str) -> DownloadView | None:
        job = await self._jobs.get(task_id)
        return _job_to_view(job, self._settings.download_path) if job else None

    async def parse_rss(self, url: str, limit: int | None = None) -> ParseRSSOutcome:
        if not url:
            return ParseRSSOutcome(False, "'url' is required.")
        try:
            adapter = self._registry.feed_for(url)
            result = await adapter.fetch(url)
            candidates = result.candidates
            total = len(candidates)
            if limit is not None and limit > 0:
                candidates = candidates[:limit]
            releases = [
                _release_view(
                    candidate.title,
                    candidate.download_url,
                    candidate.source_metadata,
                )
                for candidate in candidates
            ]
            message = (
                f"Parsed {len(releases)} of {total} entries"
                if total > len(releases)
                else f"Parsed {len(releases)} entries"
            )
            return ParseRSSOutcome(True, message, total, releases)
        except Exception as error:
            return ParseRSSOutcome(False, f"Failed to fetch RSS: {error}")

    async def resolve_magnet(self, magnet: str, metadata_timeout: int = 30) -> Any:
        return await self._resolve_magnet(magnet, metadata_timeout=metadata_timeout)

    async def resolve_torrent(self, url: str) -> Any:
        return await self._resolve_torrent(url)


def _job_to_view(job: DownloadJob, default_base_path: str) -> DownloadView:
    metadata = (
        job.metadata.values
        if job.metadata.values.minimum_complete()
        else job.candidate.source_metadata
    )
    release = _release_view(
        job.candidate.title,
        job.candidate.download_url,
        metadata,
    )
    return DownloadView(
        **release.__dict__,
        id=job.id,
        state=job.api_state(),
        error_message=job.last_error,
        retry_count=job.attempt_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        save_path=job.artifact.get("base_path", default_base_path),
        final_path=job.output_path,
    )


def _release_view(
    title: str, download_url: str, metadata: ReleaseMetadata
) -> ReleaseView:
    return ReleaseView(
        title=title,
        download_url=download_url,
        anime_name=metadata.anime_name,
        season=metadata.season,
        episode=metadata.episode,
        fansub=metadata.fansub,
        quality=metadata.quality,
        languages=tuple(metadata.languages),
        version=metadata.version or 1,
    )
