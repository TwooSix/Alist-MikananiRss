from openlist_ani.adapters.metadata_sources.models import TMDBCandidate
from openlist_ani.adapters.metadata_sources.tmdb import (
    HeuristicCandidateSelector,
    StaticQueryExpander,
)


async def test_heuristic_selector_prefers_matching_animation_candidate():
    selector = HeuristicCandidateSelector()
    match = await selector.select(
        "Example",
        [
            TMDBCandidate(id=1, name="Example", genre_ids=[18]),
            TMDBCandidate(id=2, name="Example", genre_ids=[16]),
            TMDBCandidate(id=3, name="Unrelated", genre_ids=[16]),
        ],
    )

    assert match is not None
    assert match.tmdb_id == 2
    assert match.anime_name == "Example"


async def test_static_query_expander_adds_visible_fate_punctuation_variant():
    queries = await StaticQueryExpander().expand("Fatestrange Fake")

    assert "Fate/strange Fake" in queries
