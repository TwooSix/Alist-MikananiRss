import asyncio

from openlist_ani.adapters.metadata_sources.models import EpisodeMapping, TMDBMatch
from openlist_ani.adapters.metadata_sources.tmdb.provider import TmdbMetadataProvider
from openlist_ani.domain import (
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
)


class _IdentityResolver:
    def __init__(self, identity: TMDBMatch | None):
        self.identity = identity
        self.names = []
        self.closed = False

    async def resolve(self, anime_name: str):
        await asyncio.sleep(0)
        self.names.append(anime_name)
        return self.identity

    async def close(self):
        self.closed = True


class _EpisodeValidator:
    def __init__(self, mapping: EpisodeMapping | None):
        self.mapping = mapping
        self.calls = []

    async def validate(self, **values):
        await asyncio.sleep(0)
        self.calls.append(values)
        return self.mapping


def _candidate(title="Example - 15"):
    return ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title=title,
        download_url=f"magnet:?xt=urn:btih:{title}",
    )


def _document(episode=15):
    return MetadataDocument(
        values=ReleaseMetadata(anime_name="Example", season=1, episode=episode)
    )


async def test_tmdb_provider_applies_authoritative_identity_and_episode_mapping():
    identities = _IdentityResolver(
        TMDBMatch(tmdb_id=3822, anime_name="Canonical Example", year=2024)
    )
    episodes = _EpisodeValidator(
        EpisodeMapping(season=2, episode=3, strategy="absolute")
    )
    provider = TmdbMetadataProvider(
        identity_resolver=identities,
        episode_validator=episodes,
    )

    result = await provider.enrich_many([_candidate()], [_document()], [0])

    values = result[0].document.values
    assert values.anime_name == "Canonical Example"
    assert (values.season, values.episode) == (2, 3)
    assert values.year == 2024
    assert values.external_ids == {"tmdb": "3822"}
    assert identities.names == ["Example"]
    assert episodes.calls[0]["release_title"] == "Example - 15"


async def test_tmdb_provider_retries_then_degrades_when_authority_is_unavailable():
    provider = TmdbMetadataProvider(
        identity_resolver=_IdentityResolver(None),
        episode_validator=_EpisodeValidator(None),
    )

    retry = await provider.enrich_many([_candidate()], [_document()], [2])
    degraded = await provider.enrich_many([_candidate()], [_document()], [3])

    assert retry[0].retryable_error == "TMDB match not found for parsed anime name"
    assert degraded[0].degraded is True
    assert degraded[0].permanent_error
    assert degraded[0].document.values.extra["degraded_sources"] == ["tmdb"]


async def test_tmdb_provider_deduplicates_identity_and_episode_requests_per_batch():
    identities = _IdentityResolver(TMDBMatch(tmdb_id=1, anime_name="Example"))
    episodes = _EpisodeValidator(EpisodeMapping(season=1, episode=5, strategy="direct"))
    provider = TmdbMetadataProvider(
        identity_resolver=identities,
        episode_validator=episodes,
    )

    results = await provider.enrich_many(
        [_candidate("first"), _candidate("second")],
        [_document(5), _document(5)],
        [0, 0],
    )

    assert len(results) == 2
    assert identities.names == ["Example"]
    assert len(episodes.calls) == 1
