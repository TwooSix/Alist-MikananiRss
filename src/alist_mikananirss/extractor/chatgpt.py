from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from alist_mikananirss.utils.tmdb import TMDBClient

from .base import ExtractorBase
from .models import (
    AnimeNameExtractResult,
    ResourceTitleExtractResult,
    TMDBSearchParam,
    TMDBTvInfo,
)


class ChatGPTExtractor(ExtractorBase):
    def __init__(self, api_key, base_url=None, model="gpt-4o-mini") -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
            if self._base_url:
                self._client.base_url = self._base_url
        return self._client

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameExtractResult:
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an anime series resource categorization assistant. When given an anime series name, you need to parse out the original series name without season information, and the season information (default is Season 1)",
                },
                {"role": "user", "content": anime_name},
            ],
            response_format=AnimeNameExtractResult,
        )

        res = response.choices[0].message.parsed
        if res is None:
            raise ValueError(f"Failed to parse anime name: {anime_name} by GPT")
        logger.debug(f"Chatgpt analyse resource name: {anime_name} -> {res}")
        return res

    async def search_name_in_tmdb(
        self, resource_title: str, max_retry_times: int = 5
    ) -> Optional[TMDBTvInfo]:
        """Ask GPT use the resource title to search in TMDB and find the correct anime name

        Args:
            resource_title (str): The title of the resource

        Returns:
            TMDBTvInfo: The information of the tv series in TMDB, or None if not found
        """

        # 1. Ask GPT to parse the resource title and extract search keyword
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an anime series search assistant. You need to parse the filename of anime resources and extract search keywords from it. The keywords should be as concise as possible and should not include season information, to avoid missing relevant search results.",
                },
                {"role": "user", "content": resource_title},
            ],
            response_format=TMDBSearchParam,
        )
        search_param = response.choices[0].message.parsed
        if search_param is None:
            logger.error(f"Failed to parse resource title: {resource_title} by GPT")
            return None
        logger.debug(f"Search param: {search_param}")

        # 2. Use the keyword to search in TMDB
        self.tmdb_client = TMDBClient()
        search_results = await self.tmdb_client.search_tv(search_param.query)
        i = 0
        while i < max_retry_times and len(search_results) == 0:
            logger.warning(
                f"Unable to find anime name in TMDB, search param: {search_param}. Retry {i+1}/{max_retry_times}"
            )
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an anime series search assistant. You excel at breaking down original anime titles into keywords containing core information, then entering these keywords into search engines to find corresponding results.",
                    },
                    {
                        "role": "user",
                        "content": f"No results found for: {search_param.query}. Please try a different keyword.",
                    },
                ],
                response_format=TMDBSearchParam,
            )
            search_param = response.choices[0].message.parsed
            if search_param is None:
                logger.warning(
                    f"Failed to parse resource title: {resource_title} by GPT"
                )
                continue
            search_results = await self.tmdb_client.search_tv(search_param.query)
            i += 1

        if len(search_results) == 0:
            logger.error("Unable to find anime name in TMDB")
            return None
        logger.debug(f"Search results: {search_results}")

        # 3. Ask GPT to find the correct anime in the search results
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an anime series search assistant. Now that the search part is completed, given a filename of an anime resource, you need to find the corresponding anime series from the search results based on the information contained in the filename",
                },
                {
                    "role": "user",
                    "content": f"resource_file_name: {resource_title}, search_results: {search_results}",
                },
            ],
            response_format=TMDBTvInfo,
        )
        message = response.choices[0].message
        tmdb_info = message.parsed
        if tmdb_info is None:
            logger.error(
                f"Failed to find the anime of {resource_title} in search result: {search_results} by GPT"
            )
            return None
        logger.debug(f"TMDB info: {tmdb_info}")

        return tmdb_info

    async def analyse_resource_title(
        self, resource_title: str, use_tmdb: bool = True
    ) -> ResourceTitleExtractResult:
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an anime resource categorization assistant. Given an anime resource name, you need to extract information that helps users categorize and organize the resource based on its name",
                },
                {
                    "role": "user",
                    "content": resource_title,
                },
            ],
            response_format=ResourceTitleExtractResult,
        )
        message = response.choices[0].message
        res = message.parsed
        if res is None:
            raise ValueError(f"Failed to parse resource title: {resource_title} by GPT")

        if use_tmdb:
            tmdb_info = await self.search_name_in_tmdb(resource_title)
            res.anime_name = tmdb_info.anime_name if tmdb_info else res.anime_name
        logger.debug(f"Chatgpt analyse resource name: {resource_title} -> {res}")
        return res
