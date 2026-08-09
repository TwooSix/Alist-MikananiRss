from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from openlist_ani.assistant.contracts import EventType, LoopEvent, MessageQueue
from openlist_ani.assistant.frontend.messaging import (
    AllowedChatAuthorizer,
    MessagingFrontend,
)
from openlist_ani.assistant.frontend.telegram import TelegramFrontend
from openlist_ani.integrations.messaging.models import InboundMessage, OutboundTarget


class FakeLoop:
    def __init__(self, response: str = "assistant reply") -> None:
        self.response = response
        self.message_queue = MessageQueue()
        self.closed = False
        self.reset_count = 0
        self.process_count = 0

    async def process(self, user_text: str, **_kwargs):
        self.process_count += 1
        await asyncio.sleep(0)
        yield LoopEvent(type=EventType.DONE, text=self.response)

    def reset(self) -> None:
        self.reset_count += 1

    async def shutdown(self) -> None:
        self.closed = True

    async def cancel(self) -> None:
        self.message_queue.clear()

    def status(self) -> str:
        return "idle"


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
    def __init__(self, text: str, *, user_id: int = 2, chat_id: int = 123) -> None:
        self.text = text
        self.chat_id = chat_id
        self.from_user = SimpleNamespace(id=user_id)
        self.replies: list[str] = []
        self.reply_kwargs: list[dict] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append(text)
        self.reply_kwargs.append(kwargs)
        return SimpleNamespace()


def _message(text: str, chat_id: str = "chat-1") -> InboundMessage:
    return InboundMessage(
        platform="wechat",
        text=text,
        target=OutboundTarget(
            platform="wechat",
            chat_id=chat_id,
            chat_type="dm",
            user_id="user-1",
        ),
        message_id="msg-1",
    )


@pytest.mark.asyncio
async def test_messaging_frontend_routes_message_to_harness_loop():
    messenger = FakeMessenger()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=FakeLoop("hello from agent"),
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("hello"))

    assert messenger.sent[-1] == ("chat-1", "hello from agent")


@pytest.mark.asyncio
async def test_messaging_frontend_rejects_unauthorized_chat():
    messenger = FakeMessenger()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=FakeLoop(),
        authorizer=AllowedChatAuthorizer(["chat-1"]),
    )

    await frontend.handle_inbound(_message("secret", chat_id="chat-2"))

    assert messenger.sent[-1] == ("chat-2", "Unauthorized.")


@pytest.mark.asyncio
async def test_empty_allowlist_rejects_before_session_or_agent_creation():
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
async def test_generic_frontend_shows_deduplicated_progress_before_result():
    class ProgressLoop(FakeLoop):
        async def process(self, user_text: str, **_kwargs):
            yield LoopEvent(type=EventType.THINKING, text="正在解析 RSS…")
            yield LoopEvent(type=EventType.THINKING, text="正在解析 RSS…")
            yield LoopEvent(type=EventType.SCRIPT_STARTED, text="查询资源")
            yield LoopEvent(type=EventType.DONE, text="完成")

    messenger = FakeMessenger()
    frontend = MessagingFrontend(
        platform="feishu",
        messenger=messenger,
        loop=ProgressLoop(),
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("hello"))

    assert [text for _, text in messenger.sent] == [
        "⏳ 正在解析 RSS…",
        "🔧 查询资源",
        "完成",
    ]


@pytest.mark.asyncio
async def test_generic_frontend_exposes_narration_but_uses_done_as_final():
    class ProgressLoop(FakeLoop):
        async def process(self, user_text: str, **_kwargs):
            yield LoopEvent(EventType.TEXT_DELTA, "我先查询资源。")
            yield LoopEvent(EventType.SCRIPT_STARTED, "执行 Skill mikan / search")
            yield LoopEvent(EventType.SCRIPT_FINISHED, "mikan / search 完成")
            yield LoopEvent(EventType.TEXT_DELTA, "中间整理文本，不应成为最终答案。")
            yield LoopEvent(EventType.DONE, "最终答案。")

    messenger = FakeMessenger()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=ProgressLoop(),
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("hello"))

    assert [text for _, text in messenger.sent] == [
        "💭 我先查询资源。",
        "🔧 执行 Skill mikan / search",
        "✅ mikan / search 完成",
        "最终答案。",
    ]


@pytest.mark.asyncio
async def test_feishu_frontend_uses_cards_for_progress_and_result():
    class CardMessenger(FakeMessenger):
        platform = "feishu"

        def __init__(self):
            super().__init__()
            self.cards = []

        async def send_card(self, chat_id, **payload):
            self.cards.append((chat_id, payload))
            return True

    class ProgressLoop(FakeLoop):
        async def process(self, user_text: str, **_kwargs):
            yield LoopEvent(type=EventType.THINKING, text="正在处理…")
            yield LoopEvent(type=EventType.DONE, text="完成")

    messenger = CardMessenger()
    frontend = MessagingFrontend(
        platform="feishu",
        messenger=messenger,
        loop=ProgressLoop(),
        allowed_users=["user-1"],
    )

    await frontend.handle_inbound(_message("hello"))

    assert messenger.sent == []
    assert [payload["title"] for _, payload in messenger.cards] == [
        "Assistant 处理进度",
        "Assistant 结果",
    ]


@pytest.mark.asyncio
async def test_telegram_rejects_unauthorized_user():
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("private", user_id=2)

    await frontend._handle_text(
        SimpleNamespace(message=message),
        SimpleNamespace(),
    )

    assert message.replies == ["Unauthorized."]


@pytest.mark.asyncio
async def test_telegram_rejects_unauthorized_builtin_command():
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("/start", user_id=2)

    await frontend._cmd_start(
        SimpleNamespace(message=message),
        SimpleNamespace(),
    )

    assert message.replies == ["Unauthorized."]


@pytest.mark.asyncio
async def test_telegram_group_users_get_isolated_agent_sessions():
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

    first = await frontend._get_loop(123, 1)
    same = await frontend._get_loop(123, 1)
    second_user = await frontend._get_loop(123, 2)

    assert first is same
    assert first is not second_user
    assert len(created) == 2


@pytest.mark.asyncio
async def test_telegram_shows_actual_agent_timeline_and_only_returns_done_text(
    monkeypatch,
):
    class ProgressLoop(FakeLoop):
        async def process(self, user_text: str, **_kwargs):
            yield LoopEvent(EventType.THINKING, "正在理解订阅查询…")
            yield LoopEvent(EventType.TEXT_DELTA, "我先读取 Mikan Skill，")
            yield LoopEvent(EventType.TEXT_DELTA, "再查询当前订阅。")
            yield LoopEvent(EventType.SKILL_SELECTED, "读取 Skill mikan")
            yield LoopEvent(
                EventType.SCRIPT_STARTED,
                "执行 Skill mikan / subscriptions · username=TwoSix",
            )
            yield LoopEvent(
                EventType.SCRIPT_FINISHED,
                "Skill mikan / subscriptions 完成（1.2s）",
                data={"success": True},
            )
            yield LoopEvent(EventType.TEXT_DELTA, "我已经拿到结果，正在整理。")
            yield LoopEvent(EventType.DONE, "最终只有这一段回答。")

    class StatusMessage:
        def __init__(self):
            self.edits: list[str] = []

        async def edit_text(self, text: str):
            self.edits.append(text)

    monkeypatch.setattr(
        "openlist_ani.assistant.frontend.telegram._EDIT_DEBOUNCE_SECONDS", 0
    )
    frontend = TelegramFrontend(
        loop=ProgressLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    status = StatusMessage()

    final_parts, confirmation = await frontend._stream_events(
        frontend._loop,
        "查询订阅",
        status,
    )

    rendered = "\n".join(status.edits)
    assert "💭 我先读取 Mikan Skill，再查询当前订阅。" in rendered
    assert "🧩 读取 Skill mikan" in rendered
    assert "🔧 执行 Skill mikan / subscriptions · username=TwoSix" in rendered
    assert "✅ Skill mikan / subscriptions 完成（1.2s）" in rendered
    assert "正在生成回答" not in rendered
    assert final_parts == ["最终只有这一段回答。"]
    assert confirmation is False


@pytest.mark.asyncio
async def test_telegram_debounce_applies_pending_tool_status_without_next_event(
    monkeypatch,
):
    class StatusMessage:
        def __init__(self):
            self.edits: list[str] = []

        async def edit_text(self, text: str):
            self.edits.append(text)

    monkeypatch.setattr(
        "openlist_ani.assistant.frontend.telegram._EDIT_DEBOUNCE_SECONDS", 0.01
    )
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    status = StatusMessage()
    state = {
        "last_edit_time": asyncio.get_running_loop().time(),
        "pending": False,
        "pending_text": "",
        "pending_task": None,
    }

    await frontend._debounced_edit(status, ["🔧 执行 Skill mikan / search"], state)
    await asyncio.sleep(0.03)

    assert status.edits == ["🔧 执行 Skill mikan / search"]


@pytest.mark.asyncio
async def test_telegram_confirmation_event_renders_buttons_and_cancel_expires_it():
    frontend = TelegramFrontend(
        loop=FakeLoop(),
        bot_token="token",
        allowed_users=[1],
    )
    message = FakeTelegramMessage("request", user_id=1)
    status = SimpleNamespace(delete=lambda: asyncio.sleep(0))
    session_key = (123, 1)

    await frontend._send_final_result(
        SimpleNamespace(message=message),
        status,
        ["Confirm this download"],
        confirmation_required=True,
        session_key=session_key,
    )

    markup = message.reply_kwargs[-1]["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "oani:confirm"
    assert session_key in frontend._pending_confirmations

    class Query:
        data = "oani:cancel"
        from_user = SimpleNamespace(id=1)

        def __init__(self):
            self.message = message
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

        async def edit_message_reply_markup(self, **kwargs):
            self.markup = kwargs

    query = Query()
    await frontend._handle_confirmation(
        SimpleNamespace(callback_query=query),
        SimpleNamespace(),
    )

    assert session_key not in frontend._pending_confirmations
    assert message.replies[-1] == "已取消这次写操作。"


@pytest.mark.asyncio
async def test_frontend_shutdown_closes_each_harness_loop():
    first = FakeLoop()
    second = FakeLoop()
    frontend = MessagingFrontend(
        platform="wechat",
        messenger=FakeMessenger(),
        loop=first,
        allowed_users=["user-1"],
    )
    frontend._chat_loops = {"one": first, "two": second}

    await frontend.shutdown()

    assert first.closed is True
    assert second.closed is True
