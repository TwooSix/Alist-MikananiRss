"""Factory for the TMDB metadata provider."""

from __future__ import annotations

from openlist_ani.application.ports import MetadataCacheRepository

from ..llm.client import LLMClient
from .candidate import (
    HeuristicCandidateSelector,
    LLMCandidateSelector,
    LLMQueryExpander,
    StaticQueryExpander,
)
from .client import TMDBClient, get_tmdb_client
from .episode_validator import TMDBEpisodeValidator
from .provider import TmdbMetadataProvider
from .resolver import TMDBAnimeIdentityResolver
from .settings import MetadataValidatorSettings


def create_tmdb_metadata_provider(
    settings: MetadataValidatorSettings,
    *,
    llm_client: LLMClient | None = None,
    tmdb_client: TMDBClient | None = None,
    cache: MetadataCacheRepository | None = None,
    cache_version: str = "1",
    max_concurrency: int = 8,
) -> TmdbMetadataProvider:
    client = tmdb_client or get_tmdb_client(
        api_key=settings.tmdb_api_key,
        language=settings.tmdb_language,
    )
    if llm_client is None:
        query_expander = StaticQueryExpander()
        candidate_selector = HeuristicCandidateSelector()
    else:
        query_expander = LLMQueryExpander(llm_client)
        candidate_selector = LLMCandidateSelector(llm_client)

    return TmdbMetadataProvider(
        identity_resolver=TMDBAnimeIdentityResolver(
            tmdb_client=client,
            query_expander=query_expander,
            candidate_selector=candidate_selector,
        ),
        episode_validator=TMDBEpisodeValidator(
            tmdb_client=client,
            llm_client=llm_client,
        ),
        cache=cache,
        cache_version=cache_version,
        max_concurrency=max_concurrency,
        close_callbacks=[llm_client.close] if llm_client is not None else [],
    )
