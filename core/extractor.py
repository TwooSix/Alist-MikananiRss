import re

import yaml
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

    async def analyse_resource_name(self, resource_name: str):
        prompt = """
        你是一个执行命令并准确的返回执行结果的程序，当我给出指定内容时，你会按照我的要求返回指定格式的内容。
        后续我将会给你提供一个番剧的资源名字，请你根据番剧名字，提取出字幕组名称，类型为string，存储在fansub字段中；番剧的季度，类型为int，存储在season字段中，如果是OVA篇/总集篇则季度设置为0（总集篇通常集数为浮点数），没有特别标注的默认为第1季；番剧的集数，类型为float，存储在episode字段中；番剧的清晰度，类型为string，以"xp"的格式存储在quality字段中，例如"1920x1080"请重命名为"1080p"。最后以YAML的格式返回。YAML具体格式如下：
        ```yaml
        fansub:
        season:
        episode:
        quality:
        ```
        """

        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": resource_name},
            ],
            model=self.model,
        )
        resp = chat_completion.choices[0].message.content
        pattern = r"```yaml\n(.*?)\n```"
        match = re.search(pattern, resp, re.DOTALL)
        if match:
            yaml_content = match.group(1)
            data = yaml.load(yaml_content, Loader=yaml.FullLoader)
            # 类型检查
            if not isinstance(data["fansub"], str):
                raise TypeError(
                    f"Chatgpt provide a wrong type of fansub: {data['fansub']}"
                )
            elif not isinstance(data["season"], int):
                raise TypeError(
                    f"Chatgpt provide a wrong type of season: {data['season']}"
                )
            elif not (
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
        # 从番剧名字中提取番剧名字和季数
        pattern = r"(.+) 第(.+)[季期]"
        match = re.search(pattern, anime_name)
        if match:
            name = match.group(1)
            name = name.strip()
            try:
                season = int(match.group(2))
            except ValueError:
                season = self.__chinese_to_arabic(match.group(2))
            return {"name": name, "season": season}
        else:
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
