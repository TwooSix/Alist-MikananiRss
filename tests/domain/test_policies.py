import pytest

from openlist_ani.domain import LanguageType, ReleaseMetadata, VideoQuality
from openlist_ani.domain.policies import (
    collection_title_reason,
    dominated_by_records,
    is_version_upgrade,
    metadata_exclusion_reason,
    title_exclusion_reason,
)


def _metadata(**overrides):
    values = {
        "anime_name": "Test Anime",
        "season": 1,
        "episode": 1,
        "fansub": "Sub_A",
        "quality": VideoQuality.Q1080P,
        "languages": [LanguageType.CHS],
        "version": 1,
    }
    values.update(overrides)
    return ReleaseMetadata(**values)


def test_title_policy_rejects_collection_but_accepts_single_episode():
    assert title_exclusion_reason("Anime 01-24 [1080p]", [])
    assert title_exclusion_reason("[Group] Show Complete BDRip", [])
    assert title_exclusion_reason("Show S02 - 14 [1080p]", []) is None
    assert title_exclusion_reason("The Bad Batch - 01", []) is None


@pytest.mark.parametrize(
    "title",
    [
        "Example Season 2 Batch",
        "Example S02 Batch",
        "Anime 1-12 [1080p]",
        "Anime E01-E12",
        "Anime 1~12 Batch",
    ],
)
def test_collection_classifier_accepts_common_unbracketed_batch_titles(title):
    assert collection_title_reason(title)


def test_collection_classifier_does_not_treat_real_bad_batch_episode_as_batch():
    assert collection_title_reason("The Bad Batch - 01") is None


def test_metadata_policy_matches_configured_values():
    assert (
        metadata_exclusion_reason(
            _metadata(),
            fansubs=["Sub_A"],
            qualities=[],
            languages=[],
        )
        == "fansub=Sub_A"
    )
    assert (
        metadata_exclusion_reason(
            _metadata(),
            fansubs=[],
            qualities=["1080p"],
            languages=[],
        )
        == "quality=1080p"
    )


def test_priority_policy_rejects_candidate_dominated_by_existing_record():
    records = [
        {
            "fansub": "Sub_A",
            "quality": "1080p",
            "languages": "简",
            "version": 1,
        }
    ]
    assert dominated_by_records(
        _metadata(fansub="Sub_B"),
        records,
        field_order=["fansub"],
        fansubs=["Sub_A", "Sub_B"],
        qualities=[],
        languages=[],
    )


def test_version_upgrade_bypasses_existing_priority_dominance():
    records = [
        {
            "fansub": "Sub_A",
            "quality": "1080p",
            "languages": "简",
            "version": 1,
        }
    ]
    candidate = _metadata(version=2)
    assert is_version_upgrade(candidate, records)
    assert not dominated_by_records(
        candidate,
        records,
        field_order=["fansub", "quality"],
        fansubs=["Sub_A"],
        qualities=["1080p"],
        languages=[],
    )
