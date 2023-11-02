import pytest

from core.common.filters import RegexFilter


class TestRegexFilter:
    @pytest.fixture
    def chs(self):
        chs = [
            (
                "赛马娘 Pretty Derby Season 3 / Uma Musume：Pretty Derby Season 3"
                " [03][1080p][简体内嵌] [544.64 MB]"
            ),
            "★10月新番★[葬送的芙莉莲 / Sousou no Frieren][06][1080p][简日双语][招募翻译] [709.7MB]",
            "[白圣女与黑牧师_Shiro Seijo to Kuro Bokushi][12][x264 1080p][CHS] [复制磁连]",
        ]
        return chs

    @pytest.fixture
    def cht(self):
        cht = [
            "★07月新番[彻夜之歌][01-13(全集)][1080P][繁体][MP4]",
            "星灵感应 / Hoshikuzu Telepath [03][1080p][繁体内嵌]",
            "葬送的芙莉莲 / Sousou no Frieren [08][WebRip][1080p][HEVC_AAC][繁日内嵌] [复制磁连]",
            (
                "16bit 的感动 ANOTHER LAYER - 05 [1080P][Baha][WEB-DL][AAC"
                " AVC][CHT][MP4] [复制磁连]"
            ),
            "[彻夜之歌 / Yofukashi no Uta][修正合集][繁日双语][1080P][WEBrip][MP4]（急招校对、后期） [复制磁连]",
        ]
        return cht

    @pytest.fixture
    def bgm_collection(self):
        bgm_collection = [
            "★07月新番[彻夜之歌][01-13(全集)][1080P][繁体][MP4]",
            "[彻夜之歌 / Yofukashi no Uta][修正合集][繁日双语][1080P][WEBrip][MP4]（急招校对、后期） [复制磁连]",
        ]
        return bgm_collection

    @pytest.fixture
    def p720(self):
        p720 = [
            "16bit的感动 -ANOTHER LAYER- 第03话 MP4 720p [复制磁连]",
        ]
        return p720

    @pytest.fixture
    def string_to_filt(self, chs, cht, bgm_collection, p720):
        string_to_filt = list(set(chs + cht + bgm_collection + p720))
        return string_to_filt

    @pytest.fixture
    def chs_pattern(self):
        pattern = r"(简体|简中|简日|CHS)"
        return pattern

    @pytest.fixture
    def cht_pattern(self):
        pattern = r"(繁体|繁中|繁日|CHT)"
        return pattern

    @pytest.fixture
    def p1080_pattern(self):
        pattern = r"(1080[pP])"
        return pattern

    @pytest.fixture
    def non_collection_pattern(self):
        pattern = r"^((?![合集|全集]).)*$"
        return pattern

    def test_chs_filt(self, chs, string_to_filt, chs_pattern):
        rgx_filter = RegexFilter([chs_pattern])
        idx_after_filt = rgx_filter.filt_list(string_to_filt)
        res = [string_to_filt[i] for i in idx_after_filt]
        res.sort()
        chs.sort()
        assert res == chs

    def test_cht_filt(self, cht, string_to_filt, cht_pattern):
        rgx_filter = RegexFilter([cht_pattern])
        idx_after_filt = rgx_filter.filt_list(string_to_filt)
        res = [string_to_filt[i] for i in idx_after_filt]
        res.sort()
        cht.sort()
        assert res == cht

    def test_p1080_filt(self, p720, string_to_filt, p1080_pattern):
        rgx_filter = RegexFilter([p1080_pattern])
        idx_after_filt = rgx_filter.filt_list(string_to_filt)
        res = [string_to_filt[i] for i in idx_after_filt]
        p1080 = list(set(string_to_filt) - set(p720))
        res.sort()
        p1080.sort()
        assert res == p1080

    def test_non_collection_filt(
        self, bgm_collection, string_to_filt, non_collection_pattern
    ):
        rgx_filter = RegexFilter([non_collection_pattern])
        idx_after_filt = rgx_filter.filt_list(string_to_filt)
        res = [string_to_filt[i] for i in idx_after_filt]
        non_collection_pattern = list(set(string_to_filt) - set(bgm_collection))
        res.sort()
        non_collection_pattern.sort()
        assert res == non_collection_pattern
