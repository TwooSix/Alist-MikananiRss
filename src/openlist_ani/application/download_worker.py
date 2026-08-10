"""Durable manifest resolution, organization and finalization worker pool."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from openlist_ani.application.collection import (
    CollectionVideo,
    child_release_title,
    collection_parent_probe,
    collection_videos,
    explicit_path_season,
    is_main_feature_path,
    parent_context,
)
from openlist_ani.application.lease import run_with_job_heartbeat
from openlist_ani.application.metadata_pipeline import MetadataPipelineResolver
from openlist_ani.application.manual_policy import (
    COLLECTION_POLICY_CONFLICT_KEY,
    manual_policy_acknowledges,
    manual_policy_is_approved,
    manual_partial_collection_retry_from_artifact,
)
from openlist_ani.application.organization import OrganizationCleanupPending
from openlist_ani.application.ports import (
    CompletedResource,
    DownloadBackendBundle,
    DownloadBackendResolver,
    DownloadManifest,
    DownloadedFile,
    JobRepository,
    LibraryRepository,
    OrganizationRequest,
    OrganizationResult,
    OrganizationSidecar,
)
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    JobStep,
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
)
from openlist_ani.domain.naming import (
    ReleaseDirectoryPlanner,
    ReleaseFilenamePlanner,
    format_anime_episode,
)
from openlist_ani.domain.policies import (
    best_indices,
    configured_title_exclusion_reason,
    dominated_by_records,
    episode_key,
    is_version_upgrade,
    metadata_exclusion_reason,
    priority_levels,
)
from openlist_ani.logger import logger


class UnknownDownloadBackend(RuntimeError):
    """A persisted job names a backend bundle that is not installed."""


class CollectionMetadataPending(RuntimeError):
    """At least one collection item still has a retryable metadata result."""


class DownloadWorkerPool:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        backends: DownloadBackendResolver,
        metadata_resolver: MetadataPipelineResolver,
        library: LibraryRepository,
        settings: CoreSettings,
        work_available: asyncio.Event,
        notification_available: asyncio.Event,
    ) -> None:
        self._jobs = jobs
        self._backends = backends
        self._metadata_resolver = metadata_resolver
        self._library = library
        self._settings = settings
        self._work_available = work_available
        self._notification_available = notification_available
        self._stop = asyncio.Event()
        self._collection_policy_lock = asyncio.Lock()
        self._directory_planner = ReleaseDirectoryPlanner()
        self._filename_planner = ReleaseFilenamePlanner(settings.rename_format)

    async def stop(self) -> None:  # NOSONAR - awaitable lifecycle contract
        self._stop.set()
        self._work_available.set()

    async def run(self, worker_id: int) -> None:
        while not self._stop.is_set():
            try:
                jobs = await self._jobs.claim_download_work(1)
                if not jobs:
                    await self._wait()
                    continue
                await run_with_job_heartbeat(
                    self._process(jobs[0], worker_id),
                    jobs=jobs,
                    repository=self._jobs,
                    interval_seconds=self._settings.job_heartbeat_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception(
                    f"Download worker recovered: worker={worker_id}; error={error}"
                )
                await self._wait()

    async def _process(self, job: DownloadJob, worker_id: int) -> None:
        try:
            if await self._finish_terminal_cleanup(job):
                return
            while job.status not in {
                JobStatus.COMPLETED,
                JobStatus.SKIPPED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                if await self._run_job_step(job, worker_id):
                    return
        except asyncio.CancelledError:
            raise
        except UnknownDownloadBackend as error:
            await self._jobs.fail(job, str(error))
            logger.error(
                f"Download job backend is unavailable: job_id={job.id}; {error}"
            )
        except CollectionMetadataPending as error:
            # Per-item and parent-context attempt counts are persisted
            # independently.  They decide when metadata is terminal, so this
            # retry must not be cut short by the parent job's generic cap.
            await self._reschedule_download_work(job, str(error))
        except OrganizationCleanupPending as error:
            await self._reschedule_download_work(job, str(error))
        except Exception as error:
            await self._handle_processing_failure(job, error)

    async def _finish_terminal_cleanup(self, job: DownloadJob) -> bool:
        terminal_error = job.artifact.get("terminal_cleanup_pending")
        if not terminal_error:
            return False
        await self._cleanup_terminal_staging(job)
        job.artifact.pop("terminal_cleanup_pending", None)
        await self._jobs.fail(job, str(terminal_error))
        logger.error(
            f"Download job failed after staging cleanup: {_job_label(job)}; "
            f"job_id={job.id}; error={terminal_error}"
        )
        return True

    async def _run_job_step(self, job: DownloadJob, worker_id: int) -> bool:
        if job.step == JobStep.DOWNLOAD:
            await self._download(job)
        elif job.step == JobStep.RESOLVE_FILES:
            logger.info(
                f"Downloaded file analysis started: {_job_label(job)}; job_id={job.id}"
            )
            await self._resolve_files(job)
            states = Counter(
                str(item.get("state") or "unknown")
                for item in job.artifact.get("resolved_items", [])
            )
            logger.info(
                f"Downloaded file analysis completed: {_job_label(job)}; "
                f"ready={states['ready']}, skipped={states['skipped']}, "
                f"failed={states['failed']}"
            )
        elif job.step == JobStep.ORGANIZE:
            await self._organize(job)
        elif job.step == JobStep.FINALIZE:
            await self._finalize(job, worker_id)
            return True
        else:
            raise RuntimeError(f"Unsupported download job step: {job.step}")
        return False

    async def _reschedule_download_work(self, job: DownloadJob, error: str) -> None:
        delay = _download_retry_delay(job.attempt_count)
        await self._jobs.reschedule(job, error, delay)
        self._work_available.set()
        logger.warning(
            f"Download work paused for {_job_label(job)}; step={job.step.value}, "
            f"attempt={job.attempt_count}, retry_in={delay:g}s; error={error}"
        )

    async def _handle_processing_failure(
        self, job: DownloadJob, error: Exception
    ) -> None:
        if job.attempt_count < 3:
            await self._reschedule_download_work(job, str(error))
            return
        if job.step in {JobStep.DOWNLOAD, JobStep.RESOLVE_FILES}:
            cleanup_pending = await self._try_terminal_cleanup(job, error)
            if cleanup_pending:
                return
        await self._jobs.fail(job, str(error))
        logger.error(f"Download job failed: job_id={job.id}; error={error}")

    async def _try_terminal_cleanup(self, job: DownloadJob, error: Exception) -> bool:
        job.artifact["terminal_cleanup_pending"] = str(error)
        await self._jobs.save(job)
        try:
            await self._cleanup_terminal_staging(job)
        except Exception as cleanup_error:
            await self._reschedule_download_work(
                job, f"Terminal staging cleanup is pending: {cleanup_error}"
            )
            return True
        job.artifact.pop("terminal_cleanup_pending", None)
        return False

    def _bundle(self, job: DownloadJob) -> DownloadBackendBundle:
        try:
            bundle = self._backends.download_backend(job.downloader_name)
        except Exception as error:
            raise UnknownDownloadBackend(
                f"Persisted download backend '{job.downloader_name}' is unavailable"
            ) from error
        if bundle.name.casefold() != job.downloader_name.casefold():
            raise UnknownDownloadBackend(
                f"Resolved backend '{bundle.name}' does not match persisted key "
                f"'{job.downloader_name}'"
            )
        return bundle

    async def _cleanup_terminal_staging(self, job: DownloadJob) -> None:
        """Clean an exact v2 staging namespace before a terminal failure."""

        root_path: str | None = None
        payload = job.artifact.get("download_manifest")
        if isinstance(payload, dict) and payload.get("cleanup_root"):
            root_path = str(payload["cleanup_root"])
        elif job.checkpoint_version >= 2 and job.checkpoint.get("temp_path"):
            root_path = str(job.checkpoint["temp_path"])
        if not root_path:
            return

        bundle = self._bundle(job)
        manifest = DownloadManifest(
            root_path=root_path,
            files=(),
            checkpoint=dict(job.checkpoint),
            cleanup_root=root_path,
        )

        async def checkpoint(value: dict[str, Any]) -> None:
            job.artifact["organization_checkpoint"] = dict(value)
            await self._jobs.save(job)

        try:
            results = await bundle.organizer.organize(job, manifest, (), checkpoint)
        except Exception as error:
            raise OrganizationCleanupPending(str(error)) from error
        if results:
            raise OrganizationCleanupPending(
                "Organizer returned items for an empty terminal cleanup"
            )

    async def _download(self, job: DownloadJob) -> None:
        bundle = self._bundle(job)
        job.artifact.setdefault("base_path", self._settings.download_path)
        logger.info(
            f"Download started: {_job_label(job)}; title={job.candidate.title}; "
            f"job_id={job.id}; backend={bundle.name}; attempt={job.attempt_count}"
        )

        async def checkpoint(payload: dict[str, Any]) -> None:
            job.checkpoint = dict(payload)
            await self._jobs.save(job)

        manifest = await bundle.downloader.start_or_resume(job, checkpoint)
        job.checkpoint = dict(manifest.checkpoint)
        job.artifact["download_manifest"] = _manifest_to_dict(manifest)
        job.advance(JobStep.RESOLVE_FILES)
        job.status = JobStatus.RUNNING
        await self._jobs.save(job)
        logger.info(
            f"Download completed: {_job_label(job)}; title={job.candidate.title}; "
            f"files={len(manifest.files)}; job_id={job.id}"
        )

    async def _resolve_files(self, job: DownloadJob) -> None:
        manifest = _manifest_from_job(job)
        videos = collection_videos(manifest)
        collection_mode = bool(job.artifact.get("collection_hint")) or len(videos) != 1

        if job.artifact.get("collection_hint") and len(videos) == 1:
            # A single multi-episode video would require chapter splitting,
            # which this workflow deliberately does not guess.  Persist a
            # terminal item so the organizer still removes the whole staging
            # namespace before finalization fails the parent task.
            video = videos[0]
            items = [
                {
                    "item_key": video.item_key,
                    "source_path": video.relative_path,
                    "state": "failed",
                    "metadata": MetadataDocument().to_dict(),
                    "error": "single_video_collection_unsupported",
                    "attempt_count": 0,
                }
            ]
            job.artifact["resolved_items"] = items
            job.artifact["organization_requests"] = []
            job.advance(JobStep.ORGANIZE)
            job.status = JobStatus.RUNNING
            await self._jobs.save(job)
            return

        if not collection_mode and videos and job.metadata.values.minimum_complete():
            item = _ready_single_item(videos[0], job.metadata)
            items = [item]
        else:
            items = await self._resolve_collection_items(job, videos)
            pending = [item for item in items if item["state"] == "pending"]
            if pending:
                job.artifact["resolved_items"] = items
                await self._jobs.save(job)
                raise CollectionMetadataPending(
                    f"Metadata is still pending for {len(pending)} collection item(s)"
                )
            # Serialize the save/reserve/policy transition across workers in
            # this runtime.  A second collection can then see the first one's
            # per-episode records instead of both organizing the same episode.
            async with self._collection_policy_lock:
                job.artifact["resolved_items"] = items
                await self._jobs.save(job)
                await self._apply_collection_policies(job, items)
                requests = self._build_organization_requests(job, videos, items)
                job.artifact["resolved_items"] = items
                job.artifact["organization_requests"] = [
                    _request_to_dict(request) for request in requests
                ]
                job.advance(JobStep.ORGANIZE)
                job.status = JobStatus.RUNNING
                await self._jobs.save(job)
            return

        requests = self._build_organization_requests(job, videos, items)
        job.artifact["resolved_items"] = items
        job.artifact["organization_requests"] = [
            _request_to_dict(request) for request in requests
        ]
        job.advance(JobStep.ORGANIZE)
        job.status = JobStatus.RUNNING
        await self._jobs.save(job)

    async def _resolve_collection_items(
        self,
        job: DownloadJob,
        videos: tuple[CollectionVideo, ...],
    ) -> list[dict[str, Any]]:
        items = _restore_collection_items(job, videos)
        unresolved = [item for item in items if item.get("state") == "pending"]
        if unresolved:
            context = await self._collection_context(job)
            candidates, documents, attempts = _collection_resolution_inputs(
                job, unresolved, context
            )
            # Persist incremented per-item attempts even when a provider raises
            # for the whole batch. This keeps retries bounded and guarantees
            # that the organizer can eventually clean the staging namespace.
            job.artifact["resolved_items"] = items
            await self._jobs.save(job)
            try:
                resolutions = await self._metadata_resolver.resolve_many(
                    candidates,
                    documents,
                    attempts,
                    fallbacks=[context] * len(candidates),
                )
            except Exception as error:
                _record_collection_resolution_failure(unresolved, documents, error)
            else:
                _apply_collection_resolutions(unresolved, resolutions)
        return items

    async def _collection_context(self, job: DownloadJob) -> ReleaseMetadata:
        if saved := job.artifact.get("collection_context"):
            return ReleaseMetadata.from_dict(saved)

        fallback = parent_context(job.metadata.values)
        source_context = parent_context(job.candidate.source_metadata)
        context_attempt = (
            int(job.artifact.get("collection_context_attempt_count") or 0) + 1
        )
        job.artifact["collection_context_attempt_count"] = context_attempt
        await self._jobs.save(job)
        probe_title = (
            collection_parent_probe(job.candidate.title) or job.candidate.title
        )
        candidate = ReleaseCandidate.create(
            source_name=job.candidate.source_name,
            source_url=job.candidate.source_url,
            title=probe_title,
            download_url=job.candidate.download_url,
            guid=f"{job.id}:collection-context",
            source_metadata=source_context,
        )
        try:
            resolution = (
                await self._metadata_resolver.resolve_many(
                    [candidate],
                    [MetadataDocument()],
                    [job.attempt_count],
                    fallbacks=[fallback],
                    include_enrichment=False,
                )
            )[0]
            context = parent_context(resolution.document.values)
            retryable_error = resolution.retryable_error
        except Exception as error:
            document = MetadataDocument()
            document.apply(
                MetadataPatch(
                    source=job.candidate.source_name,
                    values=source_context,
                    priority=20,
                )
            )
            document.apply(
                MetadataPatch(
                    source="collection_context",
                    values=fallback,
                    priority=0,
                )
            )
            context = parent_context(document.values)
            retryable_error = str(error)
        if (
            retryable_error
            and not _parent_context_complete(context)
            and context_attempt < 3
        ):
            job.artifact["collection_context_error"] = retryable_error
            raise CollectionMetadataPending(
                f"Collection parent metadata is still pending: {retryable_error}"
            )
        if retryable_error:
            job.artifact["collection_context_error"] = retryable_error
        else:
            job.artifact.pop("collection_context_error", None)
        job.artifact["collection_context"] = context.to_dict()
        return context

    async def _apply_collection_policies(
        self, job: DownloadJob, items: list[dict[str, Any]]
    ) -> None:
        _apply_partial_collection_retry_exclusions(job, items)
        if manual_policy_acknowledges(job, (COLLECTION_POLICY_CONFLICT_KEY,)):
            return
        confirmation_required = manual_policy_is_approved(job)
        self._apply_collection_metadata_filters(items, confirmation_required)
        await self._apply_collection_selection_policies(
            job, items, confirmation_required
        )
        if confirmation_required:
            _fail_collection_for_policy_confirmation(items)

    def _apply_collection_metadata_filters(
        self, items: list[dict[str, Any]], confirmation_required: bool
    ) -> None:
        metadata_filter = self._settings.metadata_filter
        for item in items:
            if item.get("state") != "ready":
                continue
            metadata = MetadataDocument.from_dict(item.get("metadata")).values
            if configured_title_exclusion_reason(
                str(item["source_path"]), metadata_filter.exclude_patterns
            ) or metadata_exclusion_reason(
                metadata,
                fansubs=metadata_filter.exclude_fansub,
                qualities=metadata_filter.exclude_quality,
                languages=metadata_filter.exclude_languages,
            ):
                _reject_policy_item(item, confirmation_required)

    async def _apply_collection_selection_policies(
        self,
        job: DownloadJob,
        items: list[dict[str, Any]],
        confirmation_required: bool,
    ) -> None:
        grouped = _group_ready_items(items)
        keys = list(grouped)
        records = await self._library.find_releases_by_episodes(keys)
        active_records = await self._active_collection_records(job.id)
        for key, group in grouped.items():
            known = [*records.get(key, []), *active_records.get(key, [])]
            self._apply_collection_group_policies(
                key, group, known, confirmation_required
            )

    def _apply_collection_group_policies(
        self,
        key: tuple[str, int, int],
        group: list[dict[str, Any]],
        known: list[dict[str, Any]],
        confirmation_required: bool,
    ) -> None:
        priority = self._settings.priority
        remaining: list[dict[str, Any]] = []
        for item in group:
            metadata = _item_metadata(item)
            if dominated_by_records(
                metadata,
                known,
                field_order=priority.field_order,
                fansubs=priority.fansub,
                qualities=priority.quality,
                languages=priority.languages,
            ):
                _reject_policy_item(item, confirmation_required)
            else:
                remaining.append(item)

        non_upgrades = [
            item
            for item in remaining
            if not is_version_upgrade(_item_metadata(item), known)
        ]
        levels = [
            priority_levels(
                _item_metadata(item),
                field_order=priority.field_order,
                fansubs=priority.fansub,
                qualities=priority.quality,
                languages=priority.languages,
            )
            for item in non_upgrades
        ]
        keep = best_indices(levels)
        for index, item in enumerate(non_upgrades):
            if index not in keep:
                _reject_policy_item(item, confirmation_required)

        if self._settings.strict_filtering:
            self._apply_strict_collection_group(
                key,
                [item for item in remaining if item["state"] == "ready"],
                known,
                confirmation_required=confirmation_required,
            )

    async def _active_collection_records(
        self, current_job_id: str
    ) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
        output: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
        for active in await self._jobs.list_active():
            if active.id == current_job_id:
                continue
            documents = [] if _is_collection_job(active) else [active.metadata]
            documents.extend(
                MetadataDocument.from_dict(item.get("metadata"))
                for item in active.artifact.get("resolved_items", [])
                if item.get("state") == "ready" and item.get("metadata")
            )
            for document in documents:
                if key := episode_key(document.values):
                    output[key].append(_metadata_record(document.values))
        return output

    def _apply_strict_collection_group(
        self,
        key: tuple[str, int, int],
        items: list[dict[str, Any]],
        known: list[dict[str, Any]],
        *,
        confirmation_required: bool = False,
    ) -> None:
        occupied: dict[str, int] = {}
        for record in known:
            stem = self._filename_planner.stem(
                _metadata_from_record(key, record), include_version=False
            )
            occupied[stem] = max(occupied.get(stem, 0), int(record.get("version") or 1))
        winners: dict[str, dict[str, Any]] = {}
        for item in sorted(
            items, key=lambda value: str(value["source_path"]).casefold()
        ):
            metadata = _item_metadata(item)
            stem = self._filename_planner.stem(metadata, include_version=False)
            version = metadata.version or 1
            if version <= occupied.get(stem, 0):
                _reject_policy_item(item, confirmation_required)
                continue
            current = winners.get(stem)
            if current is None:
                winners[stem] = item
                continue
            current_version = _item_metadata(current).version or 1
            if version > current_version:
                _reject_policy_item(current, confirmation_required)
                winners[stem] = item
            else:
                _reject_policy_item(item, confirmation_required)

    def _build_organization_requests(
        self,
        job: DownloadJob,
        videos,
        items: list[dict[str, Any]],
    ) -> tuple[OrganizationRequest, ...]:
        by_key = {video.item_key: video for video in videos}
        base_path = str(job.artifact.get("base_path") or self._settings.download_path)
        requests: list[OrganizationRequest] = []
        for item in items:
            if item.get("state") != "ready":
                continue
            video = by_key[str(item["item_key"])]
            document = MetadataDocument.from_dict(item.get("metadata"))
            target_directory = self._directory_planner.target_directory_path(
                base_path, document.values
            )
            target_filename = self._filename_planner.filename(
                document.values, PurePosixPath(video.relative_path).name
            )
            request = OrganizationRequest(
                item_key=video.item_key,
                video_relative_path=video.relative_path,
                sidecars=video.sidecars,
                target_directory_path=target_directory,
                target_filename=target_filename,
                metadata=document,
            )
            item.update(
                {
                    "target_directory_path": target_directory,
                    "target_filename": target_filename,
                    "sidecars": [
                        {
                            "relative_path": sidecar.relative_path,
                            "suffix": sidecar.suffix,
                        }
                        for sidecar in video.sidecars
                    ],
                }
            )
            requests.append(request)
        return tuple(requests)

    async def _organize(self, job: DownloadJob) -> None:
        self._prepare_legacy_organization(job)
        bundle = self._bundle(job)
        manifest = _manifest_from_job(job)
        requests = tuple(
            _request_from_dict(item)
            for item in job.artifact.get("organization_requests", [])
        )
        operation = "Rename" if len(requests) == 1 else "Organization"
        detail = _organization_detail(requests)
        logger.info(
            f"{operation} started: {_job_label(job)}; items={len(requests)}{detail}"
        )

        async def checkpoint(payload: dict[str, Any]) -> None:
            job.artifact["organization_checkpoint"] = dict(payload)
            await self._jobs.save(job)

        results = await bundle.organizer.organize(job, manifest, requests, checkpoint)
        _validate_organization_results(requests, results)
        job.artifact["organization_results"] = [
            _result_to_dict(result) for result in results
        ]
        job.advance(JobStep.FINALIZE)
        job.status = JobStatus.RUNNING
        await self._jobs.save(job)
        states = Counter(result.state for result in results)
        logger.info(
            f"{operation} completed: {_job_label(job)}; "
            f"completed={states['completed']}, skipped={states['skipped']}, "
            f"failed={states['failed']}"
        )

    def _prepare_legacy_organization(self, job: DownloadJob) -> None:
        if job.artifact.get("organization_requests") is not None:
            return
        directory = job.artifact.get("directory_path")
        filename = job.artifact.get("filename")
        if not directory or not filename:
            job.artifact["organization_requests"] = []
            return
        target_filename = job.artifact.get(
            "target_filename"
        ) or self._filename_planner.filename(job.metadata.values, str(filename))
        manifest = DownloadManifest(
            root_path=str(directory),
            files=(
                DownloadedFile(str(filename)),
                *(
                    DownloadedFile(str(item["filename"]))
                    for item in job.artifact.get("sidecars", [])
                ),
            ),
            checkpoint=dict(job.checkpoint),
            legacy_materialized=True,
        )
        request = OrganizationRequest(
            item_key="legacy-single-resource",
            video_relative_path=str(filename),
            sidecars=tuple(
                OrganizationSidecar(
                    str(item["filename"]), str(item.get("suffix") or "")
                )
                for item in job.artifact.get("sidecars", [])
            ),
            target_directory_path=str(directory),
            target_filename=str(target_filename),
            metadata=job.metadata,
        )
        job.artifact["download_manifest"] = _manifest_to_dict(manifest)
        job.artifact["resolved_items"] = [
            {
                "item_key": request.item_key,
                "source_path": request.video_relative_path,
                "state": "ready",
                "metadata": job.metadata.to_dict(),
                "attempt_count": 1,
            }
        ]
        job.artifact["organization_requests"] = [_request_to_dict(request)]

    async def _finalize(self, job: DownloadJob, worker_id: int) -> None:
        self._prepare_legacy_finalization(job)
        resolved = {
            str(item["item_key"]): item
            for item in job.artifact.get("resolved_items", [])
            if item.get("item_key")
        }
        results = [
            _result_from_dict(item)
            for item in job.artifact.get("organization_results", [])
        ]
        completed = [
            result
            for result in results
            if result.state == "completed" and result.final_path
        ]
        resources = tuple(
            CompletedResource(
                item_key=result.item_key,
                source_path=str(resolved[result.item_key]["source_path"]),
                title=_resource_title(job, resolved[result.item_key], len(resolved)),
                metadata=MetadataDocument.from_dict(
                    resolved[result.item_key].get("metadata")
                ),
                final_path=str(result.final_path),
            )
            for result in completed
            if result.item_key in resolved
        )
        summary = _completion_summary(job, _manifest_from_job(job), resolved, results)
        job.artifact["summary"] = summary
        job.artifact["final_paths"] = sorted(
            {resource.final_path for resource in resources}, key=str.casefold
        )

        if resources:
            await self._jobs.complete_with_resources(job, resources, summary)
            self._notification_available.set()
            logger.info(
                f"Notification queued: {_job_label(job)}; resources={len(resources)}"
            )
            logger.info(
                f"Download job completed: {_job_label(job)}; "
                f"title={job.candidate.title}; resources={len(resources)}, "
                f"warnings={summary['warning_count']}, worker={worker_id}, "
                f"job_id={job.id}"
            )
            return

        reason = (
            "Manual policy confirmation is required for collection contents"
            if any(
                item.get("error") == "manual_policy_confirmation_required"
                for item in resolved.values()
            )
            else "No regular episode from the download could be organized"
        )
        if _all_policy_skipped(resolved):
            await self._jobs.skip(job, "release_policy")
        else:
            await self._jobs.fail(job, reason)
        logger.warning(f"Download job produced no resources: job_id={job.id}; {reason}")

    def _prepare_legacy_finalization(self, job: DownloadJob) -> None:
        if job.artifact.get("organization_results") is not None:
            return
        final_path = job.output_path or job.artifact.get("renamed_path")
        if not final_path:
            job.artifact["organization_results"] = []
            return
        source = str(job.artifact.get("filename") or PurePosixPath(final_path).name)
        item_key = "legacy-single-resource"
        job.artifact.setdefault(
            "download_manifest",
            _manifest_to_dict(
                DownloadManifest(
                    root_path=str(job.artifact.get("directory_path") or "/"),
                    files=(DownloadedFile(source),),
                    legacy_materialized=True,
                )
            ),
        )
        job.artifact["resolved_items"] = [
            {
                "item_key": item_key,
                "source_path": source,
                "state": "ready",
                "metadata": job.metadata.to_dict(),
                "attempt_count": 1,
            }
        ]
        job.artifact["organization_results"] = [
            {
                "item_key": item_key,
                "state": "completed",
                "final_path": str(final_path),
                "sidecar_paths": [],
                "error": None,
            }
        ]

    async def _wait(self) -> None:
        self._work_available.clear()
        try:
            await asyncio.wait_for(self._work_available.wait(), timeout=2.0)
        except TimeoutError:
            pass


def _manifest_to_dict(manifest: DownloadManifest) -> dict[str, Any]:
    return {
        "root_path": manifest.root_path,
        "files": [
            {"relative_path": item.relative_path, "size": item.size}
            for item in manifest.files
        ],
        "checkpoint": dict(manifest.checkpoint),
        "cleanup_root": manifest.cleanup_root,
        "legacy_materialized": manifest.legacy_materialized,
    }


def _manifest_from_job(job: DownloadJob) -> DownloadManifest:
    payload = job.artifact.get("download_manifest")
    if not isinstance(payload, dict):
        directory = job.artifact.get("directory_path")
        filename = job.artifact.get("filename")
        if directory and filename:
            return DownloadManifest(
                root_path=str(directory),
                files=(DownloadedFile(str(filename)),),
                checkpoint=dict(job.checkpoint),
                legacy_materialized=True,
            )
        raise RuntimeError("Download manifest is missing")
    return DownloadManifest(
        root_path=str(payload["root_path"]),
        files=tuple(
            DownloadedFile(
                relative_path=str(item["relative_path"]),
                size=int(item.get("size") or 0),
            )
            for item in payload.get("files", [])
        ),
        checkpoint=dict(payload.get("checkpoint") or {}),
        cleanup_root=payload.get("cleanup_root"),
        legacy_materialized=bool(payload.get("legacy_materialized")),
    )


def _ready_single_item(video, metadata: MetadataDocument) -> dict[str, Any]:
    return {
        "item_key": video.item_key,
        "source_path": video.relative_path,
        "state": "ready",
        "metadata": metadata.to_dict(),
        "error": None,
        "attempt_count": 1,
    }


def _restore_collection_items(
    job: DownloadJob, videos: tuple[CollectionVideo, ...]
) -> list[dict[str, Any]]:
    previous = {
        str(item.get("item_key")): dict(item)
        for item in job.artifact.get("resolved_items", [])
        if item.get("item_key")
    }
    return [
        (
            previous[video.item_key]
            if video.item_key in previous
            else _new_collection_item(video)
        )
        for video in videos
    ]


def _new_collection_item(video: CollectionVideo) -> dict[str, Any]:
    main_feature = (
        is_main_feature_path(video.relative_path)
        and explicit_path_season(video.relative_path) != 0
    )
    return {
        "item_key": video.item_key,
        "source_path": video.relative_path,
        "state": "pending" if main_feature else "skipped",
        "error": None if main_feature else "not_main_episode",
        "attempt_count": 0,
    }


def _collection_resolution_inputs(
    job: DownloadJob,
    unresolved: list[dict[str, Any]],
    context: ReleaseMetadata,
) -> tuple[list[ReleaseCandidate], list[MetadataDocument], list[int]]:
    candidates: list[ReleaseCandidate] = []
    documents: list[MetadataDocument] = []
    attempts: list[int] = []
    for item in unresolved:
        relative_path = str(item["source_path"])
        document = MetadataDocument.from_dict(item.get("metadata"))
        _apply_collection_path_season(document, relative_path)
        attempt = int(item.get("attempt_count") or 0) + 1
        item["attempt_count"] = attempt
        attempts.append(attempt)
        candidates.append(
            ReleaseCandidate.create(
                source_name=f"{job.candidate.source_name}:collection-file",
                source_url=job.candidate.source_url,
                title=child_release_title(relative_path, context),
                download_url=job.candidate.download_url,
                guid=f"{job.id}:{relative_path}",
            )
        )
        documents.append(document)
    return candidates, documents, attempts


def _apply_collection_path_season(
    document: MetadataDocument, relative_path: str
) -> None:
    season = explicit_path_season(relative_path)
    if season is None:
        return
    document.apply(
        MetadataPatch(
            source="collection_path",
            values=ReleaseMetadata(season=season),
            priority=40,
            provided_fields=frozenset({"season"}),
        )
    )


def _record_collection_resolution_failure(
    unresolved: list[dict[str, Any]],
    documents: list[MetadataDocument],
    error: Exception,
) -> None:
    for item, document in zip(unresolved, documents):
        item["metadata"] = document.to_dict()
        item["error"] = f"metadata provider failed: {error}"
        item["state"] = "pending" if int(item["attempt_count"]) < 3 else "failed"


def _apply_collection_resolutions(
    unresolved: list[dict[str, Any]], resolutions: list[Any]
) -> None:
    for item, resolution in zip(unresolved, resolutions):
        item["metadata"] = resolution.document.to_dict()
        values = resolution.document.values
        if resolution.retryable_error:
            item["state"] = "pending" if int(item["attempt_count"]) < 3 else "failed"
            item["error"] = resolution.retryable_error
        elif _main_metadata_complete(values):
            item["state"] = "ready"
            item["error"] = None
        elif values.season == 0 or values.episode == 0:
            item["state"] = "skipped"
            item["error"] = "not_main_episode"
        else:
            item["state"] = "failed"
            item["error"] = (
                resolution.retryable_error
                or resolution.permanent_error
                or "metadata_incomplete"
            )


def _is_collection_job(job: DownloadJob) -> bool:
    if job.artifact.get("collection_hint"):
        return True
    if not isinstance(job.artifact.get("download_manifest"), dict):
        return False
    try:
        return len(collection_videos(_manifest_from_job(job))) != 1
    except (KeyError, TypeError, ValueError):
        # A malformed manifest will fail in its owning worker; it must not
        # reserve an unrelated parent episode in other jobs meanwhile.
        return True


def _main_metadata_complete(metadata: ReleaseMetadata) -> bool:
    return bool(
        metadata.anime_name
        and metadata.season is not None
        and metadata.season > 0
        and metadata.episode is not None
        and metadata.episode > 0
    )


def _parent_context_complete(metadata: ReleaseMetadata) -> bool:
    return bool(
        metadata.anime_name and metadata.season is not None and metadata.season > 0
    )


def _group_ready_items(
    items: list[dict[str, Any]],
) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    output: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("state") != "ready":
            continue
        if key := episode_key(_item_metadata(item)):
            output[key].append(item)
    return output


def _item_metadata(item: dict[str, Any]) -> ReleaseMetadata:
    return MetadataDocument.from_dict(item.get("metadata")).values


def _skip_item(item: dict[str, Any]) -> None:
    item["state"] = "skipped"
    item["error"] = "release_policy"


def _reject_policy_item(item: dict[str, Any], confirmation_required: bool) -> None:
    if confirmation_required:
        item["state"] = "failed"
        item["error"] = "manual_policy_confirmation_required"
    else:
        _skip_item(item)


def _fail_collection_for_policy_confirmation(items: list[dict[str, Any]]) -> None:
    if not any(
        item.get("error") == "manual_policy_confirmation_required" for item in items
    ):
        return
    # A collection discovered only after download did not receive the blanket
    # acknowledgement during preflight. Avoid a partial, silent selection and
    # require a fresh confirmation that covers the collection scope.
    for item in items:
        if item.get("state") == "ready":
            _reject_policy_item(item, True)


def _apply_partial_collection_retry_exclusions(
    job: DownloadJob, items: list[dict[str, Any]]
) -> None:
    retry = manual_partial_collection_retry_from_artifact(job.artifact)
    if retry is None:
        return
    completed_items = set(retry.completed_item_keys)
    completed_episodes = set(retry.completed_episode_keys)
    for item in items:
        if item.get("state") != "ready":
            continue
        key = episode_key(_item_metadata(item))
        item_key = str(item.get("item_key") or "")
        if key in completed_episodes or (key is None and item_key in completed_items):
            item["state"] = "skipped"
            item["error"] = "already_downloaded"


def _metadata_record(metadata: ReleaseMetadata) -> dict[str, Any]:
    return {
        "fansub": metadata.fansub,
        "quality": metadata.quality.value if metadata.quality else "",
        "languages": "".join(item.value for item in metadata.languages),
        "version": metadata.version or 1,
    }


def _metadata_from_record(
    key: tuple[str, int, int], record: dict[str, Any]
) -> ReleaseMetadata:
    from openlist_ani.domain import LanguageType, VideoQuality

    quality = record.get("quality")
    language_values = {item.value: item for item in LanguageType}
    return ReleaseMetadata(
        anime_name=key[0],
        season=key[1],
        episode=key[2],
        fansub=record.get("fansub"),
        quality=VideoQuality(quality) if quality else None,
        languages=[
            language_values[char]
            for char in str(record.get("languages") or "")
            if char in language_values
        ],
        version=int(record.get("version") or 1),
    )


def _request_to_dict(request: OrganizationRequest) -> dict[str, Any]:
    return {
        "item_key": request.item_key,
        "video_relative_path": request.video_relative_path,
        "sidecars": [
            {"relative_path": item.relative_path, "suffix": item.suffix}
            for item in request.sidecars
        ],
        "target_directory_path": request.target_directory_path,
        "target_filename": request.target_filename,
        "metadata": request.metadata.to_dict(),
    }


def _request_from_dict(payload: dict[str, Any]) -> OrganizationRequest:
    return OrganizationRequest(
        item_key=str(payload["item_key"]),
        video_relative_path=str(payload["video_relative_path"]),
        sidecars=tuple(
            OrganizationSidecar(
                relative_path=str(item["relative_path"]),
                suffix=str(item.get("suffix") or ""),
            )
            for item in payload.get("sidecars", [])
        ),
        target_directory_path=str(payload["target_directory_path"]),
        target_filename=str(payload["target_filename"]),
        metadata=MetadataDocument.from_dict(payload.get("metadata")),
    )


def _result_to_dict(result: OrganizationResult) -> dict[str, Any]:
    return {
        "item_key": result.item_key,
        "state": result.state,
        "final_path": result.final_path,
        "sidecar_paths": list(result.sidecar_paths),
        "error": result.error,
    }


def _validate_organization_results(
    requests: tuple[OrganizationRequest, ...],
    results: tuple[OrganizationResult, ...],
) -> None:
    expected = {request.item_key for request in requests}
    actual = [result.item_key for result in results]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise RuntimeError("Organizer returned an incomplete or duplicate result set")
    for result in results:
        if result.state not in {"completed", "failed"}:
            raise RuntimeError(
                f"Organizer returned invalid state for {result.item_key}: {result.state}"
            )
        if result.state == "completed" and not result.final_path:
            raise RuntimeError(
                f"Organizer completed {result.item_key} without a final path"
            )


def _result_from_dict(payload: dict[str, Any]) -> OrganizationResult:
    return OrganizationResult(
        item_key=str(payload["item_key"]),
        state=str(payload.get("state") or "failed"),
        final_path=payload.get("final_path"),
        sidecar_paths=tuple(payload.get("sidecar_paths") or ()),
        error=payload.get("error"),
    )


def _resource_title(job: DownloadJob, item: dict[str, Any], item_count: int) -> str:
    del item, item_count
    # All children retain the parent release title.  Schema v5 deliberately
    # permits duplicate titles, while item_key/source_path carry per-file
    # identity and allow future identical collection titles to be recognized.
    return job.candidate.title


def _completion_summary(
    job: DownloadJob,
    manifest: DownloadManifest,
    resolved: dict[str, dict[str, Any]],
    results: list[OrganizationResult],
) -> dict[str, Any]:
    by_key = {item.item_key: item for item in results}
    items: list[dict[str, Any]] = []
    kept_sources: set[str] = set()
    successful_episodes: list[str] = []
    for key, item in sorted(
        resolved.items(),
        key=lambda pair: str(pair[1].get("source_path", "")).casefold(),
    ):
        result = by_key.get(key)
        entry, metadata = _completion_summary_item(key, item, result)
        items.append(entry)
        if entry["state"] != "completed":
            continue
        kept_sources.update(_completed_item_sources(item))
        successful_episodes.append(_successful_episode_label(metadata))

    state_counts = Counter(item["state"] for item in items)
    success_count = state_counts["completed"]
    skipped_count = state_counts["skipped"]
    failed_count = state_counts["failed"]
    deleted_count = max(0, len(manifest.files) - len(kept_sources))
    warning_count = skipped_count + failed_count
    return {
        "collection": bool(job.artifact.get("collection_hint")) or len(resolved) != 1,
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "deleted_count": deleted_count,
        "warning_count": warning_count,
        "successful_episodes": successful_episodes,
        "items": items,
    }


def _completion_summary_item(
    key: str,
    item: dict[str, Any],
    result: OrganizationResult | None,
) -> tuple[dict[str, Any], ReleaseMetadata]:
    state = result.state if result is not None else str(item.get("state"))
    error = result.error if result is not None and result.error else item.get("error")
    metadata = MetadataDocument.from_dict(item.get("metadata")).values
    return (
        {
            "item_key": key,
            "source_path": item.get("source_path"),
            "state": state,
            "final_path": result.final_path if result else None,
            "error": error,
            "anime_name": metadata.anime_name,
            "season": metadata.season,
            "episode": metadata.episode,
        },
        metadata,
    )


def _completed_item_sources(item: dict[str, Any]) -> set[str]:
    return {
        str(item.get("source_path")),
        *(str(sidecar.get("relative_path")) for sidecar in item.get("sidecars", [])),
    }


def _successful_episode_label(metadata: ReleaseMetadata) -> str:
    return (
        f"{metadata.anime_name or 'Unknown'} "
        f"S{metadata.season or 0:02d}E{metadata.episode or 0:02d}"
    )


def _all_policy_skipped(resolved: dict[str, dict[str, Any]]) -> bool:
    policy_candidates = [
        item for item in resolved.values() if item.get("error") != "not_main_episode"
    ]
    return bool(policy_candidates) and all(
        item.get("state") == "skipped" and item.get("error") == "release_policy"
        for item in policy_candidates
    )


def _download_retry_delay(attempt: int) -> float:
    return (30.0, 120.0, 600.0)[min(max(attempt - 1, 0), 2)]


def _job_label(job: DownloadJob) -> str:
    metadata = job.metadata.values
    if (
        metadata.anime_name
        or metadata.season is not None
        or metadata.episode is not None
    ):
        return format_anime_episode(
            metadata.anime_name,
            metadata.season,
            metadata.episode,
        )
    return job.candidate.title


def _organization_detail(requests: tuple[OrganizationRequest, ...]) -> str:
    if len(requests) != 1:
        return ""
    request = requests[0]
    return f"; {request.video_relative_path} -> {request.target_filename}"
