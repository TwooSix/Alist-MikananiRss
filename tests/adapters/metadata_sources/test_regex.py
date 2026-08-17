import json
from pathlib import Path

import pytest

from openlist_ani.adapters.metadata_sources.regex import (
    RegexTitleExtractEngine,
)
from openlist_ani.application.collection import child_release_title
from openlist_ani.domain import ReleaseMetadata, VideoQuality

FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "metadata_parser"
    / "regex_manual_cases.jsonl"
)


def _load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["title"])
async def test_regex_engine_parses_manual_release_title_cases(case: dict):
    engine = RegexTitleExtractEngine()

    result = (await engine.parse_titles([case["title"]]))[0]

    assert result.release_title == case["title"]
    if not case["expect_success"]:
        assert result.success is False
        assert case["error_contains"] in (result.error or "")
        return

    assert result.success is True
    assert result.result is not None
    parsed = result.result.model_dump()
    assert parsed == {
        **case["expected"],
        "tmdb_id": None,
    }


async def test_collection_sparse_titles_remain_parseable_with_release_metadata():
    parent = ReleaseMetadata(anime_name="Example", season=1)
    paths = [
        "01 [1080p].mkv",
        "[Better] 02 [CHS].mkv",
        "E03 v2.mkv",
        "EP04_v3_720p_CHS.mkv",
        "[Group][05][1080p].mkv",
    ]
    titles = [child_release_title(path, parent) for path in paths]

    results = await RegexTitleExtractEngine().parse_titles(titles)

    assert all(result.success and result.result is not None for result in results)
    parsed = [result.result for result in results]
    assert [item.episode for item in parsed] == [1, 2, 3, 4, 5]
    assert [item.version for item in parsed] == [1, 1, 2, 3, 1]
    assert parsed[0].quality == VideoQuality.Q1080P
    assert parsed[1].fansub == "Better"
    assert parsed[3].quality == VideoQuality.Q720P
