from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openlist_ani.application.manual_policy import (
    ManualDownloadPolicyInspector,
    manual_policy_is_approved,
)
from openlist_ani.application.ports import MetadataResolution
from openlist_ani.application.settings import (
    CoreSettings,
    MetadataFilterSettings,
    PrioritySettings,
)
from openlist_ani.domain import (
    DownloadJob,
    LanguageType,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)


def _settings(
    *,
    metadata_filter: MetadataFilterSettings | None = None,
    priority: PrioritySettings | None = None,
    strict_filtering: bool = False,
) -> CoreSettings:
    return CoreSettings(
        download_path="/anime",
        rename_format="{anime_name} S{season:02d}E{episode:02d}",
        rss_interval_seconds=300,
        metadata_providers=(),
        metadata_filter=metadata_filter or MetadataFilterSettings(),
        priority=priority or PrioritySettings(),
        strict_filtering=strict_filtering,
    )


def _inspector(
    *,
    settings: CoreSettings,
    resolution: MetadataResolution | None = None,
):
    jobs = AsyncMock()
    jobs.list_active.return_value = []
    library = AsyncMock()
    library.find_releases_by_episodes.return_value = {}
    resolver = AsyncMock()
    if resolution is not None:
        resolver.resolve_many.return_value = [resolution]
    inspector = ManualDownloadPolicyInspector(
        jobs=jobs,
        library=library,
        metadata_resolver=resolver,
        settings=settings,
    )
    return inspector, jobs, library, resolver


@pytest.mark.asyncio
async def test_collection_reports_title_and_blanket_policy_conflicts_without_metadata():
    inspector, jobs, library, resolver = _inspector(
        settings=_settings(
            metadata_filter=MetadataFilterSettings(exclude_patterns=[r"Batch"])
        )
    )

    review = await inspector.inspect(
        "magnet:?xt=urn:btih:collection",
        "Example S01E01-E12 Batch",
    )

    assert review.conflict_keys == (
        "title_pattern:Batch",
        "collection:automatic-release-policy",
    )
    assert [conflict.code for conflict in review.conflicts] == [
        "excluded_title_pattern",
        "collection_policy_override",
    ]
    assert review.warnings == ()
    resolver.resolve_many.assert_not_awaited()
    library.find_releases_by_episodes.assert_not_awaited()
    jobs.list_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolved_multivideo_hint_reports_collection_for_opaque_title():
    inspector, jobs, library, resolver = _inspector(settings=_settings())

    review = await inspector.inspect(
        "magnet:?xt=urn:btih:opaque-collection",
        "Opaque release title",
        collection_hint=True,
    )

    assert review.conflict_keys == ("collection:automatic-release-policy",)
    assert "multiple video files" in review.conflicts[0].matched
    resolver.resolve_many.assert_not_awaited()
    library.find_releases_by_episodes.assert_not_awaited()
    jobs.list_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_release_reports_all_metadata_priority_and_strict_conflicts():
    metadata = ReleaseMetadata(
        anime_name="Example",
        season=1,
        episode=1,
        fansub="Low",
        quality=VideoQuality.Q720P,
        languages=[LanguageType.CHS, LanguageType.CHT],
        version=1,
    )
    document = MetadataDocument(values=metadata)
    inspector, jobs, library, resolver = _inspector(
        settings=_settings(
            metadata_filter=MetadataFilterSettings(
                exclude_fansub=["Low"],
                exclude_quality=[VideoQuality.Q720P.value],
                exclude_languages=[LanguageType.CHS.value, LanguageType.CHT.value],
            ),
            priority=PrioritySettings(
                field_order=["fansub", "quality", "languages"],
                fansub=["High", "Low"],
                quality=[VideoQuality.Q1080P.value, VideoQuality.Q720P.value],
                languages=[],
            ),
            strict_filtering=True,
        ),
        resolution=MetadataResolution(document),
    )
    episode_key = ("Example", 1, 1)
    library.find_releases_by_episodes.return_value = {
        episode_key: [
            {
                "fansub": "High",
                "quality": VideoQuality.Q1080P.value,
                "languages": LanguageType.CHS.value,
                "version": 1,
            }
        ]
    }

    review = await inspector.inspect(
        "magnet:?xt=urn:btih:regular",
        "Example - 01 [720p]",
    )

    assert set(review.conflict_keys) == {
        "metadata:fansub=Low",
        f"metadata:quality={VideoQuality.Q720P.value}",
        f"metadata:language={LanguageType.CHS.value}",
        f"metadata:language={LanguageType.CHT.value}",
        "priority:dominated",
        "strict:rename-stem-conflict",
    }
    assert {conflict.code for conflict in review.conflicts} == {
        "excluded_fansub",
        "excluded_quality",
        "excluded_language",
        "lower_priority",
        "strict_rename_conflict",
    }
    assert review.metadata is document
    assert review.warnings == ()
    resolver.resolve_many.assert_awaited_once()
    library.find_releases_by_episodes.assert_awaited_once_with([episode_key])
    jobs.list_active.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_incomplete_inspection_becomes_a_confirmable_conflict():
    document = MetadataDocument(values=ReleaseMetadata(anime_name="Example", season=1))
    inspector, jobs, library, _resolver = _inspector(
        settings=_settings(),
        resolution=MetadataResolution(
            document,
            retryable_error="metadata provider temporarily unavailable",
        ),
    )

    review = await inspector.inspect(
        "magnet:?xt=urn:btih:incomplete",
        "Example unknown episode",
    )

    assert review.conflict_keys == ("inspection:incomplete",)
    assert review.conflicts[0].code == "policy_inspection_incomplete"
    assert review.conflicts[0].matched == ("metadata provider temporarily unavailable")
    assert review.warnings == ("metadata provider temporarily unavailable",)
    assert review.metadata is document
    library.find_releases_by_episodes.assert_not_awaited()
    jobs.list_active.assert_not_awaited()


def _job(source_name: str, artifact: dict) -> DownloadJob:
    return DownloadJob(
        id=f"{source_name}-job",
        candidate=ReleaseCandidate.create(
            source_name=source_name,
            source_url="api" if source_name == "manual" else "https://feed.invalid",
            title="Example - 01",
            download_url=f"magnet:?xt=urn:btih:{source_name}",
        ),
        artifact=artifact,
    )


@pytest.mark.parametrize(
    ("source_name", "artifact", "expected"),
    [
        ("manual", {"manual_policy_review": {"approved": True}}, True),
        ("manual", {"manual_policy_review": {"approved": False}}, False),
        ("manual", {"manual_policy_review": {"approved": "true"}}, False),
        ("manual", {"manual_policy_review": {"approved": 1}}, False),
        ("manual", {"manual_policy_review": []}, False),
        ("manual", {}, False),
        ("feed", {"manual_policy_review": {"approved": True}}, False),
    ],
)
def test_manual_policy_approval_requires_manual_source_and_literal_true(
    source_name, artifact, expected
):
    assert manual_policy_is_approved(_job(source_name, artifact)) is expected
