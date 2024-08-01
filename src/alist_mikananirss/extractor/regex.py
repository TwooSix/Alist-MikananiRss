import re

from loguru import logger

from .base import ExtractorBase
from .models import AnimeNameInfo, ResourceNameInfo


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
            info.set_episode(int(episode))
        logger.debug(f"Regex analyse resource name: {resource_name} -> {info}")

        return info
