"""Reusable batch metadata composition for jobs and downloaded files."""

from __future__ import annotations

from dataclasses import fields

from openlist_ani.application.ports import (
    MetadataPhase,
    MetadataProvider,
    MetadataResolution,
)
from openlist_ani.domain import (
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
)


class MetadataPipelineResolver:
    """Run the configured provider pipeline without owning job state."""

    def __init__(self, providers: list[MetadataProvider]) -> None:
        self._providers = list(providers)

    async def resolve_many(
        self,
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument] | None = None,
        attempt_counts: list[int] | None = None,
        *,
        fallbacks: list[ReleaseMetadata | None] | None = None,
        include_enrichment: bool = True,
    ) -> list[MetadataResolution]:
        documents = list(documents or [MetadataDocument() for _ in candidates])
        attempts = list(attempt_counts or [0] * len(candidates))
        fallback_values = list(fallbacks or [None] * len(candidates))
        if not (
            len(candidates) == len(documents) == len(attempts) == len(fallback_values)
        ):
            raise ValueError("metadata pipeline inputs must have matching lengths")

        retryable: list[str | None] = [None] * len(candidates)
        permanent: list[str | None] = [None] * len(candidates)
        degraded = [False] * len(candidates)
        title_providers = [
            item for item in self._providers if item.phase == MetadataPhase.TITLE
        ]
        enrichment_providers = [
            item for item in self._providers if item.phase != MetadataPhase.TITLE
        ]
        for provider in title_providers:
            await self._apply_provider(
                provider,
                candidates,
                documents,
                attempts,
                retryable,
                permanent,
                degraded,
            )

        self.apply_source_metadata(candidates, documents)
        self.apply_fallback_metadata(documents, fallback_values)

        if include_enrichment:
            for provider in enrichment_providers:
                await self._apply_provider(
                    provider,
                    candidates,
                    documents,
                    attempts,
                    retryable,
                    permanent,
                    degraded,
                )

        return [
            MetadataResolution(
                document=document,
                retryable_error=retryable[index],
                permanent_error=permanent[index],
                degraded=degraded[index],
            )
            for index, document in enumerate(documents)
        ]

    @staticmethod
    async def _apply_provider(
        provider: MetadataProvider,
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
        attempts: list[int],
        retryable: list[str | None],
        permanent: list[str | None],
        degraded: list[bool],
    ) -> None:
        resolutions = await provider.enrich_many(candidates, documents, attempts)
        if len(resolutions) != len(candidates):
            raise RuntimeError(
                f"Metadata provider {provider.name} returned {len(resolutions)} "
                f"results for {len(candidates)} candidates"
            )
        for index, resolution in enumerate(resolutions):
            documents[index] = resolution.document
            retryable[index] = resolution.retryable_error or retryable[index]
            permanent[index] = resolution.permanent_error or permanent[index]
            degraded[index] = degraded[index] or resolution.degraded

    @staticmethod
    def apply_source_metadata(
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

    @staticmethod
    def apply_fallback_metadata(
        documents: list[MetadataDocument],
        fallbacks: list[ReleaseMetadata | None],
    ) -> None:
        for document, fallback in zip(documents, fallbacks):
            if fallback is None:
                continue
            missing = frozenset(
                item.name
                for item in fields(ReleaseMetadata)
                if _is_missing(getattr(document.values, item.name))
                and not _is_missing(getattr(fallback, item.name))
            )
            if missing:
                document.apply(
                    MetadataPatch(
                        source="collection_context",
                        values=fallback,
                        priority=0,
                        provided_fields=missing,
                    )
                )


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}
