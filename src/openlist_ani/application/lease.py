"""Small helper that keeps claimed SQLite jobs reclaimable and exclusive."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from typing import TypeVar

from openlist_ani.application.ports import JobRepository
from openlist_ani.domain import DownloadJob

T = TypeVar("T")


async def run_with_job_heartbeat(
    operation: Awaitable[T],
    *,
    jobs: Iterable[DownloadJob],
    repository: JobRepository,
    interval_seconds: float,
) -> T:
    claimed = tuple(jobs)
    work = asyncio.create_task(operation)
    heartbeat = asyncio.create_task(
        _heartbeat(claimed, repository, interval_seconds),
        name="job-lease-heartbeat",
    )
    try:
        done, _ = await asyncio.wait(
            {work, heartbeat},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if work in done:
            return await work
        await heartbeat
        raise RuntimeError("Job lease heartbeat stopped unexpectedly")
    finally:
        for task in (work, heartbeat):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, heartbeat, return_exceptions=True)


async def _heartbeat(
    jobs: tuple[DownloadJob, ...],
    repository: JobRepository,
    interval_seconds: float,
) -> None:
    interval = max(0.05, interval_seconds)
    while True:
        await asyncio.sleep(interval)
        for job in jobs:
            if job.lease_token:
                await repository.renew_lease(job)
