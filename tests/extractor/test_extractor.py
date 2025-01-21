from unittest.mock import AsyncMock

import pytest

from alist_mikananirss.extractor import Extractor, ExtractorBase


@pytest.fixture(autouse=True)
def reset_extractor():
    Extractor.destroy_instance()


def test_initialize():
    mock_extractor = AsyncMock(spec=ExtractorBase)
    Extractor.initialize(mock_extractor)
    extractor = Extractor()
    assert extractor._extractor == mock_extractor


def test_set_extractor():
    mock_extractor1 = AsyncMock(spec=ExtractorBase)
    Extractor.initialize(mock_extractor1)
    m = Extractor()
    assert m._extractor == mock_extractor1
    mock_extractor2 = AsyncMock(spec=ExtractorBase)
    m.set_extractor(mock_extractor2)
    assert m._extractor == mock_extractor2


@pytest.mark.asyncio
async def test_not_initialized():
    extractor = Extractor()
    try:
        await extractor.analyse_anime_name("anime_name")
    except RuntimeError as e:
        assert str(e) == "Extractor is not initialized"
    try:
        await extractor.analyse_resource_title("resource_name")
    except RuntimeError as e:
        assert str(e) == "Extractor is not initialized"
