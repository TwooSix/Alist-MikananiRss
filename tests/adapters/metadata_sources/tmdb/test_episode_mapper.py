import asyncio

from openlist_ani.adapters.metadata_sources.tmdb import (
    EpisodeMapper,
    MappingContext,
)
from openlist_ani.adapters.metadata_sources.models import SeasonInfo


class FakeTMDBClient:
    async def get_season_episodes(self, tmdb_id: int, season_number: int):
        await asyncio.sleep(0)
        return []


async def test_episode_mapper_rejects_episode_beyond_tmdb_season_count():
    mapper = EpisodeMapper()
    mapping = await mapper.map(
        MappingContext(
            tmdb_id=280758,
            fansub_season=1,
            fansub_episode=12,
            sorted_seasons=[
                SeasonInfo(season_number=0, episode_count=0, name="Specials"),
                SeasonInfo(season_number=1, episode_count=8, name="Season 1"),
            ],
            tmdb_client=FakeTMDBClient(),
            release_title="[ANi] 双人单身露营 - 12 [1080P][CHT]",
        )
    )

    assert mapping is None


async def test_episode_mapper_maps_absolute_numbering_inside_later_season():
    mapper = EpisodeMapper()
    mapping = await mapper.map(
        MappingContext(
            tmdb_id=237529,
            fansub_season=2,
            fansub_episode=21,
            sorted_seasons=[
                SeasonInfo(season_number=1, episode_count=13, name="第 1 季"),
                SeasonInfo(season_number=2, episode_count=9, name="第 2 季"),
            ],
            tmdb_client=FakeTMDBClient(),
            release_title="[绿茶字幕组] 金牌得主 第二季 / Medalist S2 [21]",
        )
    )

    assert mapping is not None
    assert mapping.season == 2
    assert mapping.episode == 8


async def test_episode_mapper_prefers_named_tmdb_season_over_valid_default_season():
    mapper = EpisodeMapper()
    mapping = await mapper.map(
        MappingContext(
            tmdb_id=30984,
            fansub_season=1,
            fansub_episode=41,
            sorted_seasons=[
                SeasonInfo(season_number=1, episode_count=366, name="本篇"),
                SeasonInfo(season_number=2, episode_count=50, name="千年血战篇"),
            ],
            tmdb_client=FakeTMDBClient(),
            release_title=(
                "[ANi] BLEACH 死神 千年血戰篇-禍進譚- - 41 "
                "[1080P][Baha][WEB-DL][AAC AVC][CHT].mp4"
            ),
        )
    )

    assert mapping is not None
    assert mapping.season == 2
    assert mapping.episode == 41
    assert mapping.strategy == "season_title"


async def test_episode_mapper_does_not_fall_back_when_named_season_is_out_of_range():
    mapper = EpisodeMapper()
    mapping = await mapper.map(
        MappingContext(
            tmdb_id=30984,
            fansub_season=1,
            fansub_episode=41,
            sorted_seasons=[
                SeasonInfo(season_number=1, episode_count=366, name="本篇"),
                SeasonInfo(season_number=2, episode_count=40, name="千年血战篇"),
            ],
            tmdb_client=FakeTMDBClient(),
            release_title="[ANi] BLEACH 死神 千年血战篇-祸进谭- - 41",
        )
    )

    assert mapping is None
