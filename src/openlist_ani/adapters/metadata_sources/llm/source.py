"""Resolve public AI source configuration into metadata completion clients."""

from __future__ import annotations

from openlist_ani.adapters.configuration.models import AISourceConfig

from .agent_client import AgentCommandLLMClient
from .client import LLMClient, LLMClientSettings, create_llm_client


def create_source_client(source: AISourceConfig) -> LLMClient:
    if source.type == "agent":
        return AgentCommandLLMClient(source)
    return create_llm_client(
        LLMClientSettings(
            provider_type=source.provider_type,
            api_key=source.api_key,
            base_url=source.base_url,
            model=source.model,
        )
    )


__all__ = ["create_source_client"]
