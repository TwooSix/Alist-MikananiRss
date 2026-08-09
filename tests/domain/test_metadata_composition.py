import json

from openlist_ani.domain import (
    LanguageType,
    MetadataDocument,
    MetadataPatch,
    ReleaseMetadata,
    VideoQuality,
)


def test_metadata_merge_is_field_level_and_priority_ordered():
    document = MetadataDocument()
    document.apply(
        MetadataPatch(
            source="regex",
            values=ReleaseMetadata(anime_name="Parsed", season=1, episode=2),
            priority=10,
        )
    )
    document.apply(
        MetadataPatch(
            source="mikan",
            values=ReleaseMetadata(anime_name="Feed Name", episode=3),
            priority=20,
        )
    )
    document.apply(
        MetadataPatch(
            source="tmdb",
            values=ReleaseMetadata(
                anime_name="Canonical Name",
                season=2,
                year=2024,
                external_ids={"tmdb": "42"},
            ),
            authoritative=True,
            priority=30,
        )
    )
    document.apply(
        MetadataPatch(
            source="late-heuristic",
            values=ReleaseMetadata(anime_name="Wrong"),
            priority=10,
        )
    )

    assert document.values.anime_name == "Canonical Name"
    assert document.values.season == 2
    assert document.values.episode == 3
    assert document.values.year == 2024
    assert document.values.external_ids == {"tmdb": "42"}
    assert [item.source for item in document.evidence["anime_name"]] == [
        "regex",
        "mikan",
        "tmdb",
    ]
    history = document.evidence["anime_name"]
    assert [item.value for item in history] == [
        "Parsed",
        "Feed Name",
        "Canonical Name",
    ]
    assert [item.previous_value for item in history] == [
        None,
        "Parsed",
        "Feed Name",
    ]
    assert [item.overrode for item in history] == [False, True, True]
    json.dumps(document.to_dict())


def test_unknown_sentinels_do_not_override_known_metadata():
    document = MetadataDocument()
    document.apply(
        MetadataPatch(
            source="title",
            values=ReleaseMetadata(
                quality=VideoQuality.Q1080P,
                languages=[LanguageType.CHT],
            ),
            priority=10,
        )
    )
    document.apply(
        MetadataPatch(
            source="feed",
            values=ReleaseMetadata(
                quality=VideoQuality.UNKNOWN,
                languages=[LanguageType.UNKNOWN],
            ),
            priority=20,
        )
    )

    assert document.values.quality == VideoQuality.Q1080P
    assert document.values.languages == [LanguageType.CHT]
    assert [item.source for item in document.evidence["quality"]] == ["title"]
    assert [item.source for item in document.evidence["languages"]] == ["title"]


def test_literal_unknown_text_is_not_confused_with_typed_sentinel():
    document = MetadataDocument()
    document.apply(
        MetadataPatch(
            source="feed",
            values=ReleaseMetadata(anime_name="unknown", fansub="未知"),
        )
    )

    assert document.values.anime_name == "unknown"
    assert document.values.fansub == "未知"


def test_release_metadata_normalizes_unknown_source_values_to_missing():
    metadata = ReleaseMetadata.from_dict(
        {
            "quality": VideoQuality.UNKNOWN,
            "languages": [LanguageType.UNKNOWN],
        }
    )

    assert metadata.quality is None
    assert metadata.languages == []
    assert metadata.version is None


def test_legacy_unknown_value_can_be_filled_by_lower_priority_provider():
    document = MetadataDocument.from_dict(
        {
            "values": {"quality": "unknown"},
            "evidence": {"quality": [{"source": "legacy-feed", "priority": 20}]},
        }
    )

    document.apply(
        MetadataPatch(
            source="title",
            values=ReleaseMetadata(quality=VideoQuality.Q1080P),
            priority=10,
        )
    )

    assert document.values.quality == VideoQuality.Q1080P
    assert [item.source for item in document.evidence["quality"]] == [
        "legacy-feed",
        "title",
    ]
    assert document.evidence["quality"][-1].value == "1080p"


def test_metadata_document_reads_evidence_written_before_priority_field_existed():
    document = MetadataDocument.from_dict(
        {
            "values": {"anime_name": "Legacy"},
            "evidence": {"anime_name": [{"source": "legacy"}]},
        }
    )

    evidence = document.evidence["anime_name"][0]
    assert evidence.priority == 10
    assert evidence.value is None
    assert evidence.previous_value is None
    assert evidence.overrode is False
