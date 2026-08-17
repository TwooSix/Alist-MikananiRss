from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from openlist_ani.application.manual_policy import (
    COLLECTION_POLICY_CONFLICT_KEY,
    MANUAL_PARTIAL_COLLECTION_RETRY_KEY,
    ManualPolicyConflict,
    ManualPolicyReview,
)
from openlist_ani.application.service import CoreApplicationService
from openlist_ani.application.settings import CoreSettings
from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)

DOWNLOAD_URL = "magnet:?xt=urn:btih:manual-policy"
TITLE = "[Group] Example Batch [1080p]"
CONFLICT = ManualPolicyConflict(
    key="title_pattern:Batch",
    code="excluded_title_pattern",
    reason="The title matches an RSS exclusion pattern.",
    matched="Batch",
    details={"title": TITLE},
)


def _service(
    *,
    review: ManualPolicyReview,
    downloaded: bool = False,
) -> tuple[CoreApplicationService, AsyncMock, AsyncMock, AsyncMock, asyncio.Event]:
    jobs = AsyncMock()
    jobs.list_active.return_value = []
    jobs.find_history.return_value = []
    library = AsyncMock()
    library.is_downloaded.return_value = downloaded
    inspector = AsyncMock()
    inspector.inspect.return_value = review
    metadata_available = asyncio.Event()
    service = CoreApplicationService(
        jobs=jobs,
        library=library,
        registry=Mock(),
        settings=CoreSettings(
            download_path="/anime",
            rename_format="{anime_name} S{season:02d}E{episode:02d}",
            rss_interval_seconds=300,
            metadata_providers=(),
        ),
        config_manager=Mock(),
        feed_scheduler=Mock(),
        metadata_available=metadata_available,
        resolve_magnet_func=AsyncMock(),
        resolve_torrent_func=AsyncMock(),
        health_provider=Mock(return_value={}),
        manual_policy_inspector=inspector,
    )
    return service, jobs, library, inspector, metadata_available


@pytest.mark.asyncio
async def test_preflight_conflict_does_not_create_job_or_wake_worker():
    service, jobs, _, inspector, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(CONFLICT,))
    )

    outcome = await service.preflight_download(DOWNLOAD_URL, TITLE)

    assert outcome.success is True
    assert outcome.confirmation_required is True
    assert outcome.policy_conflicts == (CONFLICT,)
    inspector.inspect.assert_awaited_once_with(
        DOWNLOAD_URL, TITLE, collection_hint=False
    )
    jobs.add_candidate.assert_not_awaited()
    assert metadata_available.is_set() is False


@pytest.mark.asyncio
async def test_create_rejects_acknowledgements_that_do_not_match_current_conflicts():
    service, jobs, _, _, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(CONFLICT,))
    )
    preflight = await service.preflight_download(DOWNLOAD_URL, TITLE)

    outcome = await service.create_download(
        DOWNLOAD_URL,
        TITLE,
        override_policy=True,
        acknowledged_conflicts=("title_pattern:Different",),
        policy_review_token=preflight.policy_review_token,
    )

    assert outcome.success is False
    assert outcome.confirmation_required is True
    assert outcome.policy_conflicts == (CONFLICT,)
    assert "changed" in outcome.message.lower()
    jobs.add_candidate.assert_not_awaited()
    assert metadata_available.is_set() is False


@pytest.mark.asyncio
async def test_clean_review_queues_without_broad_policy_override():
    service, jobs, _, _, metadata_available = _service(review=ManualPolicyReview())

    async def add_candidate(candidate, **kwargs):
        return DownloadJob(
            id="clean-manual-job",
            candidate=candidate,
            artifact=dict(kwargs["initial_artifact"]),
            metadata=kwargs["initial_metadata"],
        )

    jobs.add_candidate.side_effect = add_candidate

    outcome = await service.create_download(DOWNLOAD_URL, TITLE)

    assert outcome.success is True
    review = jobs.add_candidate.await_args.kwargs["initial_artifact"][
        "manual_policy_review"
    ]
    assert review["approved"] is True
    assert review["override_policy"] is False
    assert review["acknowledged_conflicts"] == []
    assert metadata_available.is_set() is True


@pytest.mark.asyncio
async def test_clean_recheck_accepts_confirmed_superset_after_conflict_disappears():
    service, jobs, _, inspector, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(CONFLICT,))
    )

    async def add_candidate(candidate, **kwargs):
        return DownloadJob(
            id="conflict-disappeared-job",
            candidate=candidate,
            artifact=dict(kwargs["initial_artifact"]),
            metadata=kwargs["initial_metadata"],
        )

    jobs.add_candidate.side_effect = add_candidate
    preflight = await service.preflight_download(DOWNLOAD_URL, TITLE)
    inspector.inspect.return_value = ManualPolicyReview()

    outcome = await service.create_download(
        DOWNLOAD_URL,
        TITLE,
        override_policy=True,
        acknowledged_conflicts=(CONFLICT.key,),
        policy_review_token=preflight.policy_review_token,
    )

    assert outcome.success is True
    assert outcome.confirmation_required is False
    persisted = jobs.add_candidate.await_args.kwargs["initial_artifact"][
        "manual_policy_review"
    ]
    assert persisted["override_policy"] is False
    assert persisted["acknowledged_conflicts"] == []
    assert metadata_available.is_set() is True


@pytest.mark.asyncio
async def test_confirmed_collection_review_rejects_dropped_collection_hint():
    collection_conflict = ManualPolicyConflict(
        key=COLLECTION_POLICY_CONFLICT_KEY,
        code="collection_policy_override",
        reason="Collection policy override",
    )
    service, jobs, _, inspector, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(collection_conflict,))
    )
    preflight = await service.preflight_download(
        DOWNLOAD_URL, "Opaque release", collection_hint=True
    )
    inspector.inspect.return_value = ManualPolicyReview()

    outcome = await service.create_download(
        DOWNLOAD_URL,
        "Opaque release",
        collection_hint=False,
        override_policy=True,
        acknowledged_conflicts=(COLLECTION_POLICY_CONFLICT_KEY,),
        policy_review_token=preflight.policy_review_token,
    )

    assert outcome.success is False
    assert outcome.confirmation_required is False
    assert "context changed" in outcome.message.lower()
    jobs.add_candidate.assert_not_awaited()
    assert metadata_available.is_set() is False


@pytest.mark.asyncio
async def test_matching_override_persists_policy_review_and_preflight_metadata():
    metadata = MetadataDocument(
        values=ReleaseMetadata(
            anime_name="Example",
            season=1,
            episode=1,
            fansub="Group",
            quality=VideoQuality.Q1080P,
        )
    )
    review = ManualPolicyReview(conflicts=(CONFLICT,), metadata=metadata)
    service, jobs, _, _, metadata_available = _service(review=review)

    async def add_candidate(candidate, **kwargs):
        return DownloadJob(
            id="manual-job",
            candidate=candidate,
            artifact=dict(kwargs["initial_artifact"]),
            metadata=kwargs["initial_metadata"],
        )

    jobs.add_candidate.side_effect = add_candidate
    preflight = await service.preflight_download(
        DOWNLOAD_URL, TITLE, collection_hint=True
    )

    outcome = await service.create_download(
        DOWNLOAD_URL,
        TITLE,
        collection_hint=True,
        override_policy=True,
        acknowledged_conflicts=(CONFLICT.key,),
        policy_review_token=preflight.policy_review_token,
    )

    assert outcome.success is True
    assert outcome.task is not None
    assert outcome.task.id == "manual-job"
    assert metadata_available.is_set() is True
    call = jobs.add_candidate.await_args
    candidate = call.args[0]
    assert candidate.source_name == "manual"
    assert candidate.download_url == DOWNLOAD_URL
    assert call.kwargs["initial_metadata"] is metadata
    persisted = call.kwargs["initial_artifact"]["manual_policy_review"]
    assert call.kwargs["initial_artifact"]["collection_hint"] is True
    assert persisted == {
        "approved": True,
        "override_policy": True,
        "acknowledged_conflicts": [CONFLICT.key],
        "conflicts": [CONFLICT.to_dict()],
        "warnings": [],
        "scope": "rss_filter_priority_strict",
    }


@pytest.mark.asyncio
async def test_hard_blocker_prevents_policy_inspection_and_job_creation():
    service, jobs, _, inspector, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(CONFLICT,)),
        downloaded=True,
    )

    outcome = await service.create_download(
        DOWNLOAD_URL,
        TITLE,
        override_policy=True,
        acknowledged_conflicts=(CONFLICT.key,),
    )

    assert outcome.success is False
    assert outcome.confirmation_required is False
    assert outcome.message == f"Already downloaded: {TITLE}"
    inspector.inspect.assert_not_awaited()
    jobs.add_candidate.assert_not_awaited()
    assert metadata_available.is_set() is False


@pytest.mark.asyncio
async def test_partial_collection_can_be_retried_without_repeating_completed_episode():
    collection_conflict = ManualPolicyConflict(
        key=COLLECTION_POLICY_CONFLICT_KEY,
        code="collection_policy_override",
        reason="Collection policy override",
    )
    service, jobs, library, inspector, metadata_available = _service(
        review=ManualPolicyReview(conflicts=(collection_conflict,)),
        downloaded=True,
    )
    prior = DownloadJob(
        id="partial-parent",
        candidate=ReleaseCandidate.create(
            source_name="feed",
            source_url="https://feed.invalid/rss",
            title=TITLE,
            download_url=DOWNLOAD_URL,
        ),
        status=JobStatus.COMPLETED,
        artifact={
            "summary": {
                "collection": True,
                "items": [
                    {
                        "item_key": "episode-1",
                        "state": "completed",
                        "anime_name": "Example",
                        "season": 1,
                        "episode": 1,
                    },
                    {
                        "item_key": "episode-2",
                        "state": "skipped",
                        "error": "release_policy",
                        "anime_name": "Example",
                        "season": 1,
                        "episode": 2,
                    },
                ],
            }
        },
    )
    jobs.find_history.return_value = [prior]

    async def add_candidate(candidate, **kwargs):
        return DownloadJob(
            id="partial-retry",
            candidate=candidate,
            artifact=dict(kwargs["initial_artifact"]),
            metadata=kwargs["initial_metadata"],
        )

    jobs.add_candidate.side_effect = add_candidate
    preflight = await service.preflight_download(DOWNLOAD_URL, TITLE)
    outcome = await service.create_download(
        DOWNLOAD_URL,
        TITLE,
        override_policy=True,
        acknowledged_conflicts=(COLLECTION_POLICY_CONFLICT_KEY,),
        policy_review_token=preflight.policy_review_token,
    )

    assert outcome.success is True
    assert metadata_available.is_set() is True
    assert library.is_downloaded.await_count == 0
    assert inspector.inspect.await_args_list == [
        ((DOWNLOAD_URL, TITLE), {"collection_hint": True}),
        ((DOWNLOAD_URL, TITLE), {"collection_hint": True}),
    ]
    call = jobs.add_candidate.await_args
    assert call.args[0].guid.startswith("manual-partial-retry:")
    artifact = call.kwargs["initial_artifact"]
    assert artifact["collection_hint"] is True
    retry = artifact[MANUAL_PARTIAL_COLLECTION_RETRY_KEY]
    assert retry["source_job_ids"] == ["partial-parent"]
    assert retry["completed_episode_keys"] == [
        {"anime_name": "Example", "season": 1, "episode": 1}
    ]
