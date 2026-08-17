from openlist_ani.adapters.http.service import _build_task_response
from openlist_ani.application.service import _job_to_view
from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    LanguageType,
    ReleaseCandidate,
    VideoQuality,
)


def _candidate() -> ReleaseCandidate:
    return ReleaseCandidate.create(
        source_name="test",
        source_url="test://feed",
        title="Example 01-03",
        download_url="magnet:?xt=urn:btih:example",
    )


def test_collection_view_merges_resolution_and_organization_results():
    job = DownloadJob(
        id="job-1",
        candidate=_candidate(),
        status=JobStatus.COMPLETED,
        output_path="/Anime/Example/Season 1/Example S01E01.mkv",
        artifact={
            "collection_hint": True,
            "collection_context": {
                "anime_name": "Release Alias",
                "season": 1,
                "episode": 99,
                "fansub": "Example Group",
                "quality": "1080p",
                "languages": [LanguageType.CHS.value, LanguageType.CHT.value],
            },
            "resolved_items": [
                {
                    "item_key": "episode-1",
                    "source_path": "Show/01.mkv",
                    "state": "ready",
                    "metadata": {
                        "values": {
                            "anime_name": "Example",
                            "season": 1,
                            "episode": 1,
                            "year": 2026,
                            "external_ids": {"tmdb": "123"},
                        }
                    },
                },
                {
                    "item_key": "sample",
                    "source_path": "Show/Sample.mkv",
                    "state": "failed",
                    "error": "not_main_episode",
                },
            ],
            "organization_results": [
                {
                    "item_key": "episode-1",
                    "state": "completed",
                    "final_path": "/Anime/Example/Season 1/Example S01E01.mkv",
                }
            ],
            "final_paths": [
                "/Anime/Example/Season 1/Example S01E01.mkv",
            ],
            "summary": {
                "success_count": 1,
                "failed_count": 1,
                "warning_count": 1,
                "items": [
                    {
                        "item_key": "episode-1",
                        "state": "stale-summary-state",
                    }
                ],
            },
        },
    )

    view = _job_to_view(job, "/default")
    response = _build_task_response(view)

    assert view.final_path == view.final_paths[0]
    assert view.warning_count == 1
    assert view.anime_name == "Example"
    assert view.season == 1
    assert view.episode is None
    assert view.fansub == "Example Group"
    assert view.quality == VideoQuality.Q1080P
    assert view.languages == (LanguageType.CHS, LanguageType.CHT)
    assert [item.item_key for item in view.items] == ["episode-1", "sample"]
    assert view.items[0].state == "completed"
    assert view.items[0].anime_name == "Example"
    assert view.items[0].season == 1
    assert view.items[0].episode == 1
    assert response.final_paths == list(view.final_paths)
    assert response.anime_name == "Example"
    assert response.episode is None
    assert response.items[1].error == "not_main_episode"


def test_legacy_single_resource_exposes_new_fields_without_changing_final_path():
    job = DownloadJob(
        id="legacy-job",
        candidate=_candidate(),
        status=JobStatus.COMPLETED,
        output_path="/Anime/legacy.mkv",
        artifact={"filename": "legacy.mkv"},
    )

    view = _job_to_view(job, "/default")

    assert view.final_path == "/Anime/legacy.mkv"
    assert view.final_paths == ("/Anime/legacy.mkv",)
    assert view.warning_count == 0
    assert view.items[0].item_key == "legacy-single-resource"
    assert view.items[0].state == "completed"
