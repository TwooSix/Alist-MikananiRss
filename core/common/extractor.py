import re

import yaml
from openai import OpenAI


class ChatGPT:
    def __init__(self, api_key, base_url=None, model="gpt-3.5-turbo") -> None:
        self.client = OpenAI(
            api_key=api_key,
        )
        if base_url:
            self.client.base_url = base_url
        self.model = model

    # def analyse_anime_name(self, anime_name: str):
    #     # 不准确，弃用
    #     prompt = """
    #     你是一个执行命令并准确的返回执行结果的程序，当我给出指定内容时，你会按照我的要求返回指定格式的内容。
    #     后续我将会给你提供一个番剧的名字，请你根据番剧名字，识别出番剧当前是第几季，以整型数字的形式存储在season字段中（不能是中文），若是番外篇，则值为0，若没有特殊说明，则是第一季，即值为1；获取番剧的真实名字(去除掉第几季)，以字符串的形式存储在name字段中，并以YAML的格式返回。YAML具体格式如下(注意值的类型必须严格按照我以上提到的类型填写)：
    #     ```yaml
    #     name:
    #     season:
    #     ```
    #     """
    #     chat_completion = self.client.chat.completions.create(
    #         messages=[
    #             {"role": "system", "content": prompt},
    #             {"role": "user", "content": anime_name},
    #         ],
    #         model=self.model,
    #     )
    #     resp = chat_completion.choices[0].message.content
    #     pattern = r"```yaml\n(.*?)\n```"
    #     match = re.search(pattern, resp, re.DOTALL)
    #     if match:
    #         yaml_content = match.group(1)
    #         data = yaml.load(yaml_content, Loader=yaml.FullLoader)
    #         # 类型检查
    #         if not isinstance(data["name"], str):
    #             return None
    #         elif not isinstance(data["season"], int):
    #             return None
    #         return data
    #     return None

    def analyse_resource_name(self, resource_name: str):
        prompt = """
        你是一个执行命令并准确的返回执行结果的程序，当我给出指定内容时，你会按照我的要求返回指定格式的内容。
        后续我将会给你提供一个番剧的资源名字，请你根据番剧名字，提取出字幕组名称，类型为string，存储在fansub字段中；番剧的集数，类型为int，存储在episode字段中；番剧的清晰度，类型为string，以"xP"的格式存储在quality字段中，例如"1920x1080"请重命名为"1080P"。最后以YAML的格式返回。YAML具体格式如下：
        ```yaml
        fansub:
        episode:
        quality:
        ```
        """
        chat_completion = self.client.chat.completions.create(
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
            elif not isinstance(data["episode"], int):
                raise TypeError(
                    f"Chatgpt provide a wrong type of episode: {data['episode']}"
                )
            elif not isinstance(data["quality"], str):
                raise TypeError(
                    f"Chatgpt provide a wrong type of quality: {data['quality']}"
                )
            return data
        return None


class Regex:
    def __init__(self) -> None:
        pass

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

    def analyse_anime_name(self, anime_name: str):
        # 从番剧名字中提取番剧名字和季数
        pattern = r"(.+) 第(.+)[季|期]"
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
