# FILEPATH: /e:/Code/python/Alist-MikananiRss/tests/test_extractor.py


import pytest

from core.common import initializer
from core.extractor import ChatGPT, Regex

initializer.setup_proxy()


class TestExtractor:
    @pytest.fixture
    def chatgpt(self):
        _chatgpt = initializer.init_chatgpt_client()
        return _chatgpt

    @pytest.fixture
    def resources_info(self):
        _resources_info = {
            "【喵萌奶茶屋】★01月新番★[我内心的糟糕念头 / Boku no Kokoro no Yabai Yatsu][14][1080p][简日双语][招募翻译]": {
                "fansub": "喵萌奶茶屋",
                "episode": 14,
                "quality": "1080p",
            },
            "[ANi] Ore Dake Level Up na Ken / 我独自升级 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]": {
                "fansub": "ANi",
                "episode": 2,
                "quality": "1080p",
            },
        }
        return _resources_info

    @pytest.mark.asyncio
    async def test_chatgpt_analyse_resource_name(
        self, chatgpt: ChatGPT, resources_info
    ):
        for resource_name in resources_info:
            result = await chatgpt.analyse_resource_name(resource_name)
            for k, v in result.items():
                # 目前来说，除集数外其他信息都不准确
                assert v == resources_info[resource_name][k]


class TestRegex:
    @pytest.fixture
    def regex_extractor(self):
        return Regex()

    @pytest.fixture
    def season_info(self):
        _season_info = {
            "间谍过家家 第二季": {"name": "间谍过家家", "season": 2},
            "赛马娘 Pretty Derby": {"name": "赛马娘 Pretty Derby", "season": 1},
            "赛马娘 Pretty Derby 第二季": {"name": "赛马娘 Pretty Derby", "season": 2},
        }
        return _season_info

    def test_analyse_season(self, regex_extractor: Regex, season_info):
        for name in season_info:
            result = regex_extractor.analyse_anime_name(name)
            for k, v in result.items():
                assert v == season_info[name][k]
