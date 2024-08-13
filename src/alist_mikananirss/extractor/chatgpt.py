import json
import re

from loguru import logger
from openai import AsyncOpenAI

from .base import ExtractorBase
from .models import AnimeNameExtractResult, ResourceTitleExtractResult


class ChatGPTExtractor(ExtractorBase):
    def __init__(self, api_key, base_url=None, model="gpt-3.5-turbo") -> None:
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
        match = re.search(r"(\{[^\}]*\})", resp)
        if not match:
            raise ValueError(f"Can't parse GPT responese as a json:\n {resp}")
        return json.loads(match.group(1))

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameExtractResult:
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
        resp = await self._get_gpt_response(prompt, anime_name)
        data = await self._parse_json_response(resp)

        expected_data = {"anime_name": str, "season": int}
        if not all(
            isinstance(data.get(field_name), field_type)
            for field_name, field_type in expected_data.items()
        ):
            raise TypeError(f"GPT provide a wrong type data: {data}")

        info = AnimeNameExtractResult(
            anime_name=data["anime_name"], season=data["season"]
        )
        logger.debug(f"Chatgpt analyse resource name: {anime_name} -> {info}")
        return info

    async def analyse_resource_title(
        self, resource_title: str
    ) -> ResourceTitleExtractResult:
        prompt = """
        I will provide you with the torrent name of an anime. Please extract the following information from the torrent name: the name of the anime; the season number of the anime(If this episode is OVA，season set to 0); the episode number of the anime; the video quality; the fansub's name; language of the subtitles; and the version of the subtitle(defualt to 1). 
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
            int version;
            
            ResourceNameInfo(this.anime_name, this.season, this.episode, this.quality, this.fansub, this.language, this.version);
        }

        Based on the anime resource name, please provide a JSON format data structure(output in markdown format) that I can use directly to initialize an instance of the ResourceNameInfo class.
        ps:
        1. If the episode number is a decimal, it means that it is a special episode. In this case, the season number should be set to 0.
        2. Assume season=1 if no special indication is given
        3. please make a comprehensive judgment based on the values of anime_name_cn, anime_name_jp, and anime_name_en. The meanings of these three should be relatively similar.
        4. If there are multiple names, please choose just one of them
        5. anime name should not contains season info
        """
        resp = await self._get_gpt_response(prompt, resource_title)
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
            "version": int,
        }

        if not all(
            isinstance(data.get(field_name), field_type)
            for field_name, field_type in expected_data.items()
        ):
            raise TypeError(f"GPT provide a wrong type data: {data}")
        info = ResourceTitleExtractResult(
            anime_name=data["anime_name_cn"],
            season=data["season"],
            episode=int(data["episode"]) if data["season"] != 0 else 0,
            quality=data["quality"],
            fansub=data["fansub"],
            language=data["language"],
            version=data["version"],
        )
        logger.debug(f"Chatgpt analyse resource name: {resource_title} -> {info}")
        return info
