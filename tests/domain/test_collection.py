import pytest

from openlist_ani.domain.policies import title_exclusion_reason


@pytest.mark.parametrize(
    "title",
    [
        "[Sakurato] Anime Title 合集 [BDRip]",
        "Anime 01-24 [1080p]",
        "Show S01E01-E12",
    ],
)
def test_collection_release_titles_are_excluded(title):
    assert title_exclusion_reason(title, []) is not None


@pytest.mark.parametrize(
    "title",
    [
        "[Sakurato] Anime Title - 01 [1080p]",
        "Show S01E05 1080p",
        "[ANi] Show Season 2 - 18 [1080P][CHT][MP4]",
    ],
)
def test_single_episode_release_titles_are_not_excluded(title):
    assert title_exclusion_reason(title, []) is None
