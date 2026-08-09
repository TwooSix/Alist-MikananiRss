"""LLM-backed title extraction strategy."""

from __future__ import annotations

from ..models import TitleParseResponse
from .client import LLMClient

from .batch_parser import parse_title_batch_via_llm


class LLMTitleExtractEngine:
    """Parse release titles by delegating extraction to the configured LLM."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def parse_titles(self, titles: list[str]) -> list[TitleParseResponse]:
        return await parse_title_batch_via_llm(self._llm, titles)
