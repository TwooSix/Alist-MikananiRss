from __future__ import annotations

import pytest
from pydantic import ValidationError

from openlist_ani.adapters.configuration.models import (
    AISourceConfig,
    UserConfig,
)


def test_api_sources_apply_official_base_url_defaults():
    openai = AISourceConfig(
        type="api",
        provider="openai-compatible",
        api_key="key",
        model="model",
    )
    anthropic = AISourceConfig(
        type="api",
        provider="anthropic-messages",
        api_key="key",
        model="model",
    )

    assert openai.base_url == "https://api.openai.com/v1"
    assert anthropic.base_url == "https://api.anthropic.com"


def test_api_source_preserves_custom_base_url():
    source = AISourceConfig(
        type="api",
        provider="openai-compatible",
        api_key="key",
        model="model",
        base_url="https://gateway.example/v1",
    )

    assert source.base_url == "https://gateway.example/v1"


@pytest.mark.parametrize("missing", ["api_key", "model"])
def test_api_source_requires_credentials_and_model(missing):
    values = {
        "type": "api",
        "provider": "openai-compatible",
        "api_key": "key",
        "model": "model",
    }
    values[missing] = ""
    with pytest.raises(ValidationError):
        AISourceConfig.model_validate(values)


def test_agent_source_rejects_api_fields():
    with pytest.raises(ValidationError):
        AISourceConfig(
            type="agent",
            agent="pi",
            api_key="must-not-be-here",
        )


def test_api_source_rejects_agent_fields():
    with pytest.raises(ValidationError):
        AISourceConfig(
            type="api",
            provider="openai-compatible",
            api_key="key",
            model="model",
            agent="pi",
        )


def test_implicit_selection_uses_first_declared_source():
    config = UserConfig.model_validate(
        {
            "config_version": 2,
            "ai": {
                "sources": {
                    "first": {"type": "agent", "agent": "pi"},
                    "second": {"type": "agent", "agent": "codex"},
                }
            },
        }
    )

    assert config.resolve_metadata_ai_source()[0] == "first"
    assert config.resolve_assistant_source()[0] == "first"


def test_metadata_and_assistant_select_independently():
    config = UserConfig.model_validate(
        {
            "config_version": 2,
            "ai": {
                "sources": {
                    "metadata": {"type": "agent", "agent": "pi"},
                    "chat": {"type": "agent", "agent": "codex"},
                }
            },
            "metadata": {"pipeline": ["ai", "tmdb"], "ai_source": "metadata"},
            "assistant": {"backend": "chat"},
        }
    )

    assert config.resolve_metadata_ai_source()[0] == "metadata"
    assert config.resolve_assistant_source()[0] == "chat"


def test_unknown_explicit_source_lists_consumer():
    with pytest.raises(ValidationError, match="metadata.ai_source"):
        UserConfig.model_validate(
            {
                "config_version": 2,
                "ai": {"sources": {"available": {"type": "agent", "agent": "pi"}}},
                "metadata": {"pipeline": ["ai"], "ai_source": "missing"},
            }
        )


def test_pipeline_defaults_depend_on_configured_sources():
    assert UserConfig().metadata_provider_names() == ("regex", "tmdb")
    configured = UserConfig.model_validate(
        {
            "config_version": 2,
            "ai": {"sources": {"primary": {"type": "agent", "agent": "pi"}}},
        }
    )
    assert configured.metadata_provider_names() == ("ai", "tmdb")
