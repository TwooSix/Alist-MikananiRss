from alist_mikananirss.websites import ResourceInfo

from .base import ExtractorBase
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
    async def process(cls, resource_info: ResourceInfo):
        """Use extractor to extract anime info from anime name resource title

        Args:
            resource_info (ResourceInfo)
        """
        if cls._extractor is None:
            raise ValueError(
                "Extractor not initialized. Please use initialize() first."
            )
        # chatgpt对番剧名分析不稳定，所以固定用正则分析番剧名+季度
        anime_name = resource_info.anime_name
        anime_name_info = await cls._tmp_regex_extractor.analyse_anime_name(anime_name)
        anime_name = anime_name_info.anime_name
        season = anime_name_info.season

        resource_name = resource_info.resource_title
        resource_name_info = await cls._extractor.analyse_resource_name(resource_name)
        episode = resource_name_info.episode
        # 若为总集篇，resource_name_info会返回season=0，否则为None
        if resource_name_info.season is not None:
            season = resource_name_info.season
        quality = resource_name_info.quality
        language = resource_name_info.language

        resource_info.anime_name = anime_name
        resource_info.season = season
        resource_info.episode = episode
        resource_info.quality = quality
        resource_info.language = language


# 使用示例
# Extractor.initialize(SomeExtractor())
# resource_info = ResourceInfo(xx)
# await Extractor.process(resource_info)
