import pytest

from openlist_ani.application.collection import (
    child_release_title,
    collection_parent_probe,
    collection_videos,
    explicit_path_season,
    is_main_feature_path,
    normalize_relative_path,
)
from openlist_ani.application.ports import DownloadManifest, DownloadedFile
from openlist_ani.domain import ReleaseMetadata


def test_manifest_keeps_every_nested_video_and_binds_subtitles_once():
    manifest = DownloadManifest(
        root_path="/staging/job",
        files=(
            DownloadedFile("Season 1/Show 01.mkv", 100),
            DownloadedFile("Season 1/Show 01.zh-Hans.ass", 4),
            DownloadedFile("Season 1/Show 02.mkv", 110),
            DownloadedFile("subs/Show 02.srt", 3),
            DownloadedFile("cover.jpg", 2),
        ),
    )

    videos = collection_videos(manifest)

    assert [item.relative_path for item in videos] == [
        "Season 1/Show 01.mkv",
        "Season 1/Show 02.mkv",
    ]
    assert [item.relative_path for item in videos[0].sidecars] == [
        "Season 1/Show 01.zh-Hans.ass"
    ]
    assert [item.relative_path for item in videos[1].sidecars] == ["subs/Show 02.srt"]
    assert videos[0].item_key != videos[1].item_key


def test_cross_directory_ambiguous_subtitle_is_not_bound():
    manifest = DownloadManifest(
        root_path="/staging/job",
        files=(
            DownloadedFile("disc1/Show 01.mkv"),
            DownloadedFile("disc2/Show 01.mp4"),
            DownloadedFile("subs/Show 01.ass"),
        ),
    )

    assert all(not item.sidecars for item in collection_videos(manifest))


def test_bare_episode_inherits_parent_but_explicit_directory_season_wins():
    parent = ReleaseMetadata(anime_name="Example", season=1, episode=99)

    assert explicit_path_season("Season 2/01.mkv") == 2
    assert child_release_title("Season 2/01.mkv", parent) == "Example S02 - 01"
    assert child_release_title("02.mkv", parent) == "Example S01 - 02"


def test_full_relative_path_can_supply_series_directory_for_bare_episode():
    parent = ReleaseMetadata(season=1, episode=99)

    assert child_release_title("Example/Season 2/01.mkv", parent) == "Example S02 - 01"

    assert child_release_title("Example/Part A/02.mkv", ReleaseMetadata()) == (
        "Example S01 - 02"
    )


def test_explicit_specials_season_is_not_rewritten_as_parent_season():
    parent = ReleaseMetadata(anime_name="Example", season=1)

    assert explicit_path_season("Season 0/01.mkv") == 0
    assert child_release_title("Season 0/01.mkv", parent) == "Example S00 - 01"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("01 [1080p].mkv", "Example S01 - 01 [1080p]"),
        ("[Group] 02 [CHS].mkv", "[Group] Example S01 - 02 [CHS]"),
        ("E03 v2.mkv", "Example S01 - 03 v2"),
        ("01 1080p.mkv", "Example S01 - 01 1080p"),
        ("EP01_v2_720p_CHS.mkv", "Example S01 - 01 v2_720p_CHS"),
        ("Episode 04 1080p.mkv", "Example S01 - 04 1080p"),
        ("[Group][05][1080p].mkv", "[Group] Example S01 - 05 [1080p]"),
    ],
)
def test_sparse_episode_filename_with_tags_still_uses_parent_context(path, expected):
    parent = ReleaseMetadata(anime_name="Example", season=1)

    assert child_release_title(path, parent) == expected


def test_collection_parent_probe_drops_range_and_batch_marker():
    probe = collection_parent_probe("[Group] Example S01E01-E12 Batch [1080p]")

    assert "E12" not in probe
    assert "Batch" not in probe
    assert "S01E01" in probe
    assert collection_parent_probe("Anime E01-E12") == "Anime - 01"


def test_collection_parent_probe_adds_only_a_disposable_episode_when_missing():
    probe = collection_parent_probe("[Group] Example Season 2 Batch [1080p]")

    assert "Batch" not in probe
    assert probe.endswith("- 01")


def test_collection_parent_probe_does_not_treat_season_number_as_episode():
    probe = collection_parent_probe("Example Season 2 Batch")

    assert probe == "Example Season 2 - 01"


def test_collection_parent_probe_preserves_batch_when_it_is_part_of_title():
    probe = collection_parent_probe("[Group] The Bad Batch Season 1 Complete [1080p]")

    assert probe == "[Group] The Bad Batch Season 1 [1080p] - 01"

    assert collection_parent_probe("The Bad Batch Complete") == ("The Bad Batch - 01")


def test_only_regular_episode_paths_are_main_features():
    assert is_main_feature_path("Season 1/Show S01E01.mkv")
    assert is_main_feature_path("Takt Op. Destiny/Takt Op. Destiny - 01.mkv")
    assert is_main_feature_path("Special A/Special A S01E01.mkv")
    assert is_main_feature_path("The Special/The Special S01E01.mkv")
    assert not is_main_feature_path("SP/Show SP01.mkv")
    assert not is_main_feature_path("Season 1/Show NCOP.mkv")
    assert not is_main_feature_path("特典/访谈.mkv")


@pytest.mark.parametrize(
    "path",
    [
        "OVAs/01.mkv",
        "OADs/01.mkv",
        "SPs/01.mkv",
        "OVA Collection/01.mkv",
        "[SP]/01.mkv",
        "NCOP/01.mkv",
        "[NCOP]/01.mkv",
        "SPs [1080p]/01.mkv",
        "Extras Disc/01.mkv",
    ],
)
def test_special_resource_directories_are_not_main_features(path):
    assert not is_main_feature_path(path)


@pytest.mark.parametrize("path", ["../escape.mkv", "/absolute.mkv", "C:/drive.mkv"])
def test_manifest_paths_must_be_relative_and_cannot_escape(path):
    with pytest.raises(ValueError):
        normalize_relative_path(path)
