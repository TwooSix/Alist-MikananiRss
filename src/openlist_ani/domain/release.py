"""Core release models used by the durable ingestion workflow."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .metadata import MetadataDocument, ReleaseMetadata


@dataclass(frozen=True)
class ReleaseCandidate:
    """A release observed from a feed or submitted through the API."""

    source_name: str
    source_url: str
    title: str
    download_url: str
    source_key: str
    guid: str | None = None
    source_metadata: ReleaseMetadata = field(default_factory=ReleaseMetadata)

    @classmethod
    def create(
        cls,
        *,
        source_name: str,
        source_url: str,
        title: str,
        download_url: str,
        guid: str | None = None,
        source_metadata: ReleaseMetadata | None = None,
    ) -> "ReleaseCandidate":
        identity = guid or download_url
        if not identity:
            identity = hashlib.sha256(
                f"{source_url}\0{title}".encode("utf-8")
            ).hexdigest()
        source_key = hashlib.sha256(
            f"{source_name}\0{identity}".encode("utf-8")
        ).hexdigest()
        return cls(
            source_name=source_name,
            source_url=source_url,
            title=title,
            download_url=download_url,
            source_key=source_key,
            guid=guid,
            source_metadata=source_metadata or ReleaseMetadata(),
        )


@dataclass(frozen=True)
class ResolvedRelease:
    """A candidate with enough metadata to be organized safely."""

    candidate: ReleaseCandidate
    metadata: MetadataDocument

    @property
    def values(self) -> ReleaseMetadata:
        return self.metadata.values
