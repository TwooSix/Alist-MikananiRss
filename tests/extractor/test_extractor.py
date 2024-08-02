from unittest.mock import AsyncMock

import pytest
from alist_mikananirss.extractor import Extractor, ExtractorBase, RegexExtractor


@pytest.fixture
def mock_extractor():
    return AsyncMock(spec=ExtractorBase)


@pytest.fixture
def mock_regex_extractor():
    return AsyncMock(spec=RegexExtractor)


def test_initialize():
    mock_extractor = AsyncMock(spec=ExtractorBase)
    Extractor.initialize(mock_extractor)
    assert Extractor._extractor == mock_extractor


def test_get_instance_without_initialization():
    Extractor._instance = None
    with pytest.raises(ValueError):
        Extractor.get_instance()


def test_get_instance_after_initialization(mock_extractor):
    Extractor.initialize(mock_extractor)
    instance = Extractor.get_instance()
    assert isinstance(instance, Extractor)


def test_multiple_initializations():
    # Test behavior with multiple initializations
    mock_extractor1 = AsyncMock(spec=ExtractorBase)
    mock_extractor2 = AsyncMock(spec=ExtractorBase)

    Extractor.initialize(mock_extractor1)
    first_instance = Extractor.get_instance()

    Extractor.initialize(mock_extractor2)
    second_instance = Extractor.get_instance()

    assert first_instance is second_instance
    assert Extractor._extractor == mock_extractor2


@pytest.mark.asyncio
async def test_analyse_resource_title_without_initialization():
    # Test analyse_resource_title when not initialized
    Extractor._instance = None
    Extractor._extractor = None

    with pytest.raises(ValueError):
        await Extractor.analyse_resource_title("Test")
