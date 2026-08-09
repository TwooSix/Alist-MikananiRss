from __future__ import annotations

import asyncio

import pytest

from openlist_ani.integrations.messaging.wechat_ilink import (
    WechatIlinkMessenger,
    parse_inbound_message,
)


def test_inbound_message_is_normalized_for_the_assistant():
    inbound = parse_inbound_message(
        {
            "message_id": "msg-1",
            "from_user_id": "user@im.wechat",
            "to_user_id": "bot@im.bot",
            "context_token": "ctx-token",
            "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
        },
        account_id="bot@im.bot",
    )

    assert inbound is not None
    assert inbound.text == "hello"
    assert inbound.target.chat_id == "user@im.wechat"


@pytest.mark.asyncio
async def test_reply_reuses_the_inbound_context_token(monkeypatch):
    sent_payloads = []

    async def fake_post(**kwargs):
        await asyncio.sleep(0)
        sent_payloads.append(kwargs["payload"])
        return {"ret": 0}

    monkeypatch.setattr(
        "openlist_ani.integrations.messaging.wechat_ilink.api_post", fake_post
    )
    messenger = WechatIlinkMessenger(
        account_id="bot@im.bot",
        token="token",
        base_url="https://wx",
        interactive_login=False,
    )
    messenger._remember_context_token(
        {"from_user_id": "user@im.wechat", "context_token": "ctx-token"}
    )

    assert await messenger.send_text("user@im.wechat", "hello") is True
    assert sent_payloads[0]["msg"]["context_token"] == "ctx-token"


@pytest.mark.asyncio
async def test_send_requires_an_explicit_target():
    messenger = WechatIlinkMessenger(
        account_id="bot@im.bot",
        token="token",
        base_url="https://wx",
        interactive_login=False,
    )

    with pytest.raises(ValueError, match="home_channel"):
        await messenger.send_text(None, "hello")


@pytest.mark.asyncio
async def test_login_setup_discovers_the_first_inbound_target(monkeypatch):
    messenger = WechatIlinkMessenger(
        account_id="bot@im.bot",
        token="token",
        base_url="https://wx",
        interactive_login=False,
    )

    async def fake_post(**kwargs):
        await asyncio.sleep(0)
        return {
            "get_updates_buf": "next",
            "msgs": [
                {
                    "message_id": "msg-1",
                    "from_user_id": "notify@im.wechat",
                    "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
                }
            ],
        }

    monkeypatch.setattr(
        "openlist_ani.integrations.messaging.wechat_ilink.api_post", fake_post
    )

    target = await messenger.wait_for_first_message(timeout_seconds=1)

    assert target.chat_id == "notify@im.wechat"
