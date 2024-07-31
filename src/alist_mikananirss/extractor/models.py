class ResourceNameInfo:
    def __init__(
        self,
        episode: int | float = None,
        season: int = None,
        quality: str = None,
        language: str = None,
    ) -> None:
        self.episode = episode
        self.season = season
        self.quality = quality
        self.language = language

    def set_episode(self, episode: int | float):
        self.episode = episode

    def set_season(self, season: int):
        self.season = season

    def set_quality(self, quality: str):
        self.quality = quality

    def set_language(self, language: str):
        self.language = language

    def __str__(self) -> str:
        return f"Episode: {self.episode}, Season: {self.season}, Quality: {self.quality}, Language: {self.language}"


class AnimeNameInfo:
    def __init__(self, anime_name: str = None, season: int = None) -> None:
        self.anime_name = anime_name
        self.season = season

    def set_anime_name(self, anime_name: str):
        self.anime_name = anime_name

    def set_season(self, season: int):
        self.season = season

    def __str__(self) -> str:
        return f"Anime Name: {self.anime_name}, Season: {self.season}"


class AnimeInfo:
    def __init__(
        self,
        anime_name: str = "",
        season: int = -1,
        episode: int | float = -1,
        quality: str = "",
        language: str = "",
    ) -> None:
        self.anime_name = anime_name
        self.season = season
        self.episode = episode
        self.quality = quality
        self.language = language

    def __str__(self) -> str:
        return f"Anime Name: {self.anime_name}, Season: {self.season}, Episode: {self.episode}, Quality: {self.quality}, Language: {self.language}"
