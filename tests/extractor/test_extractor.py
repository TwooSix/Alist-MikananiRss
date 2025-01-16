from unittest.mock import AsyncMock

import pytest

from alist_mikananirss.extractor import Extractor, ExtractorBase


def test_initialize():
    mock_extractor = AsyncMock(spec=ExtractorBase)
    Extractor.initialize(mock_extractor)
    extractor = Extractor()
    assert extractor._extractor == mock_extractor


def test_set_extractor():
    mock_extractor = AsyncMock(spec=ExtractorBase)
    extractor = Extractor()
    extractor.set_extractor(mock_extractor)
    assert extractor._extractor == mock_extractor


@pytest.mark.asyncio
async def test_not_initialized():
    Extractor._instances.pop(Extractor)
    extractor = Extractor()
    try:
        await extractor.analyse_anime_name("anime_name")
    except RuntimeError as e:
        assert str(e) == "Extractor is not initialized"
    try:
        await extractor.analyse_resource_title("resource_name")
    except RuntimeError as e:
        assert str(e) == "Extractor is not initialized"
