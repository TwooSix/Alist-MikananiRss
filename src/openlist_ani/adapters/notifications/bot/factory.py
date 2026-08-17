from __future__ import annotations

from typing import Any

from .base import BotBase
from .feishu import FeishuBot
from .pushplus import PushPlusBot
from .telegram import TelegramBot
from .wechat import WechatBot


class BotFactory:
    """Create notification bots through one explicit built-in mapping."""

    def create_bot(self, bot_type: str, config: dict[str, Any]) -> BotBase:
        key = bot_type.strip().lower()
        if not key:
            raise ValueError("Notification bot type cannot be empty")
        builders = {
            "telegram": _create_telegram,
            "pushplus": _create_pushplus,
            "wechat": _create_wechat,
            "feishu": _create_feishu,
        }
        try:
            builder = builders[key]
        except KeyError as error:
            available = ", ".join(sorted(builders))
            raise ValueError(
                f"Unknown notification bot '{bot_type}'. Available: {available}"
            ) from error
        return builder(config)


def _create_telegram(config: dict[str, Any]) -> BotBase:
    bot_token = config.get("bot_token")
    user_id = config.get("user_id")
    if not bot_token or not user_id:
        raise ValueError("Telegram bot requires 'bot_token' and 'user_id' in config")
    return TelegramBot(bot_token=bot_token, user_id=user_id)


def _create_pushplus(config: dict[str, Any]) -> BotBase:
    user_token = config.get("user_token")
    if not user_token:
        raise ValueError("PushPlus bot requires 'user_token' in config")
    channel = config.get("channel")
    return PushPlusBot(user_token=user_token, channel=channel)


def _create_wechat(config: dict[str, Any]) -> BotBase:
    account_id = config.get("account_id")
    token = config.get("token")
    chat_id = config.get("home_channel") or config.get("chat_id")
    if not account_id or not token:
        raise ValueError("WeChat bot requires 'account_id' and 'token' in config")
    if not chat_id:
        raise ValueError("WeChat bot requires 'home_channel' or 'chat_id' in config")
    return WechatBot(
        chat_id=chat_id,
        account_id=str(account_id),
        token=str(token),
        base_url=str(config.get("base_url") or "https://ilinkai.weixin.qq.com"),
    )


def _create_feishu(config: dict[str, Any]) -> BotBase:
    app_id = config.get("app_id")
    app_secret = config.get("app_secret")
    if not app_id or not app_secret:
        raise ValueError("Feishu bot requires 'app_id' and 'app_secret' in config")
    return FeishuBot(
        app_id=str(app_id),
        app_secret=str(app_secret),
        receive_id=config.get("receive_id"),
        receive_id_type=config.get("receive_id_type"),
        domain=str(config.get("domain") or "feishu"),
        state_dir=str(config.get("state_dir") or "data/messaging"),
    )
