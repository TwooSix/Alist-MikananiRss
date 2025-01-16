from typing import Optional

from pydantic import BaseModel, Field

from alist_mikananirss.websites.entities import VideoQuality


class TMDBSearchParam(BaseModel):
    query: str = Field(..., description="Keywords of the anime name to search")


class TMDBTvInfo(BaseModel):
    anime_name: str = Field(..., description="The name of the anime in tmdb")
    tvid: int = Field(..., description="The tmdb id of the anime")


class ResourceTitleExtractResult(BaseModel):
    anime_name: str = Field(..., description="The name of the anime")
    season: int = Field(
        ...,
        description="The season of the anime.Default to be 1. But if special episode, it should be 0",
    )
    episode: int = Field(
        ...,
        description="The episode number. It should be int. If float, it means special episode",
    )
    quality: Optional[VideoQuality] = Field(..., description="The quality of the video")
    fansub: Optional[str] = Field(..., description="The fansub of the video")
    language: Optional[str] = Field(
        ..., description="The subtitle language of the video"
    )
    version: int = Field(
        ..., description="The version of the video's subtitle, default to be 1"
    )


class AnimeNameExtractResult(BaseModel):
    anime_name: str = Field(
        ..., description="The pure name of the anime without season or other info"
    )
    season: int = Field(..., description="The season of the anime")
