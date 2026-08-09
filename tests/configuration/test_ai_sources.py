from __future__ import annotations

import pytest
from pydantic import ValidationError

from openlist_ani.adapters.configuration.models import AISourceConfig, UserConfig


def test_api_sources_receive_the_official_endpoint_defaults():
    openai = AISourceConfig(
        type="api", provider="openai-compatible", api_key="key", model="model"
    )
    anthropic = AISourceConfig(
        type="api", provider="anthropic-messages", api_key="key", model="model"
    )

    assert openai.base_url == "https://api.openai.com/v1"
    assert anthropic.base_url == "https://api.anthropic.com"


def test_api_source_requires_credentials_and_a_model():
    for missing in ("api_key", "model"):
        values = {
            "type": "api",
            "provider": "openai-compatible",
            "api_key": "key",
            "model": "model",
        }
        values[missing] = ""
        with pytest.raises(ValidationError):
            AISourceConfig.model_validate(values)


def test_api_and_agent_specific_fields_cannot_be_mixed():
    invalid = [
        {"type": "agent", "agent": "pi", "api_key": "not-allowed"},
        {
            "type": "api",
            "provider": "openai-compatible",
            "api_key": "key",
            "model": "model",
            "agent": "pi",
        },
    ]

    for values in invalid:
        with pytest.raises(ValidationError):
            AISourceConfig.model_validate(values)


def test_metadata_and_assistant_can_select_sources_independently():
    config = UserConfig.model_validate(
        {
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


def test_unknown_selected_source_is_rejected_with_consumer_context():
    with pytest.raises(ValidationError, match="metadata.ai_source"):
        UserConfig.model_validate(
            {
                "ai": {"sources": {"available": {"type": "agent", "agent": "pi"}}},
                "metadata": {"pipeline": ["ai"], "ai_source": "missing"},
            }
        )


def test_explicit_source_selection_must_be_defined_and_used():
    cases = [
        (
            {"metadata": {"pipeline": ["ai"], "ai_source": "missing"}},
            "metadata.ai_source",
        ),
        (
            {
                "ai": {"sources": {"primary": {"type": "agent", "agent": "pi"}}},
                "metadata": {
                    "pipeline": ["regex", "tmdb"],
                    "ai_source": "primary",
                },
            },
            "does not contain 'ai'",
        ),
        ({"assistant": {"backend": "missing"}}, "assistant.backend"),
    ]

    for payload, error in cases:
        with pytest.raises(ValidationError, match=error):
            UserConfig.model_validate(payload)


def test_metadata_pipeline_default_is_not_changed_by_assistant_sources():
    assert UserConfig().metadata_provider_names() == ("regex", "tmdb")
    configured = UserConfig.model_validate(
        {"ai": {"sources": {"primary": {"type": "agent", "agent": "pi"}}}}
    )

    assert configured.metadata_provider_names() == ("regex", "tmdb")
