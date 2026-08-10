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
    final_paths: tuple[str, ...] = ()
    warning_count: int = 0
    items: tuple[DownloadItemView, ...] = ()


@dataclass(frozen=True)
class DownloadItemView:
    """Public, backend-neutral state for one file discovered in a download."""

    item_key: str
    state: str
    source_path: str | None = None
    final_path: str | None = None
    error: str | None = None
    anime_name: str | None = None
    season: int | None = None
    episode: int | None = None


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
    metadata = _download_view_metadata(job)
    release = _release_view(
        job.candidate.title,
        job.candidate.download_url,
        metadata,
    )
    items = _download_item_views(job)
    final_paths = _download_final_paths(job, items)
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
        final_paths=final_paths,
        warning_count=_download_warning_count(job, items),
        items=items,
    )


def _download_view_metadata(job: DownloadJob) -> ReleaseMetadata:
    """Return parent-level metadata without leaking a collection episode."""

    if not _is_collection_job(job):
        return (
            job.metadata.values
            if job.metadata.values.minimum_complete()
            else job.candidate.source_metadata
        )

    context = ReleaseMetadata.from_dict(
        job.artifact.get("collection_context")
        if isinstance(job.artifact.get("collection_context"), dict)
        else None
    )
    parent = _merge_collection_parent_metadata(
        context,
        job.candidate.source_metadata,
    )
    if item_metadata := _first_collection_item_metadata(job):
        parent = _merge_collection_parent_metadata(item_metadata, parent)
    return parent


def _is_collection_job(job: DownloadJob) -> bool:
    summary = job.artifact.get("summary")
    return bool(
        job.artifact.get("collection_hint")
        or isinstance(job.artifact.get("collection_context"), dict)
        or (isinstance(summary, dict) and summary.get("collection"))
    )


def _first_collection_item_metadata(job: DownloadJob) -> ReleaseMetadata | None:
    successful_keys = {
        str(item.get("item_key"))
        for item in _mapping_list(job.artifact.get("organization_results"))
        if item.get("item_key") and item.get("state") == "completed"
    }
    candidates: list[tuple[tuple[int, int, str, str], ReleaseMetadata]] = []
    for item in _mapping_list(job.artifact.get("resolved_items")):
        item_key = str(item.get("item_key") or "")
        if successful_keys and item_key not in successful_keys:
            continue
        values = _metadata_values(item.get("metadata"))
        if not values:
            continue
        metadata = ReleaseMetadata.from_dict(values)
        if (
            not metadata.anime_name
            or metadata.season is None
            or metadata.season <= 0
            or metadata.episode is None
            or metadata.episode <= 0
        ):
            continue
        candidates.append(
            (
                (
                    metadata.season,
                    metadata.episode,
                    str(item.get("source_path") or ""),
                    item_key,
                ),
                metadata,
            )
        )
    return (
        min(candidates, default=None, key=lambda candidate: candidate[0])[1]
        if candidates
        else None
    )


def _merge_collection_parent_metadata(
    primary: ReleaseMetadata,
    fallback: ReleaseMetadata,
) -> ReleaseMetadata:
    """Merge safe collection fields while deliberately clearing episode."""

    return ReleaseMetadata(
        anime_name=primary.anime_name or fallback.anime_name,
        season=primary.season if primary.season is not None else fallback.season,
        episode=None,
        year=primary.year if primary.year is not None else fallback.year,
        fansub=primary.fansub or fallback.fansub,
        quality=primary.quality or fallback.quality,
        languages=list(primary.languages or fallback.languages),
        version=(primary.version if primary.version is not None else fallback.version),
        external_ids={**fallback.external_ids, **primary.external_ids},
        extra={**fallback.extra, **primary.extra},
    )


def _download_item_views(job: DownloadJob) -> tuple[DownloadItemView, ...]:
    resolved_items = _mapping_list(job.artifact.get("resolved_items"))
    organization_results = _mapping_list(job.artifact.get("organization_results"))
    summary = job.artifact.get("summary")
    summary_items = (
        _mapping_list(summary.get("items")) if isinstance(summary, dict) else []
    )

    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    organization_keys: set[str] = set()
    for source in (resolved_items, organization_results):
        for index, item in enumerate(source):
            key = str(item.get("item_key") or item.get("source_path") or index)
            if source is organization_results:
                organization_keys.add(key)
            if key not in merged:
                order.append(key)
                merged[key] = {"item_key": key}
            merged[key].update(item)
    for index, item in enumerate(summary_items):
        key = str(item.get("item_key") or item.get("source_path") or index)
        if key not in merged:
            order.append(key)
            merged[key] = {"item_key": key, **item}
            continue
        for name, value in item.items():
            if (
                name not in merged[key]
                or merged[key][name] is None
                or (name == "state" and key not in organization_keys)
            ):
                merged[key][name] = value

    views: list[DownloadItemView] = []
    for key in order:
        item = merged[key]
        values = _metadata_values(item.get("metadata"))
        views.append(
            DownloadItemView(
                item_key=key,
                state=str(item.get("state") or "pending"),
                source_path=_optional_string(
                    item.get("source_path") or item.get("video_relative_path")
                ),
                final_path=_optional_string(item.get("final_path")),
                error=_optional_string(item.get("error")),
                anime_name=_optional_string(
                    item.get("anime_name") or values.get("anime_name")
                ),
                season=_optional_int(item.get("season", values.get("season"))),
                episode=_optional_int(item.get("episode", values.get("episode"))),
            )
        )

    # Old single-file jobs have no item records. Expose their completed artifact as
    # one compatibility item without changing any of the legacy response fields.
    if not views and job.output_path:
        source_path = job.artifact.get("filename")
        views.append(
            DownloadItemView(
                item_key="legacy-single-resource",
                state="completed",
                source_path=_optional_string(source_path),
                final_path=job.output_path,
                anime_name=job.metadata.values.anime_name,
                season=job.metadata.values.season,
                episode=job.metadata.values.episode,
            )
        )
    return tuple(views)


def _download_final_paths(
    job: DownloadJob,
    items: tuple[DownloadItemView, ...],
) -> tuple[str, ...]:
    raw_paths = job.artifact.get("final_paths")
    paths = (
        [str(path) for path in raw_paths if isinstance(path, str) and path]
        if isinstance(raw_paths, (list, tuple))
        else []
    )
    if not paths:
        paths = [
            item.final_path
            for item in items
            if item.state == "completed" and item.final_path
        ]
    if job.output_path:
        paths = [job.output_path, *(path for path in paths if path != job.output_path)]
    return tuple(dict.fromkeys(paths))


def _download_warning_count(
    job: DownloadJob,
    items: tuple[DownloadItemView, ...],
) -> int:
    summary = job.artifact.get("summary")
    if isinstance(summary, dict):
        value = _optional_int(summary.get("warning_count"))
        if value is not None:
            return max(0, value)
    return sum(item.state in {"failed", "skipped"} for item in items)


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _metadata_values(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("values")
    return nested if isinstance(nested, dict) else value


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
