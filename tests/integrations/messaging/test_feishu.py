from __future__ import annotations

import asyncio
import json
import sys
import threading
import types

import pytest

from openlist_ani.integrations.messaging.feishu import (
    FeishuMessenger,
    parse_webhook_event,
)
from openlist_ani.integrations.messaging.state_store import MessagingStateStore


def test_webhook_event_is_normalized_for_the_assistant():
    payload = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "chat_type": "group",
                "content": json.dumps({"text": "@_user_1 hello"}),
                "mentions": [{"key": "@_user_1", "id": {"open_id": "ou_bot"}}],
            },
            "sender": {
                "sender_id": {"open_id": "ou_user"},
                "sender_type": "user",
            },
        },
    }

    inbound = parse_webhook_event(payload, bot_open_id="ou_bot")

    assert inbound is not None
    assert inbound.text == "hello"
    assert inbound.target.chat_id == "oc_1"
    assert inbound.target.user_id == "ou_user"


@pytest.mark.asyncio
async def test_websocket_listener_can_be_cancelled_even_if_sdk_blocks(
    tmp_path, monkeypatch
):
    started = threading.Event()
    stop = threading.Event()

    class FakeBuilder:
        def register_p2_im_message_receive_v1(self, callback):
            return self

        def register_p2_im_message_message_read_v1(self, callback):
            return self

        def build(self):
            return {}

    class FakeDispatcherHandler:
        @staticmethod
        def builder(encrypt_key, verification_token):
            return FakeBuilder()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            started.set()
            stop.wait(timeout=5)

    monkeypatch.setitem(
        sys.modules,
        "lark_oapi",
        types.SimpleNamespace(LogLevel=types.SimpleNamespace(WARNING="warning")),
    )
    monkeypatch.setitem(
        sys.modules,
        "lark_oapi.event.dispatcher_handler",
        types.SimpleNamespace(EventDispatcherHandler=FakeDispatcherHandler),
    )
    monkeypatch.setitem(
        sys.modules,
        "lark_oapi.ws",
        types.SimpleNamespace(Client=FakeClient),
    )
    monkeypatch.setattr(
        "openlist_ani.integrations.messaging.feishu.WEBSOCKET_STARTUP_ERROR_GRACE_SECONDS",
        0.01,
    )
    messenger = FeishuMessenger(
        app_id="cli_xxx",
        app_secret="secret",
        store=MessagingStateStore(tmp_path),
    )
    task = asyncio.create_task(messenger._listen_websocket(lambda message: None))
    await asyncio.to_thread(started.wait, 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stop.set()
