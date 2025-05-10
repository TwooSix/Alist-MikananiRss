from enum import StrEnum

from .base import LLMProvider


class LLMProviderType(StrEnum):
    """Enum for LLM provider types"""

    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GOOGLE = "google"


def create_llm_provider(provider_type: LLMProviderType, **kwargs) -> LLMProvider:
    """Create an LLM provider instance based on the specified type"""
    if provider_type == LLMProviderType.OPENAI:
        from .openai import OpenAIProvider

        return OpenAIProvider(**kwargs)
    elif provider_type == LLMProviderType.DEEPSEEK:
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(**kwargs)
    elif provider_type == LLMProviderType.GOOGLE:
        from .google import GoogleProvider

        return GoogleProvider(**kwargs)
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
