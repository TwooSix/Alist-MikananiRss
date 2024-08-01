import json
import re

from loguru import logger
from openai import AsyncOpenAI

from .base import ExtractorBase
from .models import AnimeNameInfo, ResourceNameInfo


class ChatGPTExtractor(ExtractorBase):
    def __init__(self, api_key, base_url=None, model="gpt-3.5-turbo") -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
        )
        if base_url:
            self.client.base_url = base_url
        self.model = model

    async def _get_gpt_response(self, prompt, resource_name):
        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": resource_name},
            ],
            model=self.model,
            temperature=0,
        )
        return chat_completion.choices[0].message.content

    async def _parse_json_response(self, resp):
        match = re.search(r"(\{.*?\})", resp, re.DOTALL)
        if not match:
            raise ValueError(f"gpt给出了一坨屎一样的回复: {resp}")
        return json.loads(match.group(1))

    async def analyse_anime_name(self, resource_name: str) -> AnimeNameInfo:
        """解析番剧名字，返回番剧本名和季度信息"""
        prompt = """
        In the following, I will provide you with an anime name. Please extract the original name of the anime (i.e., the name without season information) and the season number based on the given name.
        I need to parse this text into a data structure to initialize a AnimeNameInfo class in my code. The definition of the AnimeNameInfo class is as follows:

        class AnimeNameInfo{
            string anime_name;
            int season;
            
            MikanAnimeResource(this.anime_name, this.season);
        }

        Based on the resource name of the anime series, please provide a JSON-formatted data structure(output in markdown format) that I can directly use to initialize an instance of the class.
        """
        resp = await self._get_gpt_response(prompt, resource_name)
        data = await self._parse_json_response(resp)

        expected_data = {"anime_name": str, "season": int}
        if not all(
            isinstance(data.get(field_name), field_type)
            for field_name, field_type in expected_data.items()
        ):
            raise TypeError(f"GPT provide a wrong type data: {data}")

        info = AnimeNameInfo(anime_name=data["anime_name"], season=data["season"])
        logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {info}")
        return info

    async def analyse_resource_name(self, resource_name: str) -> ResourceNameInfo:
        """解析番剧资源名字，返回番剧集数和清晰度信息(若为总集篇则会返回季度)"""
        prompt = """
        I will provide you with the torrent name of an anime. Please extract the following information from the torrent name: the name of the anime; the episode number of the anime; the video quality; the fansub's name; and the language of the subtitles. If the episode number is a decimal, it means that it is a special episode. In this case, the season number should be set to 0.
        I need to parse this text into a data structure to initialize a ResourceNameInfo class in my code. The definition of the ResourceNameInfo class is as follows:

        class ResourceNameInfo{
            string anime_name_cn;
            string anime_name_jp;
            string anime_name_en;
            int season;
            float episode;
            string quality;
            string fansub;
            string language;
            
            ResourceNameInfo(this.anime_name, this.season, this.episode, this.quality, this.fansub, this.language);
        }

        Based on the anime resource name, please provide a JSON format data structure(output in markdown format) that I can use directly to initialize an instance of the ResourceNameInfo class.
        """
        resp = await self._get_gpt_response(prompt, resource_name)
        data = await self._parse_json_response(resp)

        expected_data = {
            "anime_name_cn": str,
            "anime_name_jp": str,
            "anime_name_en": str,
            "season": int,
            "episode": (float, int),
            "quality": str,
            "fansub": str,
            "language": str,
        }

        if not all(
            isinstance(data.get(field_name), field_type)
            for field_name, field_type in expected_data.items()
        ):
            raise TypeError(f"GPT provide a wrong type data: {data}")
        info = ResourceNameInfo(
            anime_name=data["anime_name_cn"],
            season=data["season"],
            episode=data["episode"],
            quality=data["quality"],
            fansub=data["fansub"],
            language=data["language"],
        )
        logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {info}")
        return info
