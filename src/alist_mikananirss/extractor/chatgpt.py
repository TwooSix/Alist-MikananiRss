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

    async def analyse_anime_name(self, resource_name: str) -> AnimeNameInfo:
        """解析番剧名字，返回番剧本名和季度信息"""
        prompt = """
        后续我将会给你提供一个番剧名字，请你根据番剧名字，提取出番剧的原名(即不包含季度信息的名字)；番剧的季度。
        我需要将这段文本解析成一个数据结构，以便初始化我的代码中的一个MikanAnimeResource类。MikanAnimeResource类的定义如下：

        class MikanAnimeResource{
            String anime_name;
            int season;
            
            MikanAnimeResource(this.anime_name, this.season);
        }

        请根据番剧的资源名字提供一个JSON格式的数据结构，我可以直接用它来初始化MikanAnimeResource类的一个实例
        """

        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": resource_name},
            ],
            model=self.model,
        )
        resp = chat_completion.choices[0].message.content
        pattern = r"(\{.*?\})"
        match = re.search(pattern, resp, re.DOTALL)
        if match:
            json_content = match.group(1)
            data = json.loads(json_content)
            info = AnimeNameInfo()
            # 类型检查
            if not (isinstance(data["anime_name"], str)):
                raise TypeError(
                    f"Chatgpt provide a wrong type of anime_name: {data['anime_name']}"
                )
            elif not isinstance(data["season"], int):
                raise TypeError(
                    f"Chatgpt provide a wrong type of season: {data['season']}"
                )
            info.set_anime_name(data["anime_name"])
            info.set_season(data["season"])
            logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {info}")
            return info
        else:
            raise ValueError(f"Chatgpt provide a wrong format response: {resp}")

    async def analyse_resource_name(self, resource_name: str) -> ResourceNameInfo:
        """解析番剧资源名字，返回番剧集数和清晰度信息(若为总集篇则会返回季度)"""
        prompt = """
        后续我将会给你提供一个番剧的资源名字，请你根据资源的名字，提取出番剧的集数；番剧的清晰度，以"xp"的格式存储，例如"1920x1080"请重命名为"1080p", 资源中字幕的语言。
        我需要将这段文本解析成一个数据结构，以便初始化我的代码中的一个MikanAnimeResource类。MikanAnimeResource类的定义如下：

        class MikanAnimeResource{
            float episode;
            String quality;
            String language;
            
            MikanAnimeResource(this.episode, this.quality, this.language);
        }

        请根据番剧的资源名字提供一个JSON格式的数据结构，我可以直接用它来初始化MikanAnimeResource类的一个实例
        """

        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": resource_name},
            ],
            model=self.model,
        )
        resp = chat_completion.choices[0].message.content
        pattern = r"(\{.*?\})"
        match = re.search(pattern, resp, re.DOTALL)
        if match:
            json_content = match.group(1)
            data = json.loads(json_content)
            info = ResourceNameInfo()
            # 类型检查
            if not (
                isinstance(data["episode"], float) or isinstance(data["episode"], int)
            ):
                raise TypeError(
                    f"Chatgpt provide a wrong type of episode: {data['episode']}"
                )
            elif not isinstance(data["quality"], str):
                raise TypeError(
                    f"Chatgpt provide a wrong type of quality: {data['quality']}"
                )
            # 是否总集篇(集数为浮点数)
            is_special = data["episode"] != int(data["episode"])
            if is_special:
                info.set_season(0)
                info.set_episode(data["episode"])
            else:
                info.set_episode(int(data["episode"]))
            info.set_quality(data["quality"].lower())
            info.set_language(data["language"])
            logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {info}")
            return info
        else:
            raise ValueError(f"Chatgpt provide a wrong format response: {resp}")
