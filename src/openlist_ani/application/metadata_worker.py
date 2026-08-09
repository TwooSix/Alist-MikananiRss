"""Batch metadata composition and release selection."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from openlist_ani.application.ports import (
    CandidateTransformer,
    JobRepository,
    LibraryRepository,
    MetadataPhase,
    MetadataProvider,
)
from openlist_ani.application.lease import run_with_job_heartbeat
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import (
    DownloadJob,
    JobStep,
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
)
from openlist_ani.domain.naming import ReleaseFilenamePlanner
from openlist_ani.domain.policies import (
    best_indices,
    dominated_by_records,
    episode_key,
    is_version_upgrade,
    metadata_exclusion_reason,
    priority_levels,
    title_exclusion_reason,
)
from openlist_ani.logger import logger


class MetadataWorker:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        library: LibraryRepository,
        providers: list[MetadataProvider],
        settings: CoreSettings,
        jobs_available: asyncio.Event,
        download_available: asyncio.Event,
        candidate_transformers: list[CandidateTransformer] | None = None,
    ) -> None:
        self._jobs = jobs
        self._library = library
        self._providers = providers
        self._settings = settings
        self._jobs_available = jobs_available
        self._download_available = download_available
        self._candidate_transformers = list(candidate_transformers or [])
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()
        self._jobs_available.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                jobs = await self._jobs.claim(
                    JobStep.METADATA, self._settings.metadata_batch_size
                )
                if not jobs:
                    await self._wait()
                    continue
                await run_with_job_heartbeat(
                    self._process_batch(jobs),
                    jobs=jobs,
                    repository=self._jobs,
                    interval_seconds=self._settings.job_heartbeat_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception(f"Metadata worker recovered from error: {error}")
                await self._wait()

    async def _process_batch(self, jobs: list[DownloadJob]) -> None:
        candidates = [job.candidate for job in jobs]
        documents = [job.metadata for job in jobs]
        try:
            retryable, permanent = await self._enrich(jobs, candidates, documents)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            for job in jobs:
                await self._jobs.reschedule(
                    job,
                    f"metadata provider failed: {error}",
                    _metadata_retry_delay(job.attempt_count),
                )
            return

        ready = await self._classify(jobs, documents, retryable, permanent)
        if ready:
            await self._apply_release_policies(ready)

    async def _enrich(
        self,
        jobs: list[DownloadJob],
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
    ) -> tuple[list[str | None], list[str | None]]:
        retryable: list[str | None] = [None] * len(jobs)
        permanent: list[str | None] = [None] * len(jobs)
        title_providers = [
            item for item in self._providers if item.phase == MetadataPhase.TITLE
        ]
        enrichment_providers = [
            item for item in self._providers if item.phase != MetadataPhase.TITLE
        ]
        for provider in title_providers:
            await self._apply_provider(
                provider, jobs, candidates, documents, retryable, permanent
            )

        self._apply_feed_metadata(candidates, documents)

        for provider in enrichment_providers:
            await self._apply_provider(
                provider, jobs, candidates, documents, retryable, permanent
            )
        return retryable, permanent

    async def _apply_provider(
        self,
        provider: MetadataProvider,
        jobs: list[DownloadJob],
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
        retryable: list[str | None],
        permanent: list[str | None],
    ) -> None:
        resolutions = await provider.enrich_many(
            candidates,
            documents,
            [job.attempt_count for job in jobs],
        )
        if len(resolutions) != len(jobs):
            raise RuntimeError(
                f"Metadata provider {provider.name} returned {len(resolutions)} "
                f"results for {len(jobs)} candidates"
            )
        for index, resolution in enumerate(resolutions):
            documents[index] = resolution.document
            retryable[index] = resolution.retryable_error or retryable[index]
            permanent[index] = resolution.permanent_error or permanent[index]

    @staticmethod
    def _apply_feed_metadata(
        candidates: list[ReleaseCandidate], documents: list[MetadataDocument]
    ) -> None:
        for candidate, document in zip(candidates, documents):
            already_applied = any(
                item.source == candidate.source_name
                for history in document.evidence.values()
                for item in history
            )
            if not already_applied:
                document.apply(
                    MetadataPatch(
                        source=candidate.source_name,
                        values=candidate.source_metadata,
                        priority=20,
                    )
                )

    async def _classify(
        self,
        jobs: list[DownloadJob],
        documents: list[MetadataDocument],
        retryable: list[str | None],
        permanent: list[str | None],
    ) -> list[DownloadJob]:
        ready: list[DownloadJob] = []
        for index, job in enumerate(jobs):
            job.metadata = documents[index]
            if retryable[index] and job.attempt_count < 3:
                await self._jobs.reschedule(
                    job,
                    retryable[index] or "metadata temporarily unavailable",
                    _metadata_retry_delay(job.attempt_count),
                )
                continue
            if not job.metadata.values.minimum_complete():
                if permanent[index] and not retryable[index]:
                    await self._jobs.fail(job, permanent[index] or "metadata invalid")
                else:
                    await self._jobs.reschedule(
                        job,
                        retryable[index] or permanent[index] or "metadata incomplete",
                        min(21600, _metadata_retry_delay(job.attempt_count)),
                    )
                continue
            ready.append(job)
        return ready

    async def _apply_release_policies(self, ready: list[DownloadJob]) -> None:
        existing = await self._library.find_existing_titles(
            [job.candidate.title for job in ready]
        )
        ready_ids = {job.id for job in ready}
        active_jobs = await self._jobs.list_active()
        other_active_jobs = [job for job in active_jobs if job.id not in ready_ids]
        reserved_titles = {job.candidate.title for job in other_active_jobs} | set(
            existing
        )
        batch_titles: set[str] = set()
        eligible: list[DownloadJob] = []
        rejected: dict[str, str] = {}
        for job in ready:
            if job.candidate.title in existing:
                rejected[job.id] = "already_downloaded"
            elif (
                job.candidate.title in reserved_titles
                or job.candidate.title in batch_titles
            ):
                rejected[job.id] = "duplicate_active_title"
            elif title_exclusion_reason(
                job.candidate.title,
                self._settings.metadata_filter.exclude_patterns,
            ):
                rejected[job.id] = "release_policy"
            elif metadata_exclusion_reason(
                job.metadata.values,
                fansubs=self._settings.metadata_filter.exclude_fansub,
                qualities=self._settings.metadata_filter.exclude_quality,
                languages=self._settings.metadata_filter.exclude_languages,
            ):
                rejected[job.id] = "release_policy"
            else:
                eligible.append(job)
                batch_titles.add(job.candidate.title)

        await self._apply_priority_policy(eligible, other_active_jobs, rejected)
        if self._settings.strict_filtering:
            await self._apply_strict_policy(eligible, other_active_jobs, rejected)

        selected = [job for job in eligible if job.id not in rejected]
        transformed, transform_errors = await self._transform_candidates(selected)

        for job in ready:
            if reason := rejected.get(job.id):
                await self._jobs.skip(job, reason)
            elif error := transform_errors.get(job.id):
                message = f"candidate transform failed: {error}"
                if job.attempt_count >= 3:
                    await self._jobs.fail(job, message)
                else:
                    await self._jobs.reschedule(
                        job,
                        message,
                        _metadata_retry_delay(job.attempt_count),
                    )
            else:
                job.candidate = transformed.get(job.id, job.candidate)
                reserved_titles.add(job.candidate.title)
                job.artifact["base_path"] = self._settings.download_path
                job.advance(JobStep.DOWNLOAD)
                await self._jobs.save(job)
                self._download_available.set()

    async def _transform_candidates(
        self, jobs: list[DownloadJob]
    ) -> tuple[dict[str, ReleaseCandidate], dict[str, Exception]]:
        if not self._candidate_transformers or not jobs:
            return {}, {}

        results = await asyncio.gather(
            *(self._transform_candidate(job.candidate) for job in jobs),
            return_exceptions=True,
        )
        transformed: dict[str, ReleaseCandidate] = {}
        errors: dict[str, Exception] = {}
        for job, result in zip(jobs, results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                errors[job.id] = result
            else:
                transformed[job.id] = result
        return transformed, errors

    async def _transform_candidate(
        self, candidate: ReleaseCandidate
    ) -> ReleaseCandidate:
        transformed = candidate
        for transformer in self._candidate_transformers:
            transformed = await transformer.transform(transformed)
            if transformed.source_key != candidate.source_key:
                raise ValueError(
                    f"candidate transformer {transformer.name} changed source identity"
                )
        return transformed

    async def _apply_priority_policy(
        self,
        eligible: list[DownloadJob],
        active: list[DownloadJob],
        rejected: dict[str, str],
    ) -> None:
        groups = _group_jobs(eligible)
        keys = [key for key in groups if key is not None]
        records = await self._library.find_releases_by_episodes(keys)
        active_records = _active_records(active)
        settings = self._settings.priority
        for key, jobs in groups.items():
            if key is None:
                continue
            known = [*records.get(key, []), *active_records.get(key, [])]
            remaining: list[DownloadJob] = []
            for job in jobs:
                if dominated_by_records(
                    job.metadata.values,
                    known,
                    field_order=settings.field_order,
                    fansubs=settings.fansub,
                    qualities=settings.quality,
                    languages=settings.languages,
                ):
                    rejected[job.id] = "release_policy"
                else:
                    remaining.append(job)
            non_upgrades = [
                job
                for job in remaining
                if not is_version_upgrade(job.metadata.values, known)
            ]
            levels = [
                priority_levels(
                    job.metadata.values,
                    field_order=settings.field_order,
                    fansubs=settings.fansub,
                    qualities=settings.quality,
                    languages=settings.languages,
                )
                for job in non_upgrades
            ]
            keep = best_indices(levels)
            for index, job in enumerate(non_upgrades):
                if index not in keep:
                    rejected[job.id] = "release_policy"

    async def _apply_strict_policy(
        self,
        eligible: list[DownloadJob],
        active: list[DownloadJob],
        rejected: dict[str, str],
    ) -> None:
        candidates = [job for job in eligible if job.id not in rejected]
        groups = _group_jobs(candidates)
        keys = [key for key in groups if key is not None]
        records = await self._library.find_releases_by_episodes(keys)
        planner = ReleaseFilenamePlanner(self._settings.rename_format)
        active_by_key: dict[tuple[str, int, int], list[tuple[str, int]]] = defaultdict(
            list
        )
        for job in active:
            key = episode_key(job.metadata.values)
            if key is not None:
                active_by_key[key].append(
                    (
                        planner.stem(
                            job.metadata.values,
                            include_version=False,
                        ),
                        job.metadata.values.version or 1,
                    )
                )
        for key, jobs in groups.items():
            if key is None:
                continue
            db_stems = [
                (
                    _record_stem(planner, key, record),
                    record.get("version") or 1,
                )
                for record in records.get(key, [])
            ]
            winners: dict[str, DownloadJob] = {}
            for job in jobs:
                stem = planner.stem(job.metadata.values, include_version=False)
                version = job.metadata.values.version or 1
                if any(
                    stem == old and version <= old_version
                    for old, old_version in db_stems
                ):
                    rejected[job.id] = "release_policy"
                    continue
                if any(
                    stem == old and version <= old_version
                    for old, old_version in active_by_key.get(key, [])
                ):
                    rejected[job.id] = "release_policy"
                    continue
                current = winners.get(stem)
                if current is None or version > (current.metadata.values.version or 1):
                    if current is not None:
                        rejected[current.id] = "release_policy"
                    winners[stem] = job
                else:
                    rejected[job.id] = "release_policy"

    async def _wait(self) -> None:
        self._jobs_available.clear()
        try:
            await asyncio.wait_for(self._jobs_available.wait(), timeout=2.0)
        except TimeoutError:
            pass


def _metadata_retry_delay(attempt: int) -> float:
    return (60.0, 300.0, 900.0, 21600.0)[min(max(attempt - 1, 0), 3)]


def _group_jobs(
    jobs: list[DownloadJob],
) -> dict[tuple[str, int, int] | None, list[DownloadJob]]:
    grouped: dict[tuple[str, int, int] | None, list[DownloadJob]] = defaultdict(list)
    for job in jobs:
        grouped[episode_key(job.metadata.values)].append(job)
    return grouped


def _active_records(
    jobs: list[DownloadJob],
) -> dict[tuple[str, int, int], list[dict]]:
    output: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for job in jobs:
        metadata = job.metadata.values
        key = episode_key(metadata)
        if key is None:
            continue
        output[key].append(
            {
                "fansub": metadata.fansub,
                "quality": metadata.quality.value if metadata.quality else "",
                "languages": "".join(item.value for item in metadata.languages),
                "version": metadata.version or 1,
            }
        )
    return output


def _record_stem(
    planner: ReleaseFilenamePlanner,
    key: tuple[str, int, int],
    record: dict,
) -> str:
    from openlist_ani.domain import LanguageType, ReleaseMetadata, VideoQuality

    quality = record.get("quality")
    metadata = ReleaseMetadata(
        anime_name=key[0],
        season=key[1],
        episode=key[2],
        fansub=record.get("fansub"),
        quality=VideoQuality(quality) if quality else None,
        languages=[
            LanguageType(item)
            for item in (record.get("languages") or "")
            if item in {value.value for value in LanguageType}
        ],
        version=record.get("version") or 1,
    )
    return planner.stem(metadata, include_version=False)
