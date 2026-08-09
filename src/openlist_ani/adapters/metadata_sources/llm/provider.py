"""LLM title metadata provider."""

from __future__ import annotations

from cachetools import TTLCache

from openlist_ani.application.ports import MetadataPhase, MetadataResolution
from openlist_ani.domain import (
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
)

from ..models import TitleParseResponse
from .client import LLMClient
from .engine import LLMTitleExtractEngine


class LlmMetadataProvider:
    name = "ai"

    def __init__(
        self,
        client: LLMClient | None,
        *,
        batch_size: int = 10,
        disabled_reason: str | None = None,
    ) -> None:
        self._client = client
        self._engine = LLMTitleExtractEngine(client) if client is not None else None
        self._batch_size = max(1, batch_size)
        self._disabled_reason = disabled_reason
        self._cache: TTLCache[str, TitleParseResponse] = TTLCache(
            maxsize=1024, ttl=86400
        )

    @property
    def phase(self) -> MetadataPhase:
        return MetadataPhase.TITLE

    async def enrich_many(
        self,
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
        attempt_counts: list[int],
    ) -> list[MetadataResolution]:
        del attempt_counts
        results = await self._parse([item.title for item in candidates])
        output: list[MetadataResolution] = []
        for document, result in zip(documents, results):
            if not result.success or result.result is None:
                output.append(
                    MetadataResolution(
                        document=document,
                        permanent_error=result.error or "llm parse failed",
                    )
                )
                continue
            value = result.result
            document.apply(
                MetadataPatch(
                    source=self.name,
                    values=ReleaseMetadata(
                        anime_name=value.anime_name,
                        season=value.season,
                        episode=value.episode,
                        fansub=value.fansub,
                        quality=value.quality,
                        languages=list(value.languages),
                        version=value.version,
                        external_ids=(
                            {"tmdb": str(value.tmdb_id)}
                            if value.tmdb_id is not None
                            else {}
                        ),
                    ),
                )
            )
            output.append(MetadataResolution(document=document))
        return output

    async def _parse(self, titles: list[str]) -> list[TitleParseResponse]:
        if self._engine is None:
            reason = self._disabled_reason or "LLM provider is not configured"
            return [TitleParseResponse(success=False, error=reason) for _ in titles]
        output: list[TitleParseResponse | None] = [None] * len(titles)
        misses: list[tuple[int, str]] = []
        for index, title in enumerate(titles):
            cached = self._cache.get(title)
            if cached is None:
                misses.append((index, title))
            else:
                output[index] = cached.model_copy(deep=True)
        for offset in range(0, len(misses), self._batch_size):
            chunk = misses[offset : offset + self._batch_size]
            parsed = await self._engine.parse_titles([item[1] for item in chunk])
            for (index, title), result in zip(chunk, parsed):
                result.release_title = result.release_title or title
                output[index] = result
                if result.success:
                    self._cache[title] = result.model_copy(deep=True)
        return [
            item or TitleParseResponse(success=False, error="missing parser result")
            for item in output
        ]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
