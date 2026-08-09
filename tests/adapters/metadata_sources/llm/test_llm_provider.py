import asyncio
from unittest.mock import AsyncMock

from openlist_ani.adapters.metadata_sources.llm import (
    AnthropicLLMClient,
    LLMClient,
    LLMClientSettings,
    OpenAILLMClient,
    create_llm_client,
)
from openlist_ani.adapters.metadata_sources.llm.provider import LlmMetadataProvider
from openlist_ani.adapters.metadata_sources.models import (
    ParsedFields,
    TitleParseResponse,
)
from openlist_ani.domain import (
    LanguageType,
    MetadataDocument,
    ReleaseCandidate,
    VideoQuality,
)


class _Engine:
    def __init__(self):
        self.title_batches = []

    async def parse_titles(self, titles):
        self.title_batches.append(list(titles))
        await asyncio.sleep(0)
        return [
            TitleParseResponse(
                success=True,
                result=ParsedFields(
                    anime_name="Example",
                    season=1,
                    episode=5,
                    quality=VideoQuality.Q1080P,
                    fansub="Fansub",
                    languages=[LanguageType.CHS],
                    version=1,
                ),
            )
            for _ in titles
        ]


async def test_llm_provider_applies_metadata_and_reuses_bounded_cache():
    client = AsyncMock()
    provider = LlmMetadataProvider(client)
    engine = _Engine()
    provider._engine = engine
    candidate = ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="[Fansub] Example - 05 [1080p][CHS]",
        download_url="https://example.test/5.torrent",
    )

    first = await provider.enrich_many([candidate], [MetadataDocument()], [0])
    second = await provider.enrich_many([candidate], [MetadataDocument()], [0])

    assert engine.title_batches == [[candidate.title]]
    assert first[0].document.values.anime_name == "Example"
    assert first[0].document.values.quality == VideoQuality.Q1080P
    assert second[0].document.values.episode == 5
    assert provider._cache.maxsize == 1024


def test_llm_client_types_are_exposed_from_provider_package():
    assert LLMClient is not None
    assert LLMClientSettings is not None
    assert OpenAILLMClient is not None
    assert AnthropicLLMClient is not None
    assert create_llm_client is not None
