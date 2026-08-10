from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from openlist_ani.assistant.contracts import (
    EventType,
    LoopEvent,
    MessageQueue,
    PendingMessage,
)
from openlist_ani.assistant.frontend.messaging import MessagingFrontend
from openlist_ani.assistant.frontend.telegram import TelegramFrontend
from openlist_ani.integrations.messaging.models import InboundMessage, OutboundTarget


class FakeLoop:
    def __init__(self, response: str = "assistant reply") -> None:
        self.response = response
        self.message_queue = MessageQueue()
        self.process_count = 0

    async def process(self, user_text: str, **_kwargs):
        self.process_count += 1
        await asyncio.sleep(0)
        yield LoopEvent(type=EventType.DONE, text=self.response)

    def reset(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def cancel(self) -> None:
        self.message_queue.clear()

    def status(self) -> str:
        return "idle"


class ConfirmationWithEarlyQueueLoop(FakeLoop):
    def __init__(self) -> None:
        super().__init__("Review this policy conflict, then confirm.")
        self.inputs: list[str] = []

    async def process(self, user_text: str, **_kwargs):
        self.process_count += 1
        self.inputs.append(user_text)
        self.message_queue.enqueue(PendingMessage(content="confirm"))
        yield LoopEvent(type=EventType.CONFIRMATION_REQUIRED)
        yield LoopEvent(type=EventType.DONE, text=self.response)


class FakeMessenger:
    platform = "wechat"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def listen(self, handler):
        self.handler = handler

    async def send_text(self, chat_id: str | None, text: str) -> bool:
        self.sent.append((chat_id or "", text))
        return True


class FakeTelegramMessage:
    def __init__(self, text: str, *, user_id: int = 1, chat_id: int = 123) -> None:
        self.text = text
        self.chat_id = chat_id
        self.from_user = SimpleNamespace(id=user_id)
        self.replies: list[str] = []
        self.reply_kwargs: list[dict] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append(text)
        self.reply_kwargs.append(kwargs)
        return SimpleNamespace()


def _message(text: str, *, user_id: str = "user-1") -> InboundMessage:
    return InboundMessage(
        platform="wechat",
        text=text,
        target=OutboundTarget(
            platform="wechat",
            chat_id="chat-1",
            chat_type="dm",
            user_id=user_id,
        ),
        message_id="msg-1",
    )


@pytest.mark.asyncio
async def test_authorized_message_reaches_the_agent_and_returns_its_answer():
    messenger = FakeMessenger()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=FakeLoop("hello from agent"),
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("hello"))

    assert messenger.sent == [("chat-1", "hello from agent")]


@pytest.mark.asyncio
async def test_empty_allowlist_rejects_before_creating_an_agent_session():
    messenger = FakeMessenger()
    loop = FakeLoop()
    created = 0

    def factory():
        nonlocal created
        created += 1
        return FakeLoop()

    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=loop,
        loop_factory=factory,
    )

    await frontend.handle_inbound(_message("secret"))

    assert messenger.sent == [("chat-1", "Unauthorized.")]
    assert created == 0
    assert loop.process_count == 0


@pytest.mark.asyncio
async def test_group_users_receive_isolated_agent_sessions():
    created: list[FakeLoop] = []

    def factory():
        loop = FakeLoop()
        created.append(loop)
        return loop

    frontend = TelegramFrontend(
        loop=FakeLoop(),
        loop_factory=factory,
        bot_token="token",
        allowed_users=[1, 2],
    )

    first = frontend._get_loop(123, 1)
    same = frontend._get_loop(123, 1)
    second_user = frontend._get_loop(123, 2)

    assert first is same
    assert first is not second_user
    assert len(created) == 2


@pytest.mark.asyncio
async def test_message_queued_before_policy_prompt_is_not_treated_as_confirmation():
    messenger = FakeMessenger()
    loop = ConfirmationWithEarlyQueueLoop()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=loop,
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("download this collection"))

    assert loop.inputs == ["download this collection"]
    assert any("不会被视为同意" in text for _, text in messenger.sent)


@pytest.mark.asyncio
async def test_telegram_message_queued_before_prompt_is_not_confirmation():
    loop = ConfirmationWithEarlyQueueLoop()
    frontend = TelegramFrontend(
        loop=loop,
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("download this collection")

    await frontend._process_user_turn(
        SimpleNamespace(message=message),
        "download this collection",
    )

    assert loop.inputs == ["download this collection"]
    assert any("不会被视为同意" in text for text in message.replies)


@pytest.mark.asyncio
async def test_cancelled_confirmation_cannot_execute_a_write():
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("request")
    status = SimpleNamespace(delete=lambda: asyncio.sleep(0))
    session_key = (123, 1)
    await frontend._send_final_result(
        SimpleNamespace(message=message),
        status,
        ["Confirm this download"],
        confirmation_required=True,
        session_key=session_key,
    )
    nonce = frontend._pending_confirmations[session_key]

    class Query:
        from_user = SimpleNamespace(id=1)

        def __init__(self):
            self.message = message
            self.data = f"oani:cancel:{nonce}"

        async def answer(self, text, **kwargs):
            pass

        async def edit_message_reply_markup(self, **kwargs):
            pass

    await frontend._handle_confirmation(
        SimpleNamespace(callback_query=Query()),
        SimpleNamespace(),
    )

    assert session_key not in frontend._pending_confirmations
    assert message.replies[-1] == "已取消这次写操作。"


@pytest.mark.asyncio
async def test_old_telegram_confirmation_button_cannot_confirm_a_new_request():
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("request")
    status = SimpleNamespace(delete=lambda: asyncio.sleep(0))
    session_key = (123, 1)
    update = SimpleNamespace(message=message)
    await frontend._send_final_result(
        update,
        status,
        ["Confirm first request"],
        confirmation_required=True,
        session_key=session_key,
    )
    old_nonce = frontend._pending_confirmations[session_key]
    await frontend._send_final_result(
        update,
        status,
        ["Confirm second request"],
        confirmation_required=True,
        session_key=session_key,
    )
    current_nonce = frontend._pending_confirmations[session_key]
    assert current_nonce != old_nonce

    class Query:
        data = f"oani:confirm:{old_nonce}"
        from_user = SimpleNamespace(id=1)

        def __init__(self):
            self.message = message
            self.answers: list[tuple[str, dict]] = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

        async def edit_message_reply_markup(self, **kwargs):
            raise AssertionError("stale confirmation must not edit the current prompt")

    query = Query()
    await frontend._handle_confirmation(
        SimpleNamespace(callback_query=query),
        SimpleNamespace(),
    )

    assert frontend._pending_confirmations[session_key] == current_nonce
    assert query.answers == [("该确认请求已失效。", {"show_alert": True})]
