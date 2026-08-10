"""Durable ingestion job state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .metadata import MetadataDocument
from .release import ReleaseCandidate


class JobStep(StrEnum):
    METADATA = "metadata"
    DOWNLOAD = "download"
    RESOLVE_FILES = "resolve_files"
    ORGANIZE = "organize"
    FINALIZE = "finalize"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class DownloadJob:
    id: str
    candidate: ReleaseCandidate
    status: JobStatus = JobStatus.PENDING
    step: JobStep = JobStep.METADATA
    metadata: MetadataDocument = field(default_factory=MetadataDocument)
    downloader_name: str = "openlist"
    checkpoint: dict[str, Any] = field(default_factory=dict)
    checkpoint_version: int = 2
    artifact: dict[str, Any] = field(default_factory=dict)
    attempt_count: int = 0
    next_attempt_at: str | None = None
    last_error: str | None = None
    output_path: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None

    def advance(self, step: JobStep) -> None:
        if self.status in TERMINAL_JOB_STATUSES:
            raise ValueError(f"Cannot advance terminal job {self.id}")
        self.step = step
        self.status = JobStatus.PENDING
        self.attempt_count = 0
        self.next_attempt_at = None
        self.last_error = None
        self.lease_expires_at = None
        self.updated_at = utc_now()

    def api_state(self) -> str:
        if self.status == JobStatus.FAILED:
            return "failed"
        if self.status == JobStatus.CANCELLED:
            return "cancelled"
        if self.status == JobStatus.SKIPPED:
            return "cancelled"
        if self.status == JobStatus.COMPLETED:
            return "completed"
        if self.step == JobStep.METADATA:
            return "pending"
        if self.step == JobStep.DOWNLOAD:
            return "downloading" if self.status == JobStatus.RUNNING else "pending"
        if self.step == JobStep.RESOLVE_FILES:
            return "resolving" if self.status == JobStatus.RUNNING else "downloaded"
        if self.step == JobStep.ORGANIZE:
            return "renaming" if self.status == JobStatus.RUNNING else "downloaded"
        return "notifying" if self.status == JobStatus.RUNNING else "renamed"
