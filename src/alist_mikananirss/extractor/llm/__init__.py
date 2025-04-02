from enum import StrEnum

from .base import LLMProvider
from .deepseek import DeepSeekProvider
from .openai import OpenAIProvider


class LLMProviderType(StrEnum):
    """Enum for LLM provider types"""

    OPENAI = "openai"
    DEEPSEEK = "deepseek"


def create_llm_provider(provider_type: LLMProviderType, **kwargs) -> LLMProvider:
    """Create an LLM provider instance based on the specified type"""
    if provider_type == LLMProviderType.OPENAI:
        return OpenAIProvider(**kwargs)
    elif provider_type == LLMProviderType.DEEPSEEK:
        return DeepSeekProvider(**kwargs)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
