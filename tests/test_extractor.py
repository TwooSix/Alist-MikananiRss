# FILEPATH: /e:/Code/python/Alist-MikananiRss/tests/test_extractor.py


import pytest
from alist_mikananirss.common import initializer
from alist_mikananirss.common.globalvar import config_loader
from alist_mikananirss.extractor.extractor import (
    ChatGPTExtractor,
    Extractor,
    RegexExtractor,
)

initializer.setup_proxy()

resources_info = [
    {
        "anime_name": "我心里危险的东西",
        "resource_name": "【喵萌奶茶屋】★01月新番★[我内心的糟糕念头 / Boku no Kokoro no Yabai Yatsu][14][1080p][简日双语][招募翻译]",
        "season": 1,
        "episode": 14,
    },
    {
        "anime_name": "我独自升级",
        "resource_name": "[ANi] Ore Dake Level Up na Ken / 我独自升级 - 02 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
        "season": 1,
        "episode": 2,
    },
    {
        "anime_name": "名侦探柯南",
        "resource_name": "[银色子弹字幕组][名侦探柯南][第1116集 千速与重悟的相亲派对（后篇）][V2][繁日双语MP4][1080P]",
        "season": 1,
        "episode": 1116,
    },
    {
        "anime_name": "我独自升级",
        "resource_name": "[ANi] Ore Dake Level Up na Ken /  我独自升级 - 07.5 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
        "season": 0,
        "episode": 7.5,
    },
    {
        "anime_name": "葬送的芙莉莲",
        "resource_name": "[千夏字幕组][葬送的芙莉莲_Sousou no Frieren][第25话][1080p_AVC][简体][招募新人]",
        "season": 1,
        "episode": 25,
    },
]


class TestExtractor:
    @pytest.fixture
    def gpt_extractor(self):
        api_key = config_loader.get("rename.chatgpt.api_key")
        base_url = config_loader.get("rename.chatgpt.base_url")
        model = config_loader.get("rename.chatgpt.model")
        _chatgpt = ChatGPTExtractor(api_key, base_url, model)
        return _chatgpt

    @pytest.fixture
    def regex_extractor(self):
        return RegexExtractor()

    @pytest.mark.asyncio
    async def test_gpt(self, gpt_extractor):
        extractor = Extractor(gpt_extractor)
        for real_info in resources_info:
            pred_info = await extractor.extract(
                real_info["anime_name"], real_info["resource_name"]
            )
            assert real_info["season"] == pred_info.season
            assert real_info["episode"] == pred_info.episode

    @pytest.mark.asyncio
    async def test_regex(self, regex_extractor):
        extractor = Extractor(regex_extractor)
        for real_info in resources_info:
            pred_info = await extractor.extract(
                real_info["anime_name"], real_info["resource_name"]
            )
            assert real_info["season"] == pred_info.season
            assert real_info["episode"] == pred_info.episode
