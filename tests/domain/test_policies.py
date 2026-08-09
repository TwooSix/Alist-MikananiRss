from openlist_ani.domain import LanguageType, ReleaseMetadata, VideoQuality
from openlist_ani.domain.policies import (
    best_indices,
    dominated_by_records,
    is_version_upgrade,
    metadata_exclusion_reason,
    priority_levels,
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


def test_title_policy_applies_user_patterns_after_collection_rules():
    assert title_exclusion_reason("Example CAM", [r"\bCAM\b"]) == r"\bCAM\b"


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


def test_batch_priority_winners_are_deterministic():
    levels = [
        priority_levels(
            _metadata(fansub=name),
            field_order=["fansub"],
            fansubs=["Sub_A", "Sub_B"],
            qualities=[],
            languages=[],
        )
        for name in ("Sub_B", "Sub_A", "Sub_A")
    ]
    assert best_indices(levels) == {1, 2}
