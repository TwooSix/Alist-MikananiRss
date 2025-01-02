from copy import deepcopy

import pytest

from alist_mikananirss.core import Remapper
from alist_mikananirss.core.remapper import RemapFrom, RemapTo
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture
def test_data():
    return ResourceInfo(
        resource_title="[ANi]  BLEACH 死神 千年血战篇-相克谭- - 27 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]",
        torrent_url="https://mikanani.me/Download/20241005/e3635409901a94033045060113c2a82689b5c480.torrent",
        published_date="2024-10-05T23:32:50.15614",
        anime_name="死神 千年血战篇-相克谭-",
        season=1,
        episode=27,
        fansub="ANi",
        quality="1080P",
        language="CHT",
        version=1,
    )


def test_match(test_data):

    test_match = Remapper(
        from_=RemapFrom(anime_name="死神 千年血战篇-相克谭-", season=1, fansub="ANi"),
        to_=RemapTo(anime_name="死神", season=1, episode_offset=0),
    )

    test_not_match = Remapper(
        from_=RemapFrom(anime_name="死神 千年血战篇-相克谭-", season=2, fansub="ANi"),
        to_=RemapTo(anime_name="死神", season=2, episode_offset=0),
    )

    assert test_match.match(test_data)
    assert not test_not_match.match(test_data)


def test_remap(test_data):
    test_data_copy = deepcopy(test_data)
    test_remap = Remapper(
        from_=RemapFrom(anime_name="死神 千年血战篇-相克谭-", season=1, fansub="ANi"),
        to_=RemapTo(anime_name="死神", season=2, episode_offset=-26),
    )

    test_remap.remap(test_data_copy)

    assert test_data_copy.anime_name == "死神"
    assert test_data_copy.season == 2
    assert test_data_copy.episode == 1
    assert test_data_copy.fansub == "ANi"
    assert test_data_copy.quality == "1080P"
    assert test_data_copy.language == "CHT"
    assert test_data_copy.version == 1
