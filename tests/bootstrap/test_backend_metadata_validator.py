from types import SimpleNamespace

import pytest

import openlist_ani.bootstrap.backend as backend
from openlist_ani.adapters.configuration.models import UserConfig


def test_regex_parser_mode_does_not_create_validator_llm_client(monkeypatch):
    monkeypatch.setattr(
        backend,
        "config",
        SimpleNamespace(
            metadata_parser=SimpleNamespace(provider="regex"),
            llm=SimpleNamespace(
                openai_api_key="configured",
                provider_type="openai",
                openai_base_url="https://example.invalid/v1",
                openai_model="unused",
            ),
        ),
    )

    def fail_if_called(_settings):
        raise AssertionError("regex+tmdb validation must not create an LLM client")

    monkeypatch.setattr(backend, "create_llm_client", fail_if_called)

    assert backend._create_validator_llm_client() is None


def test_backend_rejects_invalid_runtime_config_before_composition(monkeypatch):
    config = SimpleNamespace(
        data=UserConfig(),
        load_failed=False,
        log=SimpleNamespace(level="INFO", rotation="00:00", retention="1 week"),
    )
    monkeypatch.setattr(backend, "get_config", lambda: config)
    monkeypatch.setattr(backend, "configure_logger", lambda **_kwargs: None)

    with pytest.raises(SystemExit):
        backend._load_runtime_config()
