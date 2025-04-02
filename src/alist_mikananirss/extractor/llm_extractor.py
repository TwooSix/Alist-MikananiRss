from typing import Dict, List, Optional, Type

from loguru import logger

from ..utils.tmdb import TMDBClient
from .base import ExtractorBase
from .llm import LLMProvider
from .llm.prompt import PromptType, load_prompt
from .models import (
    AnimeNameExtractResult,
    ResourceTitleExtractResult,
    TMDBSearchParam,
    TMDBTvInfo,
)


class LLMExtractor(ExtractorBase):
    """Generic extractor that works with any LLM provider"""

    def __init__(
        self, llm_provider: LLMProvider, parse_mode: PromptType = PromptType.JSON_OBJECT
    ):
        """
        Initialize the extractor

        Args:
            llm_provider: The LLM provider to use
            parse_mode: The parsing mode ('json_object' or 'json_schema')
        """
        self.llm = llm_provider
        self.parse_mode = parse_mode
        self.tmdb_client = TMDBClient()

    async def _parse(self, messages: List[Dict[str, str]], response_type: Type):
        """Parse the response based on the selected mode"""
        if self.parse_mode == PromptType.JSON_SCHEMA:
            return await self.llm.parse_with_schema(messages, response_type)
        else:  # json_object mode
            json_result = await self.llm.parse_as_json(messages)
            return response_type(**json_result)

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameExtractResult:
        """Analyse the anime name to extract series and season info"""
        system_prompt = load_prompt(self.parse_mode, "anime_name")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": anime_name},
        ]

        try:
            result = await self._parse(messages, AnimeNameExtractResult)
            if result is None:
                raise ValueError(f"Failed to parse anime name: {anime_name}")
            logger.debug(f"Analyse anime name: {anime_name} -> {result}")
            return result
        except Exception as e:
            logger.error(f"Error parsing anime name: {e}")
            raise ValueError(f"Failed to parse anime name: {anime_name}") from e

    async def search_name_in_tmdb(
        self, resource_title: str, max_retry_times: int = 5
    ) -> Optional[TMDBTvInfo]:
        """Search for anime name in TMDB"""
        # 1. Ask LLM to parse the resource title and extract search keyword
        system_prompt = load_prompt(self.parse_mode, "tmdb_search_param")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resource_title},
        ]

        try:
            search_param = await self._parse(messages, TMDBSearchParam)
            if search_param is None:
                logger.error(f"Failed to parse resource title: {resource_title}")
                return None
            logger.debug(f"Search param: {search_param}")

            # 2. Use the keyword to search in TMDB
            search_results = await self.tmdb_client.search_tv(search_param.query)

            # Try different search keywords if no results
            i = 0
            while i < max_retry_times and len(search_results) == 0:
                logger.warning(
                    f"Unable to find anime name in TMDB, search param: {search_param}. "
                    f"Retry {i+1}/{max_retry_times}"
                )

                # Get a new search parameter
                retry_prompt = load_prompt(self.parse_mode, "tmdb_retry_search")
                retry_messages = [
                    {"role": "system", "content": retry_prompt},
                    {
                        "role": "user",
                        "content": f"No results found for: {search_param.query}. Please try a different keyword.",
                    },
                ]

                search_param = await self._parse(retry_messages, TMDBSearchParam)
                if search_param is None:
                    logger.warning(f"Failed to parse resource title: {resource_title}")
                    continue

                search_results = await self.tmdb_client.search_tv(search_param.query)
                i += 1

            if len(search_results) == 0:
                logger.error("Unable to find anime name in TMDB")
                return None

            logger.debug(f"Search results: {search_results}")

            # 3. Ask LLM to find the correct anime in the search results
            find_anime_prompt = load_prompt(self.parse_mode, "tmdb_find_anime")
            find_messages = [
                {"role": "system", "content": find_anime_prompt},
                {
                    "role": "user",
                    "content": f"resource_file_name: {resource_title}, search_results: {search_results}",
                },
            ]

            tmdb_info = await self._parse(find_messages, TMDBTvInfo)
            if tmdb_info is None:
                logger.error(
                    f"Failed to find the anime of {resource_title} in search result: {search_results}"
                )
                return None

            logger.debug(f"TMDB info: {tmdb_info}")
            return tmdb_info

        except Exception as e:
            logger.error(f"Error searching in TMDB: {e}")
            return None

    async def analyse_resource_title(
        self, resource_title: str, use_tmdb: bool = True
    ) -> ResourceTitleExtractResult:
        """Analyse the resource title to extract all info"""
        system_prompt = load_prompt(self.parse_mode, "resource_title")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resource_title},
        ]

        try:
            result = await self._parse(messages, ResourceTitleExtractResult)
            if result is None:
                raise ValueError(f"Failed to parse resource title: {resource_title}")

            # Get anime name from TMDB if enabled
            if use_tmdb:
                tmdb_info = await self.search_name_in_tmdb(resource_title)
                result.anime_name = (
                    tmdb_info.anime_name if tmdb_info else result.anime_name
                )

            logger.debug(f"Analyse resource title: {resource_title} -> {result}")
            return result
        except Exception as e:
            logger.error(f"Error parsing resource title: {e}")
            raise ValueError(f"Failed to parse resource title: {resource_title}") from e
