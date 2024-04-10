import json
import re

from loguru import logger
from openai import AsyncOpenAI


class ChatGPT:
    def __init__(self, api_key, base_url=None, model="gpt-3.5-turbo") -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
        )
        if base_url:
            self.client.base_url = base_url
        self.model = model

    async def analyse_anime_name(self, resource_name: str):
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
            # 类型检查
            if not (isinstance(data["anime_name"], str)):
                raise TypeError(
                    f"Chatgpt provide a wrong type of anime_name: {data['anime_name']}"
                )
            elif not isinstance(data["season"], int):
                raise TypeError(
                    f"Chatgpt provide a wrong type of season: {data['season']}"
                )
            logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {data}")
            return data
        else:
            raise ValueError(f"Chatgpt provide a wrong format response: {resp}")

    async def analyse_resource_name(self, resource_name: str):
        prompt = """
        后续我将会给你提供一个番剧的资源名字，请你根据资源的名字，提取出番剧的集数；番剧的清晰度，以"xp"的格式存储，例如"1920x1080"请重命名为"1080p"
        我需要将这段文本解析成一个数据结构，以便初始化我的代码中的一个MikanAnimeResource类。MikanAnimeResource类的定义如下：

        class MikanAnimeResource{
            float episode;
            String quality;
            
            MikanAnimeResource(this.episode, this.quality);
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
                data["season"] = 0
            else:
                data["episode"] = int(data["episode"])
            data["quality"] = data["quality"].lower()
            logger.debug(f"Chatgpt analyse resource name: {resource_name} -> {data}")
            return data
        else:
            raise ValueError(f"Chatgpt provide a wrong format response: {resp}")


class Regex:
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

    def analyse_anime_name(self, anime_name: str) -> dict:
        # 去除名字中的"第x部分"(因为这种情况一般是分段播出，而非新的一季)
        part_pattern = r"\s*第(.+)部分"
        anime_name = re.sub(part_pattern, "", anime_name)
        # 从番剧名字中提取番剧名字和季数
        season_pattern = r"(.+) 第(.+)[季期]"
        match = re.search(season_pattern, anime_name)
        if match:
            name = match.group(1)
            name = name.strip()
            try:
                season = int(match.group(2))
            except ValueError:
                season = self.__chinese_to_arabic(match.group(2))
            return {"name": name, "season": season}
        # 根据罗马数字判断季数(如：无职转生Ⅱ ～到了异世界就拿出真本事～)
        roman_season_pattern = r"\s*([ⅠⅡⅢⅣⅤ])\s*"
        roman_numerals = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"]
        match = re.search(roman_season_pattern, anime_name)
        if match:
            season = roman_numerals.index(match.group(1)) + 1
            name = re.sub(roman_season_pattern, "", anime_name)
            return {"name": name, "season": season}
        # 默认为第一季
        return {"name": anime_name, "season": 1}

    async def analyse_resource_name(self, resource_name: str):
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
        data = {"episode": episode}
        # 是否总集篇(集数为浮点数)
        is_special = data["episode"] != int(data["episode"])
        if is_special:
            data["season"] = 0
        else:
            data["episode"] = int(data["episode"])
        logger.debug(f"Regex analyse resource name: {resource_name} -> {data}")
        return data
