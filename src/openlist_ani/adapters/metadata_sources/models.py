"""Provider-private validated response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from openlist_ani.domain import LanguageType, VideoQuality


class ParsedFields(BaseModel):
    anime_name: str
    season: int
    episode: int
    quality: VideoQuality | None = None
    fansub: str | None = None
    languages: list[LanguageType]
    version: int
    tmdb_id: int | None = None


class TitleParseResponse(BaseModel):
    success: bool
    result: ParsedFields | None = None
    error: str | None = None
    release_title: str | None = None


class TMDBMatch(BaseModel):
    tmdb_id: int
    anime_name: str
    year: int | None = None
    confidence: str = "unknown"


class SeasonInfo(BaseModel):
    season_number: int
    episode_count: int
    name: str = ""

    @staticmethod
    def from_raw_list(raw_seasons: list[dict[str, Any]]) -> list["SeasonInfo"]:
        return sorted(
            [
                SeasonInfo(
                    season_number=int(item.get("season_number") or 0),
                    episode_count=int(item.get("episode_count") or 0),
                    name=str(item.get("name") or ""),
                )
                for item in raw_seasons
            ],
            key=lambda item: item.season_number,
        )


class CourGroup(BaseModel):
    cour_index: int
    start_episode: int
    end_episode: int
    air_date_start: str = ""
    air_date_end: str = ""


class TMDBCandidate(BaseModel):
    id: int
    name: str | None = None
    original_name: str | None = None
    first_air_date: str | None = None
    overview: str = ""
    genre_ids: list[int] = Field(default_factory=list)
    origin_country: list[str] = Field(default_factory=list)


class EpisodeMapping(BaseModel):
    season: int
    episode: int
    strategy: str
