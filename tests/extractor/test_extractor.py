from unittest.mock import AsyncMock

import pytest
from alist_mikananirss.extractor import Extractor, ResourceNameInfo
from alist_mikananirss.websites import ResourceInfo


@pytest.mark.asyncio
async def test_extractor_process():
    mock_chatgpt_extractor = AsyncMock()
    mock_chatgpt_extractor.analyse_resource_name.return_value = ResourceNameInfo(
        episode=3, quality="720p", language="English"
    )

    Extractor.initialize(mock_chatgpt_extractor)

    test_resource_info = ResourceInfo(
        anime_name="Test Anime 第二季",
        resource_title="Test Anime S01E03 720p",
        torrent_url="https://example.com/test.torrent",
        published_date="2022-01-01 00:00:00",
    )

    await Extractor.process(test_resource_info)

    assert test_resource_info.anime_name == "Test Anime"
    assert test_resource_info.season == 2
    assert test_resource_info.episode == 3
    assert test_resource_info.quality == "720p"
    assert test_resource_info.language == "English"


@pytest.mark.asyncio
async def test_extractor_not_initialized():
    Extractor._instance = None
    Extractor._extractor = None

    test_resource_info = ResourceInfo(
        anime_name="Test Anime 第一季",
        resource_title="Test Anime S01E03 720p",
        torrent_url="https://example.com/test.torrent",
        published_date="2022-01-01 00:00:00",
    )

    with pytest.raises(ValueError):
        await Extractor.process(test_resource_info)
