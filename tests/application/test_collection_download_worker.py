"""Focused contract tests for manifest-based collection download jobs."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import pytest

from openlist_ani.application.download_worker import DownloadWorkerPool
from openlist_ani.application.organization import OrganizationCleanupPending
from openlist_ani.application.ports import (
    DownloadBackendBundle,
    DownloadManifest,
    DownloadedFile,
    MetadataResolution,
    OrganizationRequest,
    OrganizationResult,
)
from openlist_ani.application.settings import CoreSettings, MetadataFilterSettings
from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    JobStep,
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)


class FakeJobRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[JobStep, JobStatus]] = []
        self.completed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []
        self.rescheduled: list[tuple[str, float]] = []
        self.active: list[DownloadJob] = []

    async def save(self, job: DownloadJob) -> None:
        self.saved.append((job.step, job.status))

    async def list_active(self) -> list[DownloadJob]:
        return list(self.active)

    async def complete_with_resources(
        self,
        job: DownloadJob,
        resources: tuple[Any, ...],
        summary: dict[str, Any] | None = None,
    ) -> None:
        job.status = JobStatus.COMPLETED
        job.output_path = resources[0].final_path if resources else None
        self.completed.append((resources, dict(summary or {})))

    async def fail(self, job: DownloadJob, error: str) -> None:
        job.status = JobStatus.FAILED
        job.last_error = error
        self.failed.append(error)

    async def skip(self, job: DownloadJob, reason: str) -> None:
        job.status = JobStatus.SKIPPED
        job.last_error = reason
        self.skipped.append(reason)

    async def reschedule(self, job: DownloadJob, error: str, delay: float) -> None:
        job.status = JobStatus.RETRY_WAIT
        job.last_error = error
        self.rescheduled.append((error, delay))


class FakeLibraryRepository:
    def __init__(
        self,
        records: dict[tuple[str, int, int], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.records = records or {}
        self.requested_keys: list[list[tuple[str, int, int]]] = []

    async def find_releases_by_episodes(
        self, keys: list[tuple[str, int, int]]
    ) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
        self.requested_keys.append(list(keys))
        return {key: list(self.records.get(key, [])) for key in keys}


class FakeDownloader:
    def __init__(self, name: str, manifest: DownloadManifest) -> None:
        self.name = name
        self.manifest = manifest
        self.jobs: list[str] = []

    async def start_or_resume(self, job, checkpoint_callback):
        self.jobs.append(job.id)
        await checkpoint_callback({"backend": self.name, "downloaded": True})
        return self.manifest


class TerminalFailDownloader(FakeDownloader):
    async def start_or_resume(self, job, checkpoint_callback):
        self.jobs.append(job.id)
        await checkpoint_callback(
            {
                "workflow_state": "transfer_done",
                "temp_path": f"/library/.oani-download-tmp/{job.id}",
            }
        )
        raise RuntimeError("inventory timed out")


@dataclass(frozen=True)
class OrganizerCall:
    job_id: str
    manifest: DownloadManifest
    requests: tuple[OrganizationRequest, ...]


class FakeOrganizer:
    def __init__(
        self,
        backend_name: str,
        states: dict[str, tuple[str, str | None]] | None = None,
    ) -> None:
        self.backend_name = backend_name
        self.states = states or {}
        self.calls: list[OrganizerCall] = []

    async def organize(
        self, job, manifest, requests, checkpoint_callback=None
    ) -> tuple[OrganizationResult, ...]:
        self.calls.append(OrganizerCall(job.id, manifest, requests))
        if checkpoint_callback is not None:
            await checkpoint_callback(
                {"planned": [request.item_key for request in requests]}
            )
        output = []
        for request in requests:
            state, error = self.states.get(
                request.video_relative_path, ("completed", None)
            )
            final_path = None
            if state == "completed":
                final_path = (
                    f"{request.target_directory_path.rstrip('/')}"
                    f"/{request.target_filename}"
                )
            output.append(
                OrganizationResult(
                    item_key=request.item_key,
                    state=state,
                    final_path=final_path,
                    error=error,
                )
            )
        return tuple(output)


class RetryCleanupOrganizer(FakeOrganizer):
    def __init__(self, backend_name: str) -> None:
        super().__init__(backend_name)
        self.cleanup_attempts = 0

    async def organize(
        self, job, manifest, requests, checkpoint_callback=None
    ) -> tuple[OrganizationResult, ...]:
        self.cleanup_attempts += 1
        if self.cleanup_attempts == 1:
            raise RuntimeError("cleanup cache is stale")
        return await super().organize(job, manifest, requests, checkpoint_callback)


class FakeBackendResolver:
    def __init__(self, *bundles: DownloadBackendBundle) -> None:
        self.bundles = {bundle.name.casefold(): bundle for bundle in bundles}
        self.requests: list[str] = []

    def download_backend(self, name: str) -> DownloadBackendBundle:
        self.requests.append(name)
        return self.bundles[name.casefold()]


@dataclass(frozen=True)
class MetadataCall:
    titles: tuple[str, ...]
    paths: tuple[str, ...]
    fallback_episodes: tuple[int | None, ...]
    include_enrichment: bool


class RecordingMetadataResolver:
    """Small provider-like resolver that preserves pre-applied path evidence."""

    def __init__(
        self,
        *,
        parent: ReleaseMetadata | None = None,
        per_path: dict[str, ReleaseMetadata | None] | None = None,
    ) -> None:
        self.parent = parent or ReleaseMetadata(anime_name="Example", season=1)
        self.per_path = per_path or {}
        self.calls: list[MetadataCall] = []

    async def resolve_many(
        self,
        candidates,
        documents=None,
        attempt_counts=None,
        *,
        fallbacks=None,
        include_enrichment=True,
    ) -> list[MetadataResolution]:
        documents = list(documents or [MetadataDocument() for _ in candidates])
        fallbacks = list(fallbacks or [None] * len(candidates))
        paths = tuple(_candidate_path(candidate) for candidate in candidates)
        self.calls.append(
            MetadataCall(
                titles=tuple(candidate.title for candidate in candidates),
                paths=paths,
                fallback_episodes=tuple(
                    fallback.episode if fallback is not None else None
                    for fallback in fallbacks
                ),
                include_enrichment=include_enrichment,
            )
        )

        if not include_enrichment:
            document = documents[0]
            document.apply(
                MetadataPatch(
                    source="parent-parser",
                    values=self.parent,
                    priority=10,
                )
            )
            return [MetadataResolution(document)]

        output: list[MetadataResolution] = []
        for candidate, document, fallback, path in zip(
            candidates, documents, fallbacks, paths
        ):
            parsed = self.per_path.get(path, _metadata_from_title(candidate.title))
            if parsed is None:
                # Deliberately use only safe fallback context.  If a parent
                # episode leaked here this item would incorrectly become ready.
                parsed = ReleaseMetadata(
                    anime_name=fallback.anime_name if fallback else None,
                    season=fallback.season if fallback else None,
                    episode=fallback.episode if fallback else None,
                )
            document.apply(
                MetadataPatch(
                    source="file-parser",
                    values=parsed,
                    priority=10,
                )
            )
            complete = document.values.minimum_complete()
            output.append(
                MetadataResolution(
                    document,
                    permanent_error=None if complete else "unparseable file",
                )
            )
        return output


class UnexpectedMetadataResolver:
    async def resolve_many(self, *args, **kwargs):
        raise AssertionError("a normal single-file job must reuse its job metadata")


class FailingMetadataResolver:
    async def resolve_many(self, *args, **kwargs):
        raise RuntimeError("metadata service unavailable")


class RetryableCompleteMetadataResolver:
    """Mimic TMDB: parsed fields exist while validation is still retryable."""

    async def resolve_many(
        self,
        candidates,
        documents=None,
        attempt_counts=None,
        *,
        fallbacks=None,
        include_enrichment=True,
    ):
        documents = list(documents or [MetadataDocument() for _ in candidates])
        if not include_enrichment:
            documents[0].apply(
                MetadataPatch(
                    source="parent",
                    values=ReleaseMetadata(anime_name="Example", season=1),
                )
            )
            return [MetadataResolution(documents[0])]
        output = []
        for document, attempt in zip(documents, attempt_counts or []):
            document.apply(
                MetadataPatch(
                    source="title",
                    values=ReleaseMetadata(anime_name="Example", season=1, episode=1),
                )
            )
            output.append(
                MetadataResolution(
                    document,
                    retryable_error=(
                        "TMDB validation unavailable" if attempt < 3 else None
                    ),
                )
            )
        return output


class ParentRetryThenSuccessResolver(RecordingMetadataResolver):
    def __init__(self) -> None:
        super().__init__(parent=ReleaseMetadata(anime_name="Example", season=1))
        self.parent_attempts = 0

    async def resolve_many(
        self,
        candidates,
        documents=None,
        attempt_counts=None,
        *,
        fallbacks=None,
        include_enrichment=True,
    ):
        if not include_enrichment:
            self.parent_attempts += 1
            if self.parent_attempts == 1:
                document = list(documents or [MetadataDocument()])[0]
                return [
                    MetadataResolution(
                        document,
                        retryable_error="parent parser temporarily unavailable",
                    )
                ]
        return await super().resolve_many(
            candidates,
            documents,
            attempt_counts,
            fallbacks=fallbacks,
            include_enrichment=include_enrichment,
        )


def _candidate_path(candidate: ReleaseCandidate) -> str:
    marker = ":collection-context"
    if candidate.guid and candidate.guid.endswith(marker):
        return marker
    return str(candidate.guid or "").split(":", 1)[-1]


def _metadata_from_title(title: str) -> ReleaseMetadata:
    compact = re.search(r"(?i)S(?P<season>\d{1,2})E(?P<episode>\d{1,3})", title)
    bare = re.search(
        r"(?i)S(?P<season>\d{1,2})\s*-\s*0*(?P<episode>\d{1,3})$",
        title,
    )
    match = compact or bare
    if not match:
        return ReleaseMetadata(anime_name="Example", season=1)
    return ReleaseMetadata(
        anime_name="Example",
        season=int(match.group("season")),
        episode=int(match.group("episode")),
        quality=VideoQuality.Q1080P,
    )


def _job(
    *,
    backend: str = "archive",
    title: str = "Example S01E01-E12 Batch",
    metadata: ReleaseMetadata | None = None,
    collection_hint: bool = False,
) -> DownloadJob:
    return DownloadJob(
        id="job-collection",
        candidate=ReleaseCandidate.create(
            source_name="fixture-feed",
            source_url="https://fixture.invalid/feed",
            title=title,
            download_url="magnet:?xt=urn:btih:collection",
        ),
        status=JobStatus.RUNNING,
        step=JobStep.DOWNLOAD,
        metadata=MetadataDocument(
            values=metadata
            or ReleaseMetadata(anime_name="Example", season=1, episode=99)
        ),
        downloader_name=backend,
        artifact={"collection_hint": True} if collection_hint else {},
    )


def _settings(
    *,
    exclude_patterns: list[str] | None = None,
    strict_filtering: bool = False,
) -> CoreSettings:
    return CoreSettings(
        download_path="/library",
        rename_format="{anime_name} S{season:02d}E{episode:02d}",
        rss_interval_seconds=300,
        metadata_providers=("fixture",),
        download_backend="openlist",
        strict_filtering=strict_filtering,
        metadata_filter=MetadataFilterSettings(
            exclude_patterns=list(exclude_patterns or [])
        ),
    )


def _bundle(
    manifest: DownloadManifest,
    *,
    name: str = "archive",
    organizer_states: dict[str, tuple[str, str | None]] | None = None,
) -> tuple[DownloadBackendBundle, FakeDownloader, FakeOrganizer]:
    downloader = FakeDownloader(name, manifest)
    organizer = FakeOrganizer(name, organizer_states)
    return (
        DownloadBackendBundle(name=name, downloader=downloader, organizer=organizer),
        downloader,
        organizer,
    )


def _worker(
    *,
    jobs: FakeJobRepository,
    backends: FakeBackendResolver,
    resolver,
    settings: CoreSettings | None = None,
    library: FakeLibraryRepository | None = None,
):
    notification_available = asyncio.Event()
    worker = DownloadWorkerPool(
        jobs=jobs,
        backends=backends,
        metadata_resolver=resolver,
        library=library or FakeLibraryRepository(),
        settings=settings or _settings(),
        work_available=asyncio.Event(),
        notification_available=notification_available,
    )
    return worker, notification_available


@pytest.mark.asyncio
async def test_persisted_backend_key_never_falls_back_to_current_default():
    manifest = DownloadManifest(
        root_path="/staging/default", files=(DownloadedFile("01.mkv"),)
    )
    default_bundle, default_downloader, default_organizer = _bundle(
        manifest, name="openlist"
    )
    backends = FakeBackendResolver(default_bundle)
    jobs = FakeJobRepository()
    job = _job(backend="retired-backend")
    worker, notification = _worker(
        jobs=jobs,
        backends=backends,
        resolver=UnexpectedMetadataResolver(),
    )

    await worker._process(job, worker_id=1)

    assert backends.requests == ["retired-backend"]
    assert jobs.failed == [
        "Persisted download backend 'retired-backend' is unavailable"
    ]
    assert not jobs.rescheduled
    assert not default_downloader.jobs
    assert not default_organizer.calls
    assert not notification.is_set()


@pytest.mark.asyncio
async def test_persisted_backend_bundle_handles_download_and_organization_atomically():
    archive_manifest = DownloadManifest(
        root_path="/staging/archive",
        files=(DownloadedFile("Example S01E01.mkv", 100),),
    )
    archive_bundle, archive_downloader, archive_organizer = _bundle(
        archive_manifest, name="archive"
    )
    default_bundle, default_downloader, default_organizer = _bundle(
        DownloadManifest(
            root_path="/staging/default", files=(DownloadedFile("wrong.mkv"),)
        ),
        name="openlist",
    )
    jobs = FakeJobRepository()
    job = _job(
        backend="ARCHIVE",
        title="Example S01E01",
        metadata=ReleaseMetadata(anime_name="Example", season=1, episode=1),
    )
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(default_bundle, archive_bundle),
        resolver=UnexpectedMetadataResolver(),
    )

    await worker._process(job, worker_id=1)

    assert archive_downloader.jobs == [job.id]
    assert len(archive_organizer.calls) == 1
    assert not default_downloader.jobs
    assert not default_organizer.calls
    assert job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_multiple_manifest_videos_resolve_and_persist_individual_resources():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("Example S01E01.mkv", 100),
            DownloadedFile("Example S01E01.zh-Hans.ass", 3),
            DownloadedFile("nested/Example S01E02.mp4", 110),
            DownloadedFile("cover.jpg", 2),
        ),
        checkpoint={"durable": True},
        cleanup_root="/staging/job-collection",
    )
    bundle, downloader, organizer = _bundle(manifest)
    resolver = RecordingMetadataResolver()
    jobs = FakeJobRepository()
    job = _job(collection_hint=False)
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )

    await worker._process(job, worker_id=2)

    assert downloader.jobs == [job.id]
    assert len(resolver.calls) == 2
    assert resolver.calls[0].include_enrichment is False
    assert resolver.calls[1].paths == (
        "Example S01E01.mkv",
        "nested/Example S01E02.mp4",
    )
    requests = organizer.calls[0].requests
    assert [request.video_relative_path for request in requests] == [
        "Example S01E01.mkv",
        "nested/Example S01E02.mp4",
    ]
    assert [request.metadata.values.episode for request in requests] == [1, 2]
    assert [item.relative_path for item in requests[0].sidecars] == [
        "Example S01E01.zh-Hans.ass"
    ]

    resources, summary = jobs.completed[0]
    assert len(resources) == 2
    assert {resource.title for resource in resources} == {job.candidate.title}
    assert {resource.metadata.values.episode for resource in resources} == {1, 2}
    assert len({resource.item_key for resource in resources}) == 2
    assert summary["collection"] is True
    assert summary["success_count"] == 2
    assert summary["warning_count"] == 0
    assert summary["deleted_count"] == 1
    assert notification.is_set()


@pytest.mark.asyncio
async def test_bare_episode_uses_parent_context_and_directory_season_overrides_it():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("01.mkv", 100),
            DownloadedFile("Season 2/02.mkv", 101),
        ),
    )
    bundle, _, organizer = _bundle(manifest)
    # The provider reports season 1 for both leaves.  The explicit Season 2
    # directory must win through the worker's higher-priority path evidence.
    resolver = RecordingMetadataResolver(
        per_path={
            "01.mkv": ReleaseMetadata(anime_name="Example", season=1, episode=1),
            "Season 2/02.mkv": ReleaseMetadata(
                anime_name="Example", season=1, episode=2
            ),
        }
    )
    jobs = FakeJobRepository()
    job = _job(metadata=ReleaseMetadata(anime_name="Example", season=1, episode=99))
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )

    await worker._process(job, worker_id=1)

    file_call = resolver.calls[1]
    assert file_call.titles == ("Example S01 - 01", "Example S02 - 02")
    assert file_call.fallback_episodes == (None, None)
    requests = organizer.calls[0].requests
    assert [request.metadata.values.episode for request in requests] == [1, 2]
    assert [request.metadata.values.season for request in requests] == [1, 2]
    assert [request.target_directory_path for request in requests] == [
        "/library/Example/Season 1",
        "/library/Example/Season 2",
    ]
    assert job.artifact["collection_context"]["episode"] is None


@pytest.mark.asyncio
async def test_parent_episode_never_turns_an_unparseable_child_into_an_episode():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("01.mkv", 100),
            DownloadedFile("mystery.mkv", 101),
        ),
    )
    bundle, _, organizer = _bundle(manifest)
    resolver = RecordingMetadataResolver(
        per_path={
            "01.mkv": ReleaseMetadata(anime_name="Example", season=1, episode=1),
            "mystery.mkv": None,
        }
    )
    jobs = FakeJobRepository()
    job = _job(metadata=ReleaseMetadata(anime_name="Example", season=1, episode=99))
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )

    await worker._process(job, worker_id=1)

    assert resolver.calls[1].fallback_episodes == (None, None)
    assert [request.video_relative_path for request in organizer.calls[0].requests] == [
        "01.mkv"
    ]
    unresolved = next(
        item
        for item in job.artifact["resolved_items"]
        if item["source_path"] == "mystery.mkv"
    )
    assert unresolved["state"] == "failed"
    assert unresolved["metadata"]["values"]["episode"] is None


@pytest.mark.asyncio
async def test_retryable_parent_context_is_not_cached_before_it_recovers():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("01.mkv", 100), DownloadedFile("02.mkv", 101)),
    )
    bundle, _, organizer = _bundle(manifest)
    resolver = ParentRetryThenSuccessResolver()
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )
    job = _job(
        metadata=ReleaseMetadata(),
        collection_hint=True,
    )

    await worker._process(job, worker_id=1)

    assert job.status == JobStatus.RETRY_WAIT
    assert "collection_context" not in job.artifact
    assert resolver.parent_attempts == 1

    job.status = JobStatus.RUNNING
    await worker._process(job, worker_id=1)

    assert job.status == JobStatus.COMPLETED
    assert resolver.parent_attempts == 2
    assert [
        request.metadata.values.episode for request in organizer.calls[0].requests
    ] == [1, 2]


@pytest.mark.asyncio
async def test_non_main_video_is_skipped_before_metadata_and_organization():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("Example S01E01.mkv", 100),
            DownloadedFile("SP/Example SP01.mkv", 20),
            DownloadedFile("Bonus/Example NCOP.mkv", 10),
        ),
    )
    bundle, _, organizer = _bundle(manifest)
    resolver = RecordingMetadataResolver()
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)

    assert resolver.calls[1].paths == ("Example S01E01.mkv",)
    assert [request.video_relative_path for request in organizer.calls[0].requests] == [
        "Example S01E01.mkv"
    ]
    states = {
        item["source_path"]: (item["state"], item["error"])
        for item in job.artifact["resolved_items"]
    }
    assert states["SP/Example SP01.mkv"] == ("skipped", "not_main_episode")
    assert states["Bonus/Example NCOP.mkv"] == (
        "skipped",
        "not_main_episode",
    )
    assert jobs.completed[0][1]["warning_count"] == 2


@pytest.mark.asyncio
async def test_explicit_season_zero_directory_is_skipped_before_metadata():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("Example S01E01.mkv", 100),
            DownloadedFile("Season 0/01.mkv", 20),
        ),
    )
    bundle, _, organizer = _bundle(manifest)
    resolver = RecordingMetadataResolver()
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=resolver,
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)

    assert resolver.calls[1].paths == ("Example S01E01.mkv",)
    assert [request.video_relative_path for request in organizer.calls[0].requests] == [
        "Example S01E01.mkv"
    ]
    special = next(
        item
        for item in job.artifact["resolved_items"]
        if item["source_path"] == "Season 0/01.mkv"
    )
    assert (special["state"], special["error"]) == (
        "skipped",
        "not_main_episode",
    )


@pytest.mark.asyncio
async def test_collection_parent_episode_is_not_reserved_as_an_active_child():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("Example S01E01.mkv", 100),),
    )
    bundle, _, _ = _bundle(manifest)
    jobs = FakeJobRepository()
    active = _job(collection_hint=True)
    active.id = "active-collection"
    active.artifact["resolved_items"] = [
        {
            "item_key": "episode-2",
            "source_path": "02.mkv",
            "state": "ready",
            "metadata": MetadataDocument(
                values=ReleaseMetadata(anime_name="Example", season=1, episode=2)
            ).to_dict(),
        }
    ]
    jobs.active = [active]
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
    )

    records = await worker._active_collection_records("current")

    assert ("Example", 1, 99) not in records
    assert ("Example", 1, 2) in records


def test_strict_collection_uses_highest_known_version_for_a_filename():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("Example S01E01.mkv", 100),),
    )
    bundle, _, _ = _bundle(manifest)
    worker, _ = _worker(
        jobs=FakeJobRepository(),
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
        settings=_settings(strict_filtering=True),
    )
    item = {
        "source_path": "Example S01E01 v2.mkv",
        "state": "ready",
        "metadata": MetadataDocument(
            values=ReleaseMetadata(anime_name="Example", season=1, episode=1, version=2)
        ).to_dict(),
    }

    worker._apply_strict_collection_group(
        ("Example", 1, 1),
        [item],
        [{"version": 3}, {"version": 1}],
    )

    assert (item["state"], item["error"]) == ("skipped", "release_policy")


@pytest.mark.asyncio
async def test_partial_organization_success_completes_parent_with_warning_summary():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("Example S01E01.mkv", 100),
            DownloadedFile("Example S01E02.mkv", 101),
        ),
    )
    bundle, _, organizer = _bundle(
        manifest,
        organizer_states={"Example S01E02.mkv": ("failed", "remote move failed")},
    )
    jobs = FakeJobRepository()
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
    )
    job = _job()

    await worker._process(job, worker_id=3)

    assert len(organizer.calls[0].requests) == 2
    resources, summary = jobs.completed[0]
    assert [resource.source_path for resource in resources] == ["Example S01E01.mkv"]
    assert summary["success_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["items"][1]["error"] == "remote move failed"
    assert job.status == JobStatus.COMPLETED
    assert notification.is_set()


@pytest.mark.asyncio
async def test_zero_regular_episodes_still_calls_organizer_to_cleanup_then_fails():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("SP/Example SP01.mkv", 20),
            DownloadedFile("cover.jpg", 2),
        ),
        cleanup_root="/staging/job-collection",
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)

    assert len(organizer.calls) == 1
    assert organizer.calls[0].requests == ()
    assert organizer.calls[0].manifest.cleanup_root == "/staging/job-collection"
    assert jobs.failed == ["No regular episode from the download could be organized"]
    assert not jobs.completed
    assert not jobs.skipped
    assert not notification.is_set()


@pytest.mark.asyncio
async def test_collection_title_with_one_video_is_not_treated_as_one_episode():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("01.mkv", 100),),
        cleanup_root="/staging/job-collection",
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=UnexpectedMetadataResolver(),
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)

    assert organizer.calls[0].requests == ()
    assert job.artifact["resolved_items"][0]["error"] == (
        "single_video_collection_unsupported"
    )
    assert jobs.failed == ["No regular episode from the download could be organized"]
    assert not notification.is_set()


@pytest.mark.asyncio
async def test_all_policy_rejections_cleanup_then_mark_parent_skipped():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("blocked/Example S01E01.mkv", 100),
            DownloadedFile("blocked/Example S01E02.mkv", 101),
            DownloadedFile("SP/Example SP01.mkv", 20),
        ),
        cleanup_root="/staging/job-collection",
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
        settings=_settings(exclude_patterns=[r"(?:^|/)blocked/"]),
    )
    job = _job()

    await worker._process(job, worker_id=1)

    assert organizer.calls[0].requests == ()
    assert jobs.skipped == ["release_policy"]
    assert not jobs.failed
    assert not jobs.completed
    regular = [
        item
        for item in job.artifact["resolved_items"]
        if item["source_path"].startswith("blocked/")
    ]
    assert all(
        item["state"] == "skipped" and item["error"] == "release_policy"
        for item in regular
    )
    assert not notification.is_set()


@pytest.mark.asyncio
async def test_single_video_manifest_reuses_existing_metadata_compatibly():
    manifest = DownloadManifest(
        root_path="/staging/job-single",
        files=(
            DownloadedFile("opaque-name.mkv", 100),
            DownloadedFile("opaque-name.ass", 3),
        ),
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    metadata = ReleaseMetadata(
        anime_name="Single Example",
        season=3,
        episode=7,
        quality=VideoQuality.Q1080P,
    )
    worker, notification = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=UnexpectedMetadataResolver(),
    )
    job = _job(
        title="Original single release title",
        metadata=metadata,
        collection_hint=False,
    )

    await worker._process(job, worker_id=1)

    request = organizer.calls[0].requests[0]
    assert request.video_relative_path == "opaque-name.mkv"
    assert request.metadata.values == metadata
    assert request.target_directory_path == "/library/Single Example/Season 3"
    assert request.target_filename == "Single Example S03E07.mkv"
    assert [item.relative_path for item in request.sidecars] == ["opaque-name.ass"]
    resources, summary = jobs.completed[0]
    assert len(resources) == 1
    assert resources[0].title == "Original single release title"
    assert summary["collection"] is False
    assert summary["warning_count"] == 0
    assert notification.is_set()


@pytest.mark.asyncio
async def test_provider_exceptions_are_bounded_per_item_before_staging_cleanup():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(
            DownloadedFile("01.mkv", 100),
            DownloadedFile("02.mkv", 101),
        ),
        cleanup_root="/staging/job-collection",
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=FailingMetadataResolver(),
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)
    assert job.status == JobStatus.RETRY_WAIT
    job.status = JobStatus.RUNNING
    job.attempt_count = 1
    await worker._process(job, worker_id=1)
    assert job.status == JobStatus.RETRY_WAIT
    job.status = JobStatus.RUNNING
    job.attempt_count = 2
    await worker._process(job, worker_id=1)

    assert organizer.calls[-1].requests == ()
    assert job.status == JobStatus.FAILED
    assert all(
        item["state"] == "failed" and item["attempt_count"] == 3
        for item in job.artifact["resolved_items"]
    )


@pytest.mark.asyncio
async def test_complete_title_metadata_waits_for_retryable_validation():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("01.mkv", 100), DownloadedFile("02.mkv", 101)),
        cleanup_root="/staging/job-collection",
    )
    bundle, _, organizer = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RetryableCompleteMetadataResolver(),
    )
    job = _job(collection_hint=True)

    await worker._process(job, worker_id=1)
    assert job.status == JobStatus.RETRY_WAIT
    assert not organizer.calls
    job.status = JobStatus.RUNNING
    job.attempt_count = 1
    await worker._process(job, worker_id=1)
    assert job.status == JobStatus.RETRY_WAIT
    assert not organizer.calls
    job.status = JobStatus.RUNNING
    job.attempt_count = 2
    await worker._process(job, worker_id=1)

    assert job.status == JobStatus.COMPLETED
    assert len(organizer.calls) == 1


@pytest.mark.asyncio
async def test_durable_cleanup_pending_does_not_consume_normal_job_retry_cap():
    manifest = DownloadManifest(
        root_path="/staging/job-collection",
        files=(DownloadedFile("Example S01E01.mkv", 100),),
    )
    bundle, _, _ = _bundle(manifest)
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=RecordingMetadataResolver(),
    )
    job = _job()
    job.step = JobStep.ORGANIZE
    job.attempt_count = 99

    async def cleanup_pending(_job):
        raise OrganizationCleanupPending("staging cleanup is pending")

    worker._organize = cleanup_pending
    await worker._process(job, worker_id=1)

    assert jobs.rescheduled
    assert jobs.failed == []


@pytest.mark.asyncio
async def test_terminal_download_failure_cleans_exact_staging_before_failing():
    manifest = DownloadManifest(root_path="/unused", files=())
    downloader = TerminalFailDownloader("archive", manifest)
    organizer = FakeOrganizer("archive")
    bundle = DownloadBackendBundle(
        name="archive", downloader=downloader, organizer=organizer
    )
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=UnexpectedMetadataResolver(),
    )
    job = _job(backend="archive")
    job.attempt_count = 3

    await worker._process(job, worker_id=1)

    assert jobs.failed == ["inventory timed out"]
    assert len(organizer.calls) == 1
    assert organizer.calls[0].manifest.root_path == (
        f"/library/.oani-download-tmp/{job.id}"
    )
    assert organizer.calls[0].requests == ()


@pytest.mark.asyncio
async def test_terminal_cleanup_retries_without_restarting_downloader():
    manifest = DownloadManifest(root_path="/unused", files=())
    downloader = TerminalFailDownloader("archive", manifest)
    organizer = RetryCleanupOrganizer("archive")
    bundle = DownloadBackendBundle(
        name="archive", downloader=downloader, organizer=organizer
    )
    jobs = FakeJobRepository()
    worker, _ = _worker(
        jobs=jobs,
        backends=FakeBackendResolver(bundle),
        resolver=UnexpectedMetadataResolver(),
    )
    job = _job(backend="archive")
    job.attempt_count = 3

    await worker._process(job, worker_id=1)
    assert job.status == JobStatus.RETRY_WAIT
    assert job.artifact["terminal_cleanup_pending"] == "inventory timed out"

    job.status = JobStatus.RUNNING
    job.attempt_count = 4
    await worker._process(job, worker_id=1)

    assert downloader.jobs == [job.id]
    assert organizer.cleanup_attempts == 2
    assert jobs.failed == ["inventory timed out"]
