"""Durable download, organization and finalization worker pool."""

from __future__ import annotations

import asyncio

from openlist_ani.application.lease import run_with_job_heartbeat
from openlist_ani.application.ports import (
    DownloadAdapter,
    DownloadedAsset,
    DownloadedSidecar,
    JobRepository,
    Organizer,
)
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import JobStatus, JobStep
from openlist_ani.domain.naming import (
    ReleaseDirectoryPlanner,
    ReleaseFilenamePlanner,
)
from openlist_ani.logger import logger


class DownloadWorkerPool:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        downloader: DownloadAdapter,
        organizer: Organizer,
        settings: CoreSettings,
        work_available: asyncio.Event,
        notification_available: asyncio.Event,
    ) -> None:
        self._jobs = jobs
        self._downloader = downloader
        self._organizer = organizer
        self._settings = settings
        self._work_available = work_available
        self._notification_available = notification_available
        self._stop = asyncio.Event()
        self._directory_planner = ReleaseDirectoryPlanner()
        self._filename_planner = ReleaseFilenamePlanner(settings.rename_format)

    async def stop(self) -> None:
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

    async def _process(self, job, worker_id: int) -> None:
        try:
            while job.status not in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                if job.step == JobStep.DOWNLOAD:
                    await self._download(job)
                    continue
                if job.step == JobStep.ORGANIZE:
                    await self._organize(job)
                    continue
                await self._jobs.complete_with_resource(job, job.output_path or "")
                self._notification_available.set()
                logger.info(
                    f"Download job completed: job_id={job.id}, worker={worker_id}, "
                    f"path={job.output_path}"
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if job.attempt_count >= 3:
                await self._jobs.fail(job, str(error))
                logger.error(f"Download job failed: job_id={job.id}; error={error}")
            else:
                await self._jobs.reschedule(
                    job, str(error), _download_retry_delay(job.attempt_count)
                )
                self._work_available.set()

    async def _download(self, job) -> None:
        base_path = job.artifact.get("base_path", self._settings.download_path)
        target_directory = self._directory_planner.target_directory_path(
            base_path, job.metadata.values
        )

        async def checkpoint(payload: dict) -> None:
            job.checkpoint = dict(payload)
            await self._jobs.save(job)

        asset = await self._downloader.start_or_resume(
            job,
            target_directory,
            checkpoint,
        )
        job.checkpoint = dict(asset.checkpoint)
        job.artifact.update(
            {
                "base_path": base_path,
                "directory_path": asset.directory_path,
                "filename": asset.filename,
                "sidecars": [
                    {"filename": item.filename, "suffix": item.suffix}
                    for item in asset.sidecars
                ],
            }
        )
        job.advance(JobStep.ORGANIZE)
        job.status = JobStatus.RUNNING
        await self._jobs.save(job)

    async def _organize(self, job) -> None:
        renamed_path = job.artifact.get("renamed_path")
        if renamed_path:
            job.output_path = renamed_path
        else:
            asset = DownloadedAsset(
                directory_path=job.artifact["directory_path"],
                filename=job.artifact["filename"],
                sidecars=tuple(
                    DownloadedSidecar(
                        filename=item["filename"],
                        suffix=item.get("suffix", ""),
                    )
                    for item in job.artifact.get("sidecars", [])
                ),
                checkpoint=dict(job.checkpoint),
            )
            target_filename = job.artifact.get("target_filename")
            if not target_filename:
                target_filename = self._filename_planner.filename(
                    job.metadata.values, asset.filename
                )
                job.artifact["target_filename"] = target_filename
                await self._jobs.save(job)
            async def checkpoint(payload: dict) -> None:
                job.artifact["organize_plan"] = dict(payload)
                await self._jobs.save(job)

            organized = await self._organizer.organize(
                job,
                asset,
                target_filename,
                checkpoint,
            )
            job.output_path = organized.path
            job.artifact["renamed_path"] = organized.path
            job.artifact["renamed_sidecars"] = list(organized.sidecar_filenames)
        job.advance(JobStep.FINALIZE)
        job.status = JobStatus.RUNNING
        await self._jobs.save(job)

    async def _wait(self) -> None:
        self._work_available.clear()
        try:
            await asyncio.wait_for(self._work_available.wait(), timeout=2.0)
        except TimeoutError:
            pass


def _download_retry_delay(attempt: int) -> float:
    return (30.0, 120.0, 600.0)[min(max(attempt - 1, 0), 2)]
