from enum import StrEnum

from .base import ExtractorBase
from .extractor import Extractor
from .llm import create_llm_provider
from .llm_extractor import LLMExtractor
from .models import AnimeNameExtractResult, ResourceTitleExtractResult, VideoQuality
from .regex import RegexExtractor
