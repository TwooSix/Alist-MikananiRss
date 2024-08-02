from .base import ExtractorBase
from .models import AnimeNameExtractResult, ResourceTitleExtractResult
from .regex import RegexExtractor


class Extractor:
    _instance = None
    _extractor = None
    _tmp_regex_extractor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Extractor, cls).__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, extractor: ExtractorBase):
        """Initialize the Extractor with a specific extractor."""
        if cls._instance is None:
            cls._instance = cls()
        cls._extractor = extractor
        cls._tmp_regex_extractor = RegexExtractor()

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of Extractor."""
        if cls._instance is None:
            raise ValueError(
                "Extractor not initialized. Please use initialize() first."
            )
        return cls._instance

    @classmethod
    async def analyse_anime_name(cls, anime_name: str) -> AnimeNameExtractResult:
        # chatgpt对番剧名分析不稳定，所以固定用正则分析番剧名
        instance = cls.get_instance()
        return await instance._tmp_regex_extractor.analyse_anime_name(anime_name)

    @classmethod
    async def analyse_resource_title(
        cls, resource_name: str
    ) -> ResourceTitleExtractResult:
        instance = cls.get_instance()
        return await instance._extractor.analyse_resource_title(resource_name)
