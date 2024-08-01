import pytest
from alist_mikananirss.core.filters import RegexFilter  # 请替换为实际的模块名


@pytest.fixture
def regex_filter():
    return RegexFilter()


@pytest.fixture
def test_resources():
    resoureces = [
        "★10月新番★[葬送的芙莉莲 / Sousou no Frieren][06][1080p][简日双语][招募翻译] [709.7MB]",
        "[白圣女与黑牧师_Shiro Seijo to Kuro Bokushi][12][x264 1080p][CHS]",
        "★07月新番[彻夜之歌][01-13(全集)][1080P][繁体][MP4]",
        "葬送的芙莉莲 / Sousou no Frieren [08][WebRip][1080p][HEVC_AAC][繁日内嵌]",
        "[彻夜之歌 / Yofukashi no Uta][修正合集][繁日双语][1080P][WEBrip][MP4]（急招校对、后期）",
        "[ANi] Undead Unluck / 不死不运 - 14 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4] [567.96 MB]",
        "【悠哈璃羽字幕社】[异种族风俗娘评鉴指南_Ishuzoku Rebyuazu][01-12][x264][CHT][AT-X 1280x720]",
        "[GJ.Y] 我内心的糟糕念头 第二季 / Boku no Kokoro no Yabai Yatsu Season 2 - 14 (Baha 1920x1080 AVC AAC MP4)",
        "[喵萌奶茶屋&LoliHouse] 僵尸100 ~变成僵尸前想要完成的100件事~ / Zom 100: Zombie ni Naru made ni Shitai 100 no Koto [01-12 精校合集][WebRip 1080p HEVC-10bit AAC][简繁日内封字幕][Fin]",
    ]
    return resoureces


def test_init():
    rf = RegexFilter(["简体", "1080p"])
    assert len(rf.patterns) == 2


def test_update_regex(regex_filter):
    regex_filter.update_regex({"新模式": r"测试"})
    assert "新模式" in regex_filter._default_patterns
    assert regex_filter._default_patterns["新模式"] == r"测试"


def test_add_pattern(regex_filter):
    regex_filter.add_pattern("简体")
    assert len(regex_filter.patterns) == 1


def test_add_invalid_pattern(regex_filter):
    with pytest.raises(KeyError):
        regex_filter.add_pattern("UnexistPattern")


def test_filt_single(regex_filter):
    regex_filter.add_pattern("简体")
    regex_filter.add_pattern("1080p")
    assert regex_filter.filt_single("简体中文1080P版本")
    assert not regex_filter.filt_single("繁体中文720P版本")


def test_filt_list(regex_filter, test_resources):
    regex_filter.add_pattern("简体")
    regex_filter.add_pattern("1080p")
    regex_filter.add_pattern("非合集")
    result = regex_filter.filt_list(test_resources)
    assert result == [0, 1]


def test_non_collection_filter(test_resources):
    rf = RegexFilter(["非合集"])
    result = rf.filt_list(test_resources)
    assert result == [0, 1, 3, 5, 7]


def test_multiple_patterns(test_resources):
    rf = RegexFilter(["简体", "1080p", "非合集"])
    result = rf.filt_list(test_resources)
    assert result == [0, 1]
