from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


class VideoQuality(StrEnum):
    p2160 = "2160p"
    p1080 = "1080p"
    p720 = "720p"


@dataclass
class ResourceInfo:
    resource_title: str
    torrent_url: str

    published_date: Optional[str] = None
    anime_name: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    fansub: Optional[str] = None
    quality: Optional[VideoQuality] = None
    language: Optional[str] = None
    version: int = 1

    def __hash__(self):
        return hash(self.resource_title)

    def __str__(self) -> str:
        season_format = f"{self.season:02d}" if self.season else "N/A"
        episode_format = f"{self.episode:02d}" if self.episode else "N/A"
        return f"ResourceInfo({self.resource_title} / {self.anime_name} S{season_format}E{episode_format} [{self.fansub}][{self.quality}])"


@dataclass
class FeedEntry:
    resource_title: str
    torrent_url: str
    published_date: Optional[str] = None
    homepage_url: Optional[str] = None
    author: Optional[str] = None

    def __hash__(self):
        return hash(self.resource_title)
