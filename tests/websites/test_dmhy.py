from unittest.mock import patch

import feedparser
import pytest

from alist_mikananirss.extractor import ResourceTitleExtractResult, VideoQuality
from alist_mikananirss.websites import FeedEntry, ResourceInfo
from alist_mikananirss.websites.dmhy import Dmhy


@pytest.fixture
def dmhy():
    return Dmhy("https://dmhy.org/topics/rss/rss.xml")


@pytest.fixture
def mock_rss_data():
    return """<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:wfw="http://wellformedweb.org/CommentAPI/" version="2.0">
<channel>
<title>
<![CDATA[ 動漫花園資源網 ]]>
</title>
<link>http://share.dmhy.org</link>
<description>
<![CDATA[ 動漫花園資訊網是一個動漫愛好者交流的平台,提供最及時,最全面的動畫,漫畫,動漫音樂,動漫下載,BT,ED,動漫遊戲,資訊,分享,交流,讨论. ]]>
</description>
<language>zh-cn</language>
<pubDate>Wed, 15 Jan 2025 16:57:29 +0800</pubDate>
<item>
<title>
<![CDATA[ [LoliHouse] 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～ / Kinomi Master - 03 [WebRip 1080p HEVC-10bit AAC][无字幕] ]]>
</title>
<link>http://share.dmhy.org/topics/view/687329_LoliHouse_Kinomi_Master_-_03_WebRip_1080p_HEVC-10bit_AAC.html</link>
<pubDate>Wed, 15 Jan 2025 15:09:14 +0800</pubDate>
<description>
<![CDATA[ <p> <img src="https://s2.loli.net/2025/01/09/fmJhiyGrFea8ogl.webp" /><br /> </p> <p> <br /> </p> <p> <strong> 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～<br /> Hazure Skill "Kinomi Master": Skill no Mi (Tabetara Shinu) wo Mugen ni Taberareru You ni Natta Ken ni Tsuite<br /> 外れスキル《木の実マスター》 ～スキルの実（食べたら死ぬ）を無限に食べられるようになった件について～<br /> </strong> </p> <p> <br /> </p> <p> <strong> 字幕：没有<br /> 脚本：S01T004721<br /> 压制：帕鲁奇亚籽<br /> 本片版权字幕质量堪忧，有试看需求请自行前往<a href="https://t.me/anime_chinese_subtitles" target="_blank" rel="external nofollow">获取</a>。<br /> </strong> </p> <p> <br /> </p> <hr /> <p> <br /> </p> <p> <strong> 本组作品首发于： <a href="https://nyaa.si/?f=0&c=0_0&q=lolihouse" target="_blank" rel="external nofollow">nyaa.si</a> </strong> </p> <p> <strong> 另备份发布于： <a href="https://acg.rip/?term=LoliHouse" target="_blank" rel="external nofollow">acg.rip</a> | <a href="https://share.dmhy.org/topics/list?keyword=lolihouse" target="_blank" rel="external nofollow">dmhy.org</a> | <a href="https://bangumi.moe/search/581be821ee98e9ca20730eae" target="_blank" rel="external nofollow">bangumi.moe</a> | <a href="https://share.acgnx.se/team-135-1.html" target="_blank" rel="external nofollow">acgnx.se</a> </strong> </p> <p> <strong>备份发布情况取决于各站点可用性，如有缺失烦请移步其他站点下载。</strong><br /> </p> <p> <strong>其余站点系自发抓取非我组正式发布。</strong><br /> </p> <p> <br /> </p> <hr /> <p> <br /> </p> <p> <strong>为了顺利地观看我们的作品，推荐大家使用以下播放器：</strong> </p> <p> <strong>Windows：<a href="https://mpv.io/" target="_... ]]>
</description>
<enclosure url="magnet:?xt=urn:btih:WJBPAWPQKWDXUJKQB4EIPP24RAQGRSEM&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce&tr=https%3A%2F%2Ftr.bangumi.moe%3A9696%2Fannounce&tr=http%3A%2F%2Ft.acg.rip%3A6699%2Fannounce&tr=http%3A%2F%2Fopen.acgnxtracker.com%2Fannounce&tr=http%3A%2F%2Fshare.camoe.cn%3A8080%2Fannounce&tr=https%3A%2F%2Ftracker.nanoha.org%2Fannounce" length="1" type="application/x-bittorrent"/>
<author>
<![CDATA[ LoliHouse ]]>
</author>
<guid isPermaLink="true">http://share.dmhy.org/topics/view/687329_LoliHouse_Kinomi_Master_-_03_WebRip_1080p_HEVC-10bit_AAC.html</guid>
<category domain="http://share.dmhy.org/topics/list/sort_id/2">
<![CDATA[ 動畫 ]]>
</category>
</item>
</channel>
</rss>"""


@pytest.mark.asyncio
async def test_get_feed_entries(dmhy, mock_rss_data):
    with patch.object(dmhy, "parse_feed", return_value=feedparser.parse(mock_rss_data)):
        result = await dmhy.get_feed_entries()

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result.pop()
    assert isinstance(entry, FeedEntry)
    assert (
        entry.resource_title
        == "[LoliHouse] 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～ / Kinomi Master - 03 [WebRip 1080p HEVC-10bit AAC][无字幕]"
    )
    assert (
        entry.torrent_url
        == "magnet:?xt=urn:btih:WJBPAWPQKWDXUJKQB4EIPP24RAQGRSEM&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce&tr=https%3A%2F%2Ftr.bangumi.moe%3A9696%2Fannounce&tr=http%3A%2F%2Ft.acg.rip%3A6699%2Fannounce&tr=http%3A%2F%2Fopen.acgnxtracker.com%2Fannounce&tr=http%3A%2F%2Fshare.camoe.cn%3A8080%2Fannounce&tr=https%3A%2F%2Ftracker.nanoha.org%2Fannounce"
    )
    assert (
        entry.homepage_url
        == "http://share.dmhy.org/topics/view/687329_LoliHouse_Kinomi_Master_-_03_WebRip_1080p_HEVC-10bit_AAC.html"
    )
    assert entry.author == "LoliHouse"


@pytest.mark.asyncio
async def test_get_feed_entries_real(dmhy):
    # 测试真实的RSS链接解析是否有报错
    await dmhy.get_feed_entries()


@pytest.mark.asyncio
async def test_parse_homepage_error(dmhy):
    # 非强需求；不报错
    mock_entry = FeedEntry(
        resource_title="[LoliHouse] 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～ / Kinomi Master - 03 [WebRip 1080p HEVC-10bit AAC][无字幕] ]",
        torrent_url="magnet:?xt=urn:btih:WJBPAWPQKWDXUJKQB4EIPP24RAQGRSEM&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce&tr=https%3A%2F%2Ftr.bangumi.moe%3A9696%2Fannounce&tr=http%3A%2F%2Ft.acg.rip%3A6699%2Fannounce&tr=http%3A%2F%2Fopen.acgnxtracker.com%2Fannounce&tr=http%3A%2F%2Fshare.camoe.cn%3A8080%2Fannounce&tr=https%3A%2F%2Ftracker.nanoha.org%2Fannounce",
        author="LoliHouse",
    )
    with patch.object(dmhy, "parse_homepage", side_effect=Exception):
        await dmhy.extract_resource_info(mock_entry, use_extractor=False)


@pytest.mark.asyncio
async def test_none_fansub(dmhy):
    # 无法从主页解析到fansub，使用extractor解析的fansub结果
    mock_entry = FeedEntry(
        resource_title="[LoliHouse] 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～ / Kinomi Master - 03 [WebRip 1080p HEVC-10bit AAC][无字幕] ]",
        torrent_url="magnet:?xt=urn:btih:WJBPAWPQKWDXUJKQB4EIPP24RAQGRSEM&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce&tr=https%3A%2F%2Ftr.bangumi.moe%3A9696%2Fannounce&tr=http%3A%2F%2Ft.acg.rip%3A6699%2Fannounce&tr=http%3A%2F%2Fopen.acgnxtracker.com%2Fannounce&tr=http%3A%2F%2Fshare.camoe.cn%3A8080%2Fannounce&tr=https%3A%2F%2Ftracker.nanoha.org%2Fannounce",
        author="LoliHouse",
    )
    mock_extract_result = ResourceTitleExtractResult(
        anime_name="最弱技能《果实大师》",
        season=1,
        episode=3,
        quality=VideoQuality.p1080,
        language="日语",
        fansub="LoliHouse",
        version=1,
    )

    with patch.object(dmhy, "parse_homepage", return_value=None):
        with patch(
            "alist_mikananirss.extractor.Extractor.analyse_resource_title",
            return_value=mock_extract_result,
        ):
            result = await dmhy.extract_resource_info(mock_entry, use_extractor=True)

    assert isinstance(result, ResourceInfo)
    assert result.fansub == "LoliHouse"


@pytest.mark.asyncio
async def test_homepage_fansub(dmhy):
    # 从主页解析得到fansub，使用主页解析的fansub结果

    mock_entry = FeedEntry(
        resource_title="[LoliHouse] 最弱技能《果实大师》 ～关于能无限食用技能果实（吃了就会死）这件事～ / Kinomi Master - 03 [WebRip 1080p HEVC-10bit AAC][无字幕] ]",
        torrent_url="magnet:?xt=urn:btih:WJBPAWPQKWDXUJKQB4EIPP24RAQGRSEM&dn=&tr=http%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=udp%3A%2F%2F104.143.10.186%3A8000%2Fannounce&tr=http%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=http%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ftracker.publicbt.com%3A80%2Fannounce&tr=http%3A%2F%2Ftracker.prq.to%2Fannounce&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce&tr=https%3A%2F%2Ft-115.rhcloud.com%2Fonly_for_ylbud&tr=http%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=http%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker1.itzmx.com%3A8080%2Fannounce&tr=udp%3A%2F%2Ftracker2.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker3.itzmx.com%3A6961%2Fannounce&tr=udp%3A%2F%2Ftracker4.itzmx.com%3A2710%2Fannounce&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce&tr=https%3A%2F%2Ftr.bangumi.moe%3A9696%2Fannounce&tr=http%3A%2F%2Ft.acg.rip%3A6699%2Fannounce&tr=http%3A%2F%2Fopen.acgnxtracker.com%2Fannounce&tr=http%3A%2F%2Fshare.camoe.cn%3A8080%2Fannounce&tr=https%3A%2F%2Ftracker.nanoha.org%2Fannounce",
        author="LoliHouse",
    )
    mock_extract_result = ResourceTitleExtractResult(
        anime_name="最弱技能《果实大师》",
        season=1,
        episode=3,
        quality=VideoQuality.p1080,
        language="日语",
        fansub="LoliHouse",
        version=1,
    )

    with patch.object(dmhy, "parse_homepage", return_value="homepage_fansub"):
        with patch(
            "alist_mikananirss.extractor.Extractor.analyse_resource_title",
            return_value=mock_extract_result,
        ):
            result = await dmhy.extract_resource_info(mock_entry, use_extractor=True)

    assert isinstance(result, ResourceInfo)
    assert result.fansub == "homepage_fansub"
