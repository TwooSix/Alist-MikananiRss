from openlist_ani.domain import ReleaseMetadata
from openlist_ani.domain.naming import ReleaseFilenamePlanner, format_release_stem


def test_year_is_available_to_rename_format():
    metadata = ReleaseMetadata(
        anime_name="Example",
        season=1,
        episode=2,
        year=2024,
    )

    assert (
        format_release_stem(
            "{anime_name} ({year}) S{season:02d}E{episode:02d}", metadata
        )
        == "Example (2024) S01E02"
    )


def test_missing_year_renders_as_empty_text():
    planner = ReleaseFilenamePlanner("{anime_name} {year} E{episode:02d}")

    assert (
        planner.filename(
            ReleaseMetadata(anime_name="Example", season=1, episode=2),
            "source.mkv",
        )
        == "Example  E02.mkv"
    )
