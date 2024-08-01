import pytest
from alist_mikananirss.extractor import AnimeNameInfo, RegexExtractor, ResourceNameInfo

# RegexExtractor tests


@pytest.mark.asyncio
async def test_regex_analyse_anime_name():
    extractor = RegexExtractor()

    result = await extractor.analyse_anime_name("赛马娘 第二季")
    assert isinstance(result, AnimeNameInfo)
    assert result.anime_name == "赛马娘"
    assert result.season == 2

    result = await extractor.analyse_anime_name("无职转生Ⅱ ～到了异世界就拿出真本事～")
    assert result.anime_name == "无职转生～到了异世界就拿出真本事～"
    assert result.season == 2

    result = await extractor.analyse_anime_name("赛马娘")
    assert result.anime_name == "赛马娘"
    assert result.season == 1


@pytest.mark.asyncio
async def test_regex_analyse_resource_name():
    extractor = RegexExtractor()

    result = await extractor.analyse_resource_name(
        "[夜莺家族&YYQ字幕组]New Doraemon 哆啦A梦新番[821][2024.07.27][AVC][1080P][GB_JP]"
    )
    assert isinstance(result, ResourceNameInfo)
    assert result.episode == 821
    assert result.season is None

    result = await extractor.analyse_resource_name(
        "[ANi] Ore Dake Level Up na Ken / 我独自升级 - 07.5 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]"
    )
    assert result.episode == 7.5
    assert result.season == 0  # Special episode

    with pytest.raises(ValueError):
        await extractor.analyse_resource_name("Invalid Resource Name")
