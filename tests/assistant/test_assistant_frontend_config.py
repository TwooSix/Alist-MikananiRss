from __future__ import annotations

import pytest
from pydantic import ValidationError

from openlist_ani.adapters.configuration.models import (
    AssistantConfig,
    FeishuAssistantConfig,
    TelegramAssistantConfig,
    WechatAssistantConfig,
)
from openlist_ani.assistant import _enabled_frontend_names, _validate_frontend_config


def test_enabled_frontends_require_credentials_and_an_allowlist():
    cases = [
        (
            AssistantConfig(enabled=True, wechat=WechatAssistantConfig(enabled=True)),
            "account_id",
        ),
        (
            AssistantConfig(enabled=True, feishu=FeishuAssistantConfig(enabled=True)),
            "app_id",
        ),
        (
            AssistantConfig(
                enabled=True,
                telegram=TelegramAssistantConfig(enabled=True, bot_token="token"),
            ),
            "allowed user",
        ),
    ]

    for config, expected_error in cases:
        assert any(
            expected_error in error for error in _validate_frontend_config(config)
        )


def test_remote_allowlists_reject_invalid_user_ids():
    with pytest.raises(ValidationError):
        TelegramAssistantConfig(allowed_users=[0])
    with pytest.raises(ValidationError):
        WechatAssistantConfig(allowed_users=["  "])
    with pytest.raises(ValidationError):
        FeishuAssistantConfig(allowed_users=[""])


def test_multiple_valid_frontends_can_run_together():
    disabled = AssistantConfig(
        telegram=TelegramAssistantConfig(bot_token="token", allowed_users=[123])
    )
    assert any("disabled" in error for error in _validate_frontend_config(disabled))

    config = AssistantConfig(
        enabled=True,
        telegram=TelegramAssistantConfig(bot_token="token", allowed_users=[123]),
        wechat=WechatAssistantConfig(
            enabled=True,
            account_id="bot@im.bot",
            token="wechat-token",
            home_channel="user@im.wechat",
            allowed_users=["user@im.wechat"],
        ),
    )

    assert _validate_frontend_config(config) == []
    assert _enabled_frontend_names(config) == ["telegram", "wechat"]
