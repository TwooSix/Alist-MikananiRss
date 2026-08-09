"""TMDB validation adapters."""

from .client import CachedTMDBClient, TMDBClient, close_tmdb_clients, get_tmdb_client
from .candidate import (
    CandidateSelector,
    HeuristicCandidateSelector,
    LLMCandidateSelector,
    LLMQueryExpander,
    QueryExpander,
    StaticQueryExpander,
)
from .episode_mapper import EpisodeMapper, MappingContext
from .episode_validator import TMDBEpisodeValidator
from .factory import create_tmdb_metadata_provider
from .resolver import TMDBAnimeIdentityResolver
from .provider import TmdbMetadataProvider

__all__ = [
    "CachedTMDBClient",
    "CandidateSelector",
    "EpisodeMapper",
    "HeuristicCandidateSelector",
    "LLMCandidateSelector",
    "LLMQueryExpander",
    "MappingContext",
    "QueryExpander",
    "StaticQueryExpander",
    "TMDBAnimeIdentityResolver",
    "TMDBClient",
    "TMDBEpisodeValidator",
    "TmdbMetadataProvider",
    "close_tmdb_clients",
    "create_tmdb_metadata_provider",
    "get_tmdb_client",
]
