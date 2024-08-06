import re
from functools import lru_cache

from loguru import logger

from .base import ExtractorBase
from .models import AnimeNameExtractResult, ResourceTitleExtractResult


class RegexExtractor(ExtractorBase):
    def __init__(self) -> None:
        self.num_dict: dict[str, int] = {
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
        self.unit_dict: dict[str, int] = {"十": 10, "百": 100, "千": 1000}

        self.part_pattern = re.compile(r"\s*第(.+)部分")
        self.season_pattern = re.compile(r"(.+) 第(.+)[季期]")
        self.roman_season_pattern = re.compile(r"\s*([ⅠⅡⅢⅣⅤ])\s*")
        self.roman_numerals = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5}
        self.episode_pattern = re.compile(r"第?(\d+(?:\.\d+)?)[(?:话|集)]?")

    @lru_cache(maxsize=128)
    def _chinese_to_arabic(self, chinese_num: str) -> int:
        if chinese_num == "十":
            return 10

        result = 0
        temp = 0
        for char in chinese_num:
            if char in self.unit_dict:
                result += (temp or 1) * self.unit_dict[char]
                temp = 0
            else:
                temp = self.num_dict[char]
        return result + temp

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameExtractResult:
        # 去除名字中的"第x部分"(因为这种情况一般是分段播出，而非新的一季)
        anime_name = self.part_pattern.sub("", anime_name)
        match = self.season_pattern.search(anime_name)
        name = None
        season = None
        if match:
            # 根据"第x季"提取季数
            name, season = match.groups()
            season = (
                int(season) if season.isdigit() else self._chinese_to_arabic(season)
            )
        else:
            # 根据罗马数字判断季数(如：无职转生Ⅱ ～到了异世界就拿出真本事～)
            match = self.roman_season_pattern.search(anime_name)
            if match:
                season = self.roman_numerals[match.group(1)]
                name = self.roman_season_pattern.sub("", anime_name)
            else:
                # 默认为第一季
                name = anime_name
                season = 1
        info = AnimeNameExtractResult(anime_name=name, season=int(season))
        logger.debug(f"Regex analyse anime name: {anime_name} -> {info}")
        return info

    async def analyse_resource_title(
        self, resource_title: str
    ) -> ResourceTitleExtractResult:
        clean_name = re.sub(r"[\[\]【】()（）]", " ", resource_title)
        match = self.episode_pattern.search(clean_name)
        if not match:
            raise ValueError(f"Can't find episode number in {resource_title}")
        episode = float(match.group(1))
        # if episode is a decimal, it means that it is a special episode, season = 0
        season = 0 if not episode.is_integer() else None
        episode = int(episode) if episode.is_integer() else 0
        info = ResourceTitleExtractResult(anime_name="", season=season, episode=episode)
        logger.debug(f"Regex analyse resource name: {resource_title} -> {info}")
        return info
