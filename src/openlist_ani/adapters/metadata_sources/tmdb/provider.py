"""Authoritative TMDB metadata provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable

from openlist_ani.application.ports import (
    MetadataCacheRepository,
    MetadataPhase,
    MetadataResolution,
)
from openlist_ani.domain import (
    MetadataDocument,
    MetadataPatch,
    ReleaseCandidate,
    ReleaseMetadata,
)

from ..models import EpisodeMapping, TMDBMatch
from .contracts import AnimeIdentityResolver, EpisodeValidator


class TmdbMetadataProvider:
    name = "tmdb"
    _CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(
        self,
        *,
        identity_resolver: AnimeIdentityResolver,
        episode_validator: EpisodeValidator,
        cache: MetadataCacheRepository | None = None,
        cache_version: str = "1",
        max_concurrency: int = 8,
        close_callbacks: list[Callable[[], Awaitable[None]]] | None = None,
    ) -> None:
        self._identity_resolver = identity_resolver
        self._episode_validator = episode_validator
        self._cache = cache
        self._cache_version = cache_version
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._close_callbacks = close_callbacks or []

    @property
    def phase(self) -> MetadataPhase:
        return MetadataPhase.ENRICHMENT

    async def enrich_many(
        self,
        candidates: list[ReleaseCandidate],
        documents: list[MetadataDocument],
        attempt_counts: list[int],
    ) -> list[MetadataResolution]:
        output: list[MetadataResolution | None] = [None] * len(candidates)
        misses: list[tuple[int, str]] = []
        for index, (candidate, document) in enumerate(zip(candidates, documents)):
            cache_key = _cache_key(candidate, document)
            cached = await self._get_cached(cache_key)
            if cached is None:
                misses.append((index, cache_key))
                continue
            _apply_patch(document, cached)
            output[index] = MetadataResolution(document=document)

        names = {
            documents[index].values.anime_name.strip()
            for index, _ in misses
            if documents[index].values.anime_name
            and documents[index].values.minimum_complete()
        }
        identities = await self._resolve_identities(names)
        episode_cache: dict[tuple[int, int, int], EpisodeMapping | None] = {}

        for index, cache_key in misses:
            output[index] = await self._resolve_miss(
                candidate=candidates[index],
                document=documents[index],
                attempt_count=attempt_counts[index],
                cache_key=cache_key,
                identities=identities,
                episode_cache=episode_cache,
            )

        return [item for item in output if item is not None]

    async def _resolve_miss(
        self,
        *,
        candidate: ReleaseCandidate,
        document: MetadataDocument,
        attempt_count: int,
        cache_key: str,
        identities: dict[str, TMDBMatch],
        episode_cache: dict[tuple[int, int, int], EpisodeMapping | None],
    ) -> MetadataResolution:
        authoritative, error = await self._authoritative_metadata(
            candidate, document, identities, episode_cache
        )
        if authoritative is None:
            return _failure_resolution(document, error, attempt_count)
        _apply_patch(document, authoritative)
        await self._put_cached(cache_key, authoritative)
        return MetadataResolution(document=document)

    async def _authoritative_metadata(
        self,
        candidate: ReleaseCandidate,
        document: MetadataDocument,
        identities: dict[str, TMDBMatch],
        episode_cache: dict[tuple[int, int, int], EpisodeMapping | None],
    ) -> tuple[ReleaseMetadata | None, str]:
        value = document.values
        if not value.minimum_complete() or not value.anime_name:
            return None, "metadata incomplete before TMDB"
        identity = identities.get(value.anime_name.strip())
        if identity is None:
            return None, "TMDB match not found for parsed anime name"
        mapping = await self._episode_mapping(
            identity,
            season=value.season or 1,
            episode=value.episode or 1,
            anime_name=value.anime_name,
            release_title=candidate.title,
            cache=episode_cache,
        )
        if mapping is None:
            return None, (
                "TMDB season/episode mapping failed: "
                f"S{value.season or 1:02d}E{value.episode or 1:02d} "
                "has no authoritative match"
            )
        return (
            ReleaseMetadata(
                anime_name=identity.anime_name,
                season=mapping.season,
                episode=mapping.episode,
                year=identity.year,
                external_ids={"tmdb": str(identity.tmdb_id)},
            ),
            "",
        )

    async def _resolve_identities(self, names: set[str]) -> dict[str, TMDBMatch]:
        async def resolve(name: str) -> tuple[str, TMDBMatch | None]:
            async with self._semaphore:
                return name, await self._identity_resolver.resolve(name)

        pairs = await asyncio.gather(*(resolve(name) for name in names))
        return {name: identity for name, identity in pairs if identity is not None}

    async def _episode_mapping(
        self,
        identity: TMDBMatch,
        *,
        season: int,
        episode: int,
        anime_name: str,
        release_title: str,
        cache: dict[tuple[int, int, int], EpisodeMapping | None],
    ) -> EpisodeMapping | None:
        key = (identity.tmdb_id, season, episode)
        if key not in cache:
            async with self._semaphore:
                cache[key] = await self._episode_validator.validate(
                    tmdb_id=identity.tmdb_id,
                    season=season,
                    episode=episode,
                    anime_name=anime_name,
                    release_title=release_title,
                )
        return cache[key]

    async def _get_cached(self, cache_key: str) -> ReleaseMetadata | None:
        if self._cache is None:
            return None
        payload = await self._cache.get(self.name, cache_key, self._cache_version)
        return ReleaseMetadata.from_dict(payload) if payload is not None else None

    async def _put_cached(self, cache_key: str, metadata: ReleaseMetadata) -> None:
        if self._cache is None:
            return
        await self._cache.put(
            self.name,
            cache_key,
            self._cache_version,
            metadata.to_dict(),
            self._CACHE_TTL_SECONDS,
        )

    async def close(self) -> None:
        await self._identity_resolver.close()
        for callback in self._close_callbacks:
            await callback()


def _apply_patch(document: MetadataDocument, metadata: ReleaseMetadata) -> None:
    document.apply(
        MetadataPatch(
            source=TmdbMetadataProvider.name,
            authoritative=True,
            priority=30,
            values=metadata,
        )
    )


def _failure_resolution(
    document: MetadataDocument, error: str, attempt: int
) -> MetadataResolution:
    if document.values.minimum_complete() and attempt >= 3:
        document.apply(
            MetadataPatch(
                source=TmdbMetadataProvider.name,
                values=ReleaseMetadata(extra={"degraded_sources": ["tmdb"]}),
                degraded=True,
                priority=30,
            )
        )
        return MetadataResolution(
            document=document,
            degraded=True,
            permanent_error=error,
        )
    return MetadataResolution(document=document, retryable_error=error)


def _cache_key(candidate: ReleaseCandidate, document: MetadataDocument) -> str:
    value = document.values
    payload = json.dumps(
        {
            "title": candidate.title,
            "anime_name": value.anime_name,
            "season": value.season,
            "episode": value.episode,
            "tmdb_id": value.external_ids.get("tmdb"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
