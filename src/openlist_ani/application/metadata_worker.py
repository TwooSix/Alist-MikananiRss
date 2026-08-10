"""Batch metadata composition and release selection."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from openlist_ani.application.ports import (
    CandidateTransformer,
    JobRepository,
    LibraryRepository,
    MetadataProvider,
)
from openlist_ani.application.lease import run_with_job_heartbeat
from openlist_ani.application.metadata_pipeline import MetadataPipelineResolver
from openlist_ani.application.manual_policy import (
    manual_policy_acknowledges,
    manual_policy_is_approved,
    manual_partial_collection_retry_from_artifact,
    matching_metadata_policy_keys,
    matching_title_policy_keys,
)
from openlist_ani.application.settings import CoreSettings, PrioritySettings
from openlist_ani.domain import (
    DownloadJob,
    JobStep,
    MetadataDocument,
    ReleaseCandidate,
)
from openlist_ani.domain.naming import ReleaseFilenamePlanner
from openlist_ani.domain.policies import (
    best_indices,
    collection_title_reason,
    dominated_by_records,
    episode_key,
    is_version_upgrade,
    priority_levels,
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
        self._pipeline = MetadataPipelineResolver(providers)
        self._settings = settings
        self._jobs_available = jobs_available
        self._download_available = download_available
        self._candidate_transformers = list(candidate_transformers or [])
        self._stop = asyncio.Event()

    async def stop(self) -> None:  # NOSONAR - awaitable lifecycle contract
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
        logger.info(f"Metadata processing started: {len(jobs)} release(s)")
        collection_jobs = [
            job
            for job in jobs
            if job.artifact.get("collection_hint")
            or collection_title_reason(job.candidate.title)
        ]
        regular_jobs = [job for job in jobs if job not in collection_jobs]
        if collection_jobs:
            await self._queue_collection_jobs(collection_jobs)
        if not regular_jobs:
            logger.info(
                "Metadata processing completed: "
                f"collections={len(collection_jobs)}, regular=0"
            )
            return

        candidates = [job.candidate for job in regular_jobs]
        documents = [job.metadata for job in regular_jobs]
        logger.info(f"Metadata parsing started: {len(regular_jobs)} release(s)")
        try:
            retryable, permanent = await self._enrich(
                regular_jobs, candidates, documents
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            for job in regular_jobs:
                await self._jobs.reschedule(
                    job,
                    f"metadata provider failed: {error}",
                    _metadata_retry_delay(job.attempt_count),
                )
            logger.warning(
                "Metadata parsing failed for batch; "
                f"releases={len(regular_jobs)}; error={error}"
            )
            return

        ready = await self._classify(regular_jobs, documents, retryable, permanent)
        logger.info(
            "Metadata parsing completed: "
            f"{len(ready)}/{len(regular_jobs)} release(s) ready"
        )
        if ready:
            await self._apply_release_policies(ready)
        logger.info(
            "Metadata processing completed: "
            f"collections={len(collection_jobs)}, regular={len(regular_jobs)}, "
            f"ready={len(ready)}"
        )

    async def _queue_collection_jobs(self, jobs: list[DownloadJob]) -> None:
        """Admit batch titles without inventing a parent episode number."""

        logger.info(f"Collection filtering started: {len(jobs)} release(s)")
        existing = await self._library.find_existing_titles(
            [job.candidate.title for job in jobs]
        )
        job_ids = {job.id for job in jobs}
        active = await self._jobs.list_active()
        reserved = {item.candidate.title for item in active if item.id not in job_ids}
        selected, rejected = self._classify_collection_jobs(jobs, existing, reserved)
        transformed, transform_errors = await self._transform_candidates(selected)
        for job in jobs:
            await self._persist_collection_result(
                job,
                rejected.get(job.id),
                transformed.get(job.id),
                transform_errors.get(job.id),
            )
        reasons = Counter(rejected.values())
        if transform_errors:
            reasons["candidate_transform_failed"] += len(transform_errors)
        summary = _reason_summary(reasons)
        suffix = f"; reasons: {summary}" if summary else ""
        logger.info(
            "Collection filtering completed: "
            f"{len(selected) - len(transform_errors)} accepted, "
            f"{len(jobs) - len(selected) + len(transform_errors)} skipped{suffix}"
        )

    def _classify_collection_jobs(
        self,
        jobs: list[DownloadJob],
        existing: set[str],
        reserved: set[str],
    ) -> tuple[list[DownloadJob], dict[str, str]]:
        selected: list[DownloadJob] = []
        rejected: dict[str, str] = {}
        batch_titles: set[str] = set()
        for job in jobs:
            title = job.candidate.title
            title_conflicts = matching_title_policy_keys(
                title, self._settings.metadata_filter.exclude_patterns
            )
            if title_conflicts and not manual_policy_acknowledges(job, title_conflicts):
                rejected[job.id] = _policy_rejection_reason(job)
            elif (
                title in existing
                and not manual_partial_collection_retry_from_artifact(job.artifact)
            ):
                rejected[job.id] = "already_downloaded"
            elif title in reserved or title in batch_titles:
                rejected[job.id] = "duplicate_active_title"
            else:
                selected.append(job)
                batch_titles.add(title)
        return selected, rejected

    async def _persist_collection_result(
        self,
        job: DownloadJob,
        rejection: str | None,
        transformed: ReleaseCandidate | None,
        transform_error: Exception | None,
    ) -> None:
        if rejection:
            logger.debug(
                f"Skipping collection release {job.candidate.title}: {rejection}"
            )
            await self._persist_collection_rejection(job, rejection)
            return
        if transform_error:
            logger.warning(
                "Collection candidate transform failed for "
                f"{job.candidate.title}: {transform_error}"
            )
            await self._persist_collection_transform_error(job, transform_error)
            return
        job.candidate = transformed or job.candidate
        job.artifact.update(
            {
                "base_path": self._settings.download_path,
                "collection_hint": True,
            }
        )
        job.advance(JobStep.DOWNLOAD)
        await self._jobs.save(job)
        self._download_available.set()

    async def _persist_collection_rejection(
        self, job: DownloadJob, reason: str
    ) -> None:
        if manual_policy_is_approved(job) and reason != "release_policy":
            await self._jobs.fail(job, reason)
        else:
            await self._jobs.skip(job, reason)

    async def _persist_collection_transform_error(
        self, job: DownloadJob, error: Exception
    ) -> None:
        message = f"candidate transform failed: {error}"
        if job.attempt_count >= 3:
            await self._jobs.fail(job, message)
        else:
            await self._jobs.reschedule(
                job, message, _metadata_retry_delay(job.attempt_count)
            )

    async def _enrich(
        self,
        jobs: list[DownloadJob],
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
    ) -> tuple[list[str | None], list[str | None]]:
        resolutions = await self._pipeline.resolve_many(
            candidates,
            documents,
            [job.attempt_count for job in jobs],
        )
        documents[:] = [item.document for item in resolutions]
        return (
            [item.retryable_error for item in resolutions],
            [item.permanent_error for item in resolutions],
        )

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
        MetadataPipelineResolver.apply_source_metadata(candidates, documents)

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
                delay = _metadata_retry_delay(job.attempt_count)
                await self._jobs.reschedule(
                    job,
                    retryable[index] or "metadata temporarily unavailable",
                    delay,
                )
                logger.warning(
                    f"Metadata parsing incomplete for {job.candidate.title}; "
                    f"will retry in {delay:g}s: {retryable[index]}"
                )
                continue
            if not job.metadata.values.minimum_complete():
                if permanent[index] and not retryable[index]:
                    reason = permanent[index] or "metadata invalid"
                    await self._jobs.fail(job, reason)
                    logger.warning(
                        f"Metadata extraction failed for {job.candidate.title}: "
                        f"{reason}"
                    )
                else:
                    reason = (
                        retryable[index] or permanent[index] or "metadata incomplete"
                    )
                    delay = min(21600, _metadata_retry_delay(job.attempt_count))
                    await self._jobs.reschedule(
                        job,
                        reason,
                        delay,
                    )
                    logger.warning(
                        f"Metadata extraction incomplete for {job.candidate.title}; "
                        f"will retry in {delay:g}s: {reason}"
                    )
                continue
            ready.append(job)
        return ready

    async def _apply_release_policies(self, ready: list[DownloadJob]) -> None:
        logger.info(f"Filtering started: {len(ready)} release(s)")
        existing = await self._library.find_existing_titles(
            [job.candidate.title for job in ready]
        )
        ready_ids = {job.id for job in ready}
        active_jobs = await self._jobs.list_active()
        other_active_jobs = [job for job in active_jobs if job.id not in ready_ids]
        reserved_titles = {job.candidate.title for job in other_active_jobs} | set(
            existing
        )
        eligible, rejected = self._initial_policy_results(
            ready, existing, reserved_titles
        )

        await self._apply_priority_policy(eligible, other_active_jobs, rejected)
        if self._settings.strict_filtering:
            await self._apply_strict_policy(eligible, other_active_jobs, rejected)

        selected = [job for job in eligible if job.id not in rejected]
        transformed, transform_errors = await self._transform_candidates(selected)
        await self._persist_policy_results(
            ready, rejected, transformed, transform_errors, reserved_titles
        )
        reasons = Counter(rejected.values())
        if transform_errors:
            reasons["candidate_transform_failed"] += len(transform_errors)
        accepted = len(selected) - len(transform_errors)
        summary = _reason_summary(reasons)
        suffix = f"; reasons: {summary}" if summary else ""
        logger.info(
            f"Filtering completed: {accepted} accepted, "
            f"{len(ready) - accepted} skipped{suffix}"
        )

    def _initial_policy_results(
        self,
        ready: list[DownloadJob],
        existing: set[str],
        reserved_titles: set[str],
    ) -> tuple[list[DownloadJob], dict[str, str]]:
        batch_titles: set[str] = set()
        eligible: list[DownloadJob] = []
        rejected: dict[str, str] = {}
        for job in ready:
            reason = self._initial_rejection_reason(
                job, existing, reserved_titles, batch_titles
            )
            if reason:
                rejected[job.id] = reason
            else:
                eligible.append(job)
                batch_titles.add(job.candidate.title)
        return eligible, rejected

    def _initial_rejection_reason(
        self,
        job: DownloadJob,
        existing: set[str],
        reserved_titles: set[str],
        batch_titles: set[str],
    ) -> str:
        if job.candidate.title in existing:
            return "already_downloaded"
        if (
            job.candidate.title in reserved_titles
            or job.candidate.title in batch_titles
        ):
            return "duplicate_active_title"
        metadata_filter = self._settings.metadata_filter
        conflicts = (
            *matching_title_policy_keys(
                job.candidate.title, metadata_filter.exclude_patterns
            ),
            *matching_metadata_policy_keys(job.metadata.values, metadata_filter),
        )
        if conflicts and not manual_policy_acknowledges(job, conflicts):
            return _policy_rejection_reason(job)
        return ""

    async def _persist_policy_results(
        self,
        ready: list[DownloadJob],
        rejected: dict[str, str],
        transformed: dict[str, ReleaseCandidate],
        transform_errors: dict[str, Exception],
        reserved_titles: set[str],
    ) -> None:
        for job in ready:
            if reason := rejected.get(job.id):
                logger.debug(f"Skipping release {job.candidate.title}: {reason}")
                if manual_policy_is_approved(job) and reason != "release_policy":
                    await self._jobs.fail(job, reason)
                else:
                    await self._jobs.skip(job, reason)
            elif error := transform_errors.get(job.id):
                message = f"candidate transform failed: {error}"
                logger.warning(f"{message} for {job.candidate.title}")
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
        override_key = ("priority:dominated",)
        overrides = [
            job for job in eligible if manual_policy_acknowledges(job, override_key)
        ]
        groups = _group_jobs([job for job in eligible if job not in overrides])
        keys = [key for key in groups if key is not None]
        records = await self._library.find_releases_by_episodes(keys)
        active_records = _active_records(active)
        settings = self._settings.priority
        for key, jobs in groups.items():
            if key is None:
                continue
            known = [*records.get(key, []), *active_records.get(key, [])]
            _apply_priority_group(jobs, known, settings, rejected)

    async def _apply_strict_policy(
        self,
        eligible: list[DownloadJob],
        active: list[DownloadJob],
        rejected: dict[str, str],
    ) -> None:
        override_key = ("strict:rename-stem-conflict",)
        overrides = [
            job
            for job in eligible
            if job.id not in rejected and manual_policy_acknowledges(job, override_key)
        ]
        candidates = [
            job for job in eligible if job.id not in rejected and job not in overrides
        ]
        groups = _group_jobs(candidates)
        keys = [key for key in groups if key is not None]
        records = await self._library.find_releases_by_episodes(keys)
        planner = ReleaseFilenamePlanner(self._settings.rename_format)
        active_by_key = _active_stems(active, planner)
        for job in overrides:
            if (key := episode_key(job.metadata.values)) is not None:
                active_by_key[key].append(
                    (
                        planner.stem(job.metadata.values, include_version=False),
                        job.metadata.values.version or 1,
                    )
                )
        for key, jobs in groups.items():
            if key is None:
                continue
            _apply_strict_group(
                key,
                jobs,
                records.get(key, []),
                active_by_key.get(key, []),
                planner,
                rejected,
            )

    async def _wait(self) -> None:
        self._jobs_available.clear()
        try:
            await asyncio.wait_for(self._jobs_available.wait(), timeout=2.0)
        except TimeoutError:
            pass


def _metadata_retry_delay(attempt: int) -> float:
    return (60.0, 300.0, 900.0, 21600.0)[min(max(attempt - 1, 0), 3)]


def _reason_summary(reasons: Counter[str]) -> str:
    return ", ".join(
        f"{reason}={count}" for reason, count in sorted(reasons.items()) if count
    )


def _policy_rejection_reason(job: DownloadJob) -> str:
    return (
        "manual_policy_confirmation_required"
        if manual_policy_is_approved(job)
        else "release_policy"
    )


def _group_jobs(
    jobs: list[DownloadJob],
) -> dict[tuple[str, int, int] | None, list[DownloadJob]]:
    grouped: dict[tuple[str, int, int] | None, list[DownloadJob]] = defaultdict(list)
    for job in jobs:
        grouped[episode_key(job.metadata.values)].append(job)
    return grouped


def _apply_priority_group(
    jobs: list[DownloadJob],
    known: list[dict],
    settings: PrioritySettings,
    rejected: dict[str, str],
) -> None:
    remaining = _reject_dominated_priority_jobs(jobs, known, settings, rejected)
    non_upgrades = [
        job for job in remaining if not is_version_upgrade(job.metadata.values, known)
    ]
    _reject_lower_priority_jobs(non_upgrades, settings, rejected)


def _reject_dominated_priority_jobs(
    jobs: list[DownloadJob],
    known: list[dict],
    settings: PrioritySettings,
    rejected: dict[str, str],
) -> list[DownloadJob]:
    remaining: list[DownloadJob] = []
    for job in jobs:
        dominated = dominated_by_records(
            job.metadata.values,
            known,
            field_order=settings.field_order,
            fansubs=settings.fansub,
            qualities=settings.quality,
            languages=settings.languages,
        )
        if dominated:
            rejected[job.id] = _policy_rejection_reason(job)
        else:
            remaining.append(job)
    return remaining


def _reject_lower_priority_jobs(
    jobs: list[DownloadJob],
    settings: PrioritySettings,
    rejected: dict[str, str],
) -> None:
    levels = [
        priority_levels(
            job.metadata.values,
            field_order=settings.field_order,
            fansubs=settings.fansub,
            qualities=settings.quality,
            languages=settings.languages,
        )
        for job in jobs
    ]
    keep = best_indices(levels)
    for index, job in enumerate(jobs):
        if index not in keep:
            rejected[job.id] = _policy_rejection_reason(job)


def _active_stems(
    active: list[DownloadJob], planner: ReleaseFilenamePlanner
) -> dict[tuple[str, int, int], list[tuple[str, int]]]:
    grouped: dict[tuple[str, int, int], list[tuple[str, int]]] = defaultdict(list)
    for job in active:
        if (key := episode_key(job.metadata.values)) is not None:
            grouped[key].append(
                (
                    planner.stem(job.metadata.values, include_version=False),
                    job.metadata.values.version or 1,
                )
            )
    return grouped


def _apply_strict_group(
    key: tuple[str, int, int],
    jobs: list[DownloadJob],
    records: list[dict],
    active_stems: list[tuple[str, int]],
    planner: ReleaseFilenamePlanner,
    rejected: dict[str, str],
) -> None:
    db_stems = [
        (_record_stem(planner, key, record), record.get("version") or 1)
        for record in records
    ]
    winners: dict[str, DownloadJob] = {}
    for job in jobs:
        stem = planner.stem(job.metadata.values, include_version=False)
        version = job.metadata.values.version or 1
        if _stem_is_reserved(stem, version, db_stems + active_stems):
            rejected[job.id] = _policy_rejection_reason(job)
            continue
        current = winners.get(stem)
        if current is None or version > (current.metadata.values.version or 1):
            if current is not None:
                rejected[current.id] = _policy_rejection_reason(current)
            winners[stem] = job
        else:
            rejected[job.id] = _policy_rejection_reason(job)


def _stem_is_reserved(stem: str, version: int, existing: list[tuple[str, int]]) -> bool:
    return any(stem == old and version <= old_version for old, old_version in existing)


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
