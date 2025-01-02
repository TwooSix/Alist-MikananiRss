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
    extractor = Extractor()
    assert extractor._extractor == mock_extractor
