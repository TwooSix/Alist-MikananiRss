from dataclasses import dataclass, field
from enum import StrEnum
from typing import List, Optional


class VideoQuality(StrEnum):
    p2160 = "2160p"
    p1080 = "1080p"
    p720 = "720p"


class LanguageType(StrEnum):
    SIMPLIFIED_CHINESE = "简"
    TRADITIONAL_CHINESE = "繁"
    JAPANESE = "日"
    UNKNOWN = "Unknown"


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
    languages: List[str] = field(default_factory=list)
    version: int = 1

    def __hash__(self):
        return hash(self.resource_title)

    def __str__(self) -> str:
        fields = [
            ("Title", self.resource_title),
            ("Anime", self.anime_name),
            ("Season", f"{self.season:02d}" if self.season is not None else "--"),
            ("Episode", f"{self.episode:02d}" if self.episode is not None else "--"),
            ("Fansub", self.fansub or "--"),
            ("Quality", str(self.quality) if self.quality else "--"),
            ("Language", self.languages or "--"),
            ("Date", self.published_date or "--"),
            ("Version", self.version),
            ("URL", self.torrent_url),
        ]

        return "\n".join(f"{name:8}: {value}" for name, value in fields)


@dataclass
class FeedEntry:
    resource_title: str
    torrent_url: str
    published_date: Optional[str] = None
    homepage_url: Optional[str] = None
    author: Optional[str] = None

    def __hash__(self):
        return hash(self.resource_title)
