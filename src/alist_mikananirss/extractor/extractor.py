import json
import re

from loguru import logger
from openai import AsyncOpenAI

from .models import AnimeNameInfo, ResourceNameInfo


class ExtractorBase:
    def __init__(self):
        pass

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameInfo:
        raise NotImplementedError

    async def analyse_resource_name(self, resource_name: str) -> ResourceNameInfo:
        raise NotImplementedError


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
        pattern = r"```json\n(.*?)\n```"
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
        pattern = r"```json\n(.*?)\n```"
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


class RegexExtractor(ExtractorBase):
    def __chinese_to_arabic(self, chinese_num):
        num_dict = {
            "零": 0,
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        unit_dict = {"十": 10}

        # 处理特殊情况：“十”
        if chinese_num == "十":
            return 10

        arabic_num = 0
        temp_num = 0  # 临时数字，用于处理十位和个位
        for char in chinese_num:
            if char in unit_dict:
                unit = unit_dict[char]
                if temp_num == 0:
                    temp_num = 1  # 处理“十一”这类情况
                arabic_num += temp_num * unit
                temp_num = 0  # 十位已经处理，重置临时数字
            else:
                temp_num = num_dict[char]

        arabic_num += temp_num  # 加上最后的个位数

        return arabic_num

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameInfo:
        """解析番剧名字，返回番剧本名和季度信息"""
        # 去除名字中的"第x部分"(因为这种情况一般是分段播出，而非新的一季)
        part_pattern = r"\s*第(.+)部分"
        anime_name = re.sub(part_pattern, "", anime_name)
        # 从番剧名字中提取番剧名字和季数
        season_pattern = r"(.+) 第(.+)[季期]"
        match = re.search(season_pattern, anime_name)
        info = AnimeNameInfo()
        if match:
            name = match.group(1)
            name = name.strip()
            info.set_anime_name(name)
            try:
                season = int(match.group(2))
            except ValueError:
                season = self.__chinese_to_arabic(match.group(2))
            info.set_season(season)
            return info
        # 根据罗马数字判断季数(如：无职转生Ⅱ ～到了异世界就拿出真本事～)
        roman_season_pattern = r"\s*([ⅠⅡⅢⅣⅤ])\s*"
        roman_numerals = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"]
        match = re.search(roman_season_pattern, anime_name)
        if match:
            season = roman_numerals.index(match.group(1)) + 1
            name = re.sub(roman_season_pattern, "", anime_name)
            info.set_anime_name(name)
            info.set_season(season)
            return info
        # 默认为第一季
        info.set_anime_name(anime_name)
        info.set_season(1)
        logger.debug(f"Regex analyse anime name: {anime_name} -> {info}")
        return info

    async def analyse_resource_name(self, resource_name: str) -> ResourceNameInfo:
        """解析番剧资源名字，返回番剧集数(若为总集篇则会返回季度)"""
        sep_char = ["[", "]", "【", "】", "(", ")", "（", "）"]
        tmp_str = resource_name
        for char in sep_char:
            tmp_str = tmp_str.replace(char, " ")
        keyw = tmp_str.split()
        episode = -1
        for k in reversed(keyw):
            k_ = k.replace("第", "").replace("话", "").replace("集", "")
            k_ = re.sub(r"(?<=\d)v\d", "", k_)
            try:
                episode = float(k_)
            except Exception:
                continue
            break
        if episode == -1:
            raise ValueError(f"Can't find episode number in {resource_name}")
        info = ResourceNameInfo()
        info.set_episode(episode)
        # 是否总集篇(集数为浮点数)
        is_special = episode != int(episode)
        if is_special:
            info.set_season(0)
        else:
            info.set_episode(int())
        logger.debug(f"Regex analyse resource name: {resource_name} -> {info}")

        return info


class Extractor:
    def __init__(self, extractor: ExtractorBase) -> None:
        self.extractor = extractor
        self.tmp_regex_extractor = RegexExtractor()
        self.anime_name = ""
        self.season = -1
        self.episode = -1
        self.quality = ""
        self.language = ""

    async def extract(self, anime_name: str, resource_name: str):
        # chatgpt对番剧名分析不稳定，所以固定用正则分析番剧名+季度
        anime_name_info = await self.tmp_regex_extractor.analyse_anime_name(anime_name)
        anime_name = anime_name_info.anime_name
        season = anime_name_info.season

        resource_name_info = await self.extractor.analyse_resource_name(resource_name)
        episode = resource_name_info.episode
        if resource_name_info.season:
            season = resource_name_info.season
        quality = resource_name_info.quality
        language = resource_name_info.language

        self.anime_name = anime_name
        self.season = season
        self.episode = episode
        self.quality = quality
        self.language = language

    def get_anie_name(self):
        return self.anime_name

    def get_season(self):
        return self.season

    def get_episode(self):
        return self.episode

    def get_quality(self):
        return self.quality

    def get_language(self):
        return self.language
