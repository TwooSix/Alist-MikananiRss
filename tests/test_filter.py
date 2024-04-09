from enum import Enum

import pytest
from alist_mikananirss.filters import RegexFilter


class ResourceTag(Enum):
    CHS = "chs"
    CHT = "cht"
    P1080 = "1080p"
    P720 = "720p"
    COLLECTION = "collection"


class TestRegexFilter:
    @pytest.fixture
    def resources(self):
        _resources = {
            "★10月新番★[葬送的芙莉莲 / Sousou no Frieren][06][1080p][简日双语][招募翻译] [709.7MB]": [
                ResourceTag.CHS,
                ResourceTag.P1080,
            ],
            "[白圣女与黑牧师_Shiro Seijo to Kuro Bokushi][12][x264 1080p][CHS]": [
                ResourceTag.CHS,
                ResourceTag.P1080,
            ],
            "★07月新番[彻夜之歌][01-13(全集)][1080P][繁体][MP4]": [
                ResourceTag.CHT,
                ResourceTag.P1080,
                ResourceTag.COLLECTION,
            ],
            "葬送的芙莉莲 / Sousou no Frieren [08][WebRip][1080p][HEVC_AAC][繁日内嵌]": [
                ResourceTag.CHT,
                ResourceTag.P1080,
            ],
            "[彻夜之歌 / Yofukashi no Uta][修正合集][繁日双语][1080P][WEBrip][MP4]（急招校对、后期）": [
                ResourceTag.CHT,
                ResourceTag.P1080,
                ResourceTag.COLLECTION,
            ],
            "[ANi] Undead Unluck / 不死不运 - 14 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4] [567.96 MB]": [
                ResourceTag.CHT,
                ResourceTag.P1080,
            ],
            "【悠哈璃羽字幕社】[异种族风俗娘评鉴指南_Ishuzoku Rebyuazu][01-12][x264][CHT][AT-X 1280x720]": [
                ResourceTag.CHT,
                ResourceTag.P720,
                ResourceTag.COLLECTION,
            ],
            "[GJ.Y] 我内心的糟糕念头 第二季 / Boku no Kokoro no Yabai Yatsu Season 2 - 14 (Baha 1920x1080 AVC AAC MP4)": [
                ResourceTag.CHT,
                ResourceTag.P1080,
            ],
            "[喵萌奶茶屋&LoliHouse] 僵尸100 ~变成僵尸前想要完成的100件事~ / Zom 100: Zombie ni Naru made ni Shitai 100 no Koto [01-12 精校合集][WebRip 1080p HEVC-10bit AAC][简繁日内封字幕][Fin]": [
                ResourceTag.P1080,
                ResourceTag.COLLECTION,
            ],
        }
        return _resources

    def test_chs_filt(self, resources):
        resources_name = list(resources.keys())
        chs = [name for name, tag in resources.items() if ResourceTag.CHS in tag]
        rgx_filter = RegexFilter(["简体"])
        idx_after_filt = rgx_filter.filt_list(resources_name)
        res = [resources_name[i] for i in idx_after_filt]
        for each in chs:
            assert each in res

    def test_cht_filt(self, resources):
        resources_name = list(resources.keys())
        cht = [name for name, tag in resources.items() if ResourceTag.CHT in tag]
        rgx_filter = RegexFilter(["繁体"])
        idx_after_filt = rgx_filter.filt_list(resources_name)
        res = [resources_name[i] for i in idx_after_filt]
        for each in cht:
            assert each in res

    def test_p1080_filt(self, resources):
        resources_name = list(resources.keys())
        p1080 = [name for name, tag in resources.items() if ResourceTag.P1080 in tag]
        rgx_filter = RegexFilter(["1080p"])
        idx_after_filt = rgx_filter.filt_list(resources_name)
        res = [resources_name[i] for i in idx_after_filt]
        for each in p1080:
            assert each in res

    def test_non_collection_filt(self, resources):
        resources_name = list(resources.keys())
        non_collection = [
            name for name, tag in resources.items() if ResourceTag.COLLECTION not in tag
        ]
        rgx_filter = RegexFilter(["非合集"])
        idx_after_filt = rgx_filter.filt_list(resources_name)
        res = [resources_name[i] for i in idx_after_filt]
        for each in non_collection:
            assert each in res
