from __future__ import annotations

import pytest
from pydantic import ValidationError

from openlist_ani.adapters.configuration.models import (
    AssistantConfig,
    FeishuAssistantConfig,
    TelegramAssistantConfig,
    WechatAssistantConfig,
)
from openlist_ani.assistant import (
    _enabled_frontend_names,
    _validate_frontend_config,
)


def test_validate_frontend_config_requires_wechat_setup_output():
    cfg = AssistantConfig(wechat=WechatAssistantConfig(enabled=True))

    errors = _validate_frontend_config(cfg)

    assert any("account_id" in error for error in errors)
    assert any("token" in error for error in errors)
    assert any("home_channel" in error for error in errors)
    assert any("openlist-ani-wechat-login" in error for error in errors)


def test_validate_frontend_config_accepts_wechat_setup_output():
    cfg = AssistantConfig(
        wechat=WechatAssistantConfig(
            enabled=True,
            account_id="bot@im.bot",
            token="token",
            home_channel="user@im.wechat",
            allowed_users=["user@im.wechat"],
        )
    )

    assert _validate_frontend_config(cfg) == []


def test_validate_frontend_config_requires_feishu_app_credentials():
    cfg = AssistantConfig(feishu=FeishuAssistantConfig(enabled=True))

    errors = _validate_frontend_config(cfg)

    assert any("app_id" in error for error in errors)
    assert any("app_secret" in error for error in errors)
    assert any("allowed user" in error for error in errors)


def test_validate_frontend_config_rejects_empty_telegram_allowlist():
    cfg = AssistantConfig(
        telegram=TelegramAssistantConfig(enabled=True, bot_token="token")
    )

    errors = _validate_frontend_config(cfg)

    assert any("allowed user" in error for error in errors)


def test_remote_allowlists_reject_invalid_placeholder_values():
    with pytest.raises(ValidationError, match="positive user IDs"):
        TelegramAssistantConfig(allowed_users=[0])
    with pytest.raises(ValidationError, match="empty user IDs"):
        WechatAssistantConfig(allowed_users=["  "])
    with pytest.raises(ValidationError, match="empty user IDs"):
        FeishuAssistantConfig(allowed_users=[""])


def test_enabled_frontend_names_allow_telegram_and_wechat_to_coexist():
    cfg = AssistantConfig(
        telegram=TelegramAssistantConfig(bot_token="token", allowed_users=[123]),
        wechat=WechatAssistantConfig(
            enabled=True,
            account_id="bot@im.bot",
            token="wechat-token",
            home_channel="user@im.wechat",
            allowed_users=["user@im.wechat"],
        ),
    )

    assert _enabled_frontend_names(cfg) == ["telegram", "wechat"]
