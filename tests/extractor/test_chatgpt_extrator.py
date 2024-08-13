from unittest.mock import AsyncMock, patch

import pytest
from alist_mikananirss.extractor import (
    AnimeNameExtractResult,
    ChatGPTExtractor,
    ResourceTitleExtractResult,
)


@pytest.fixture
def chatgpt_extractor():
    with patch("openai.AsyncOpenAI", new=AsyncMock()):
        yield ChatGPTExtractor("fake_api_key")


@pytest.mark.asyncio
async def test_analyse_anime_name_success(chatgpt_extractor):
    mock_response = '```json\n{"anime_name": "Test Anime", "season": 2}\n```'

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        result = await chatgpt_extractor.analyse_anime_name("Test Anime Season 2")

        assert isinstance(result, AnimeNameExtractResult)
        assert result.anime_name == "Test Anime"
        assert result.season == 2


@pytest.mark.asyncio
async def test_analyse_anime_name_invalid_json(chatgpt_extractor):
    mock_response = "Invalid JSON response"

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        with pytest.raises(ValueError, match="Can't parse GPT responese as a json"):
            await chatgpt_extractor.analyse_anime_name("Test Anime Season 2")


@pytest.mark.asyncio
async def test_analyse_anime_name_wrong_type(chatgpt_extractor):
    mock_response = '```json\n{"anime_name": "Test Anime", "season": "4"}\n```'

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        with pytest.raises(TypeError, match="GPT provide a wrong type data"):
            await chatgpt_extractor.analyse_anime_name("Test Anime Season 2")


@pytest.mark.asyncio
async def test_analyse_resource_title_success(chatgpt_extractor):
    mock_response = """
    ```json
    {
        "anime_name_cn": "测试番剧",
        "anime_name_jp": "测试番剧",
        "anime_name_en": "Test Anime",
        "season": 2,
        "episode": 1,
        "quality": "1080p",
        "fansub": "kuonji alice My wife",
        "language": "简体中文",
        "version": 2
    }
    ```
    """

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        result = await chatgpt_extractor.analyse_resource_title(
            "[kuonji alice My wife] 测试番剧 第二季 / Test Anime S2 - 01 [1080p][简体]"
        )

        assert isinstance(result, ResourceTitleExtractResult)
        assert result.anime_name == "测试番剧"
        assert result.season == 2
        assert isinstance(result.episode, int)
        assert result.episode == 1
        assert result.quality == "1080p"
        assert result.fansub == "kuonji alice My wife"
        assert result.language == "简体中文"
        assert result.version == 2


@pytest.mark.asyncio
async def test_analyse_resource_title_special_episode(chatgpt_extractor):
    mock_response = """```json
    {
        "anime_name_cn": "测试番剧",
        "anime_name_jp": "测试番剧",
        "anime_name_en": "Test Anime",
        "season": 0,
        "episode": 1.5,
        "quality": "720p",
        "fansub": "kuonji alice My wife",
        "language": "简体中文",
        "version": 1
    }
    ```"""

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        result = await chatgpt_extractor.analyse_resource_title(
            "[kuonji alice My wife] 测试番剧 第二季 / Test Anime S2 - 1.5 [720p][简体]"
        )

        assert isinstance(result, ResourceTitleExtractResult)
        assert result.anime_name == "测试番剧"
        assert result.season == 0
        assert isinstance(result.episode, int)
        assert result.episode == 0
        assert result.quality == "720p"
        assert result.fansub == "kuonji alice My wife"
        assert result.language == "简体中文"
        assert result.version == 1


@pytest.mark.asyncio
async def test_analyse_resource_title_invalid_json(chatgpt_extractor):
    mock_response = "Invalid JSON response"

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        with pytest.raises(ValueError, match="Can't parse GPT responese as a json"):
            await chatgpt_extractor.analyse_resource_title(
                "[kuonji alice My wife] 测试番剧 第二季 / Test Anime S2 - 01 [1080p][简体]"
            )


@pytest.mark.asyncio
async def test_analyse_resource_title_wrong_type(chatgpt_extractor):
    mock_response = """```json
    {
        "anime_name_cn": "测试番剧",
        "anime_name_jp": "测试番剧",
        "anime_name_en": "Test Anime",
        "season": "2",
        "episode": 1,
        "quality": "1080p",
        "fansub": "kuonji alice My wife",
        "language": "简体中文",
        "version": 2
    }
    ```"""

    with patch.object(
        chatgpt_extractor, "_get_gpt_response", new_callable=AsyncMock
    ) as mock_get_response:
        mock_get_response.return_value = mock_response

        with pytest.raises(TypeError, match="GPT provide a wrong type data"):
            await chatgpt_extractor.analyse_resource_title(
                "[kuonji alice My wife] 测试番剧 第二季 / Test Anime S2 - 01 [1080p][简体]"
            )
