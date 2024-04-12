# FILEPATH: /e:/Code/python/Alist-MikananiRss/tests/test_extractor.py


import pytest
from alist_mikananirss.common import initializer
from alist_mikananirss.common.globalvar import config_loader
from alist_mikananirss.extractor.extractor import ChatGPTExtractor, RegexExtractor

initializer.setup_proxy()


class TestChatGpt:
    @pytest.fixture
    def chatgpt(self):
        api_key = config_loader.get("rename.chatgpt.api_key")
        base_url = config_loader.get("rename.chatgpt.base_url")
        model = config_loader.get("rename.chatgpt.model")
        _chatgpt = ChatGPTExtractor(api_key, base_url, model)
        return _chatgpt

    @pytest.fixture
    def resources_info(self):
        _resources_info = {
            "【喵萌奶茶屋】★01月新番★[我内心的糟糕念头 / Boku no Kokoro no Yabai Yatsu][14][1080p][简日双语][招募翻译]": {
                "fansub": "喵萌奶茶屋",
                "season": 1,
                "episode": 14,
                "quality": "1080p",
            },
            "[ANi] Ore Dake Level Up na Ken / 我独自升级 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]": {
                "fansub": "ANi",
                "season": 1,
                "episode": 2,
                "quality": "1080p",
            },
        }
        return _resources_info

    @pytest.mark.asyncio
    async def test_analyse_resource_name(
        self, chatgpt: ChatGPTExtractor, resources_info
    ):
        for resource_name in resources_info:
            result = await chatgpt.analyse_resource_name(resource_name)
            for k, v in result.items():
                if k == "fansub":
                    continue
                assert v == resources_info[resource_name][k]


class TestRegex:
    @pytest.fixture
    def regex_extractor(self):
        return RegexExtractor()

    @pytest.fixture
    def season_info(self):
        _season_info = {
            "间谍过家家 第二季": {"name": "间谍过家家", "season": 2},
            "赛马娘 Pretty Derby": {"name": "赛马娘 Pretty Derby", "season": 1},
            "赛马娘 Pretty Derby 第二季": {"name": "赛马娘 Pretty Derby", "season": 2},
        }
        return _season_info

    @pytest.fixture
    def resources_info(self):
        _resources_info = {
            "[银色子弹字幕组][名侦探柯南][第1116集 千速与重悟的相亲派对（后篇）][V2][繁日双语MP4][1080P]": {
                "episode": 1116,
            },
            "[ANi] Ore Dake Level Up na Ken /  我独自升级 - 07.5 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]": {
                "episode": 7.5,
            },
            "[千夏字幕组][葬送的芙莉莲_Sousou no Frieren][第25话][1080p_AVC][简体][招募新人]": {
                "episode": 25,
            },
        }
        return _resources_info

    @pytest.mark.asyncio
    async def test_analyse_season(self, regex_extractor: RegexExtractor, season_info):
        for name in season_info:
            result = await regex_extractor.analyse_anime_name(name)
            for k, v in result.items():
                assert v == season_info[name][k]

    @pytest.mark.asyncio
    async def test_analyse_resource_name(
        self, regex_extractor: RegexExtractor, resources_info
    ):
        for resource_name in resources_info:
            result = await regex_extractor.analyse_resource_name(resource_name)
            assert result["episode"] == resources_info[resource_name]["episode"]
