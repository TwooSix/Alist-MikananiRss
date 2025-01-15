from ..utils import Singleton
from .base import ExtractorBase
from .models import AnimeNameExtractResult, ResourceTitleExtractResult
from .regex import RegexExtractor


class Extractor(metaclass=Singleton):
    def __init__(self, extractor: ExtractorBase = None):
        self._extractor = extractor
        self._tmp_regex_extractor = RegexExtractor()

    @classmethod
    def initialize(cls, extractor: ExtractorBase):
        """Initialize the Extractor with a specific extractor."""
        instance_ = cls()
        instance_.set_extractor(extractor)

    def set_extractor(self, extractor: ExtractorBase):
        """Set the extractor to be used."""
        self._extractor = extractor

    @classmethod
    async def analyse_anime_name(cls, anime_name: str) -> AnimeNameExtractResult:
        # chatgpt对番剧名分析不稳定，所以固定用正则分析番剧名
        instance = cls()
        if instance._extractor is None:
            raise RuntimeError("Extractor is not initialized")
        return await instance._tmp_regex_extractor.analyse_anime_name(anime_name)

    @classmethod
    async def analyse_resource_title(
        cls, resource_name: str, use_tmdb: bool = True
    ) -> ResourceTitleExtractResult:
        instance = cls()
        if instance._extractor is None:
            raise RuntimeError("Extractor is not initialized")
        return await instance._extractor.analyse_resource_title(resource_name, use_tmdb)
