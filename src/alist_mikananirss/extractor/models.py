from dataclasses import dataclass
from typing import Optional


@dataclass
class ResourceTitleExtractResult:
    anime_name: str
    season: int
    episode: int
    quality: Optional[str] = None
    fansub: Optional[str] = None
    language: Optional[str] = None


@dataclass
class AnimeNameExtractResult:
    anime_name: str
    season: int
