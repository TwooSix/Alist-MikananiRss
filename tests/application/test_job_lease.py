import asyncio

import pytest

from openlist_ani.application.lease import run_with_job_heartbeat
from openlist_ani.domain import DownloadJob, ReleaseCandidate


class _LeaseRepository:
    def __init__(self, error: Exception | None = None) -> None:
        self.renewals = 0
        self.error = error

    async def renew_lease(self, _job) -> None:
        self.renewals += 1
        if self.error is not None:
            raise self.error


def _job() -> DownloadJob:
    job = DownloadJob(
        id="lease-job",
        candidate=ReleaseCandidate.create(
            source_name="test",
            source_url="test",
            title="Lease test",
            download_url="magnet:lease",
        ),
    )
    job.lease_token = "token"
    return job


@pytest.mark.asyncio
async def test_job_heartbeat_renews_while_operation_is_running():
    repository = _LeaseRepository()

    async def operation():
        await asyncio.sleep(0.13)
        return "done"

    result = await run_with_job_heartbeat(
        operation(),
        jobs=[_job()],
        repository=repository,
        interval_seconds=0.05,
    )

    assert result == "done"
    assert repository.renewals >= 2


@pytest.mark.asyncio
async def test_lost_heartbeat_cancels_in_flight_operation():
    repository = _LeaseRepository(RuntimeError("lease lost"))
    cancelled = asyncio.Event()

    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(RuntimeError, match="lease lost"):
        await run_with_job_heartbeat(
            operation(),
            jobs=[_job()],
            repository=repository,
            interval_seconds=0.05,
        )

    assert cancelled.is_set()
