from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Protocol

from openlist_ani.logger import logger

from openlist_ani.assistant.contracts import (
    AssistantLoop,
    EventType,
    LoopEvent,
    PendingMessage,
)
from openlist_ani.assistant.frontend.base import Frontend
from openlist_ani.assistant.frontend.progress import narration_preview, progress_line
from openlist_ani.assistant.logging_format import format_log_text
from openlist_ani.integrations.messaging.models import InboundMessage
from openlist_ani.integrations.messaging.state_store import MessagingStateStore

_PROGRESS_EVENT_TYPES = {
    EventType.THINKING,
    EventType.SKILL_SELECTED,
    EventType.SCRIPT_STARTED,
    EventType.SCRIPT_FINISHED,
    EventType.RETRYING,
    EventType.CONFIRMATION_REQUIRED,
}


class TextMessenger(Protocol):
    platform: str

    async def listen(self, handler): ...

    async def send_text(self, chat_id: str | None, text: str) -> bool: ...


class MessageAuthorizer(Protocol):
    def is_authorized(self, message: InboundMessage) -> bool: ...


class AllowedTargetAuthorizer:
    def __init__(
        self,
        allowed_values: Iterable[str],
        key: Callable[[InboundMessage], str],
    ) -> None:
        self._allowed_values = set(allowed_values)
        self._key = key

    def is_authorized(self, message: InboundMessage) -> bool:
        return self._key(message) in self._allowed_values


class AllowedUserAuthorizer(AllowedTargetAuthorizer):
    def __init__(self, allowed_users: Iterable[str]) -> None:
        super().__init__(allowed_users, lambda message: message.target.user_id)


class AllowedChatAuthorizer(AllowedTargetAuthorizer):
    def __init__(self, allowed_chats: Iterable[str]) -> None:
        super().__init__(allowed_chats, lambda message: message.target.chat_id)


class AllOfAuthorizer:
    def __init__(self, *authorizers: MessageAuthorizer) -> None:
        self._authorizers = authorizers

    def is_authorized(self, message: InboundMessage) -> bool:
        return all(item.is_authorized(message) for item in self._authorizers)


class MessagingFrontend(Frontend):
    """Generic text messaging frontend for WeChat and Feishu."""

    def __init__(
        self,
        *,
        platform: str,
        messenger: TextMessenger,
        loop: AssistantLoop,
        loop_factory: Callable[[], AssistantLoop] | None = None,
        state_store: MessagingStateStore | None = None,
        allowed_users: list[str] | None = None,
        authorizer: MessageAuthorizer | None = None,
        enable_notify_home_command: bool = True,
    ) -> None:
        super().__init__(loop)
        self.platform = platform
        self._messenger = messenger
        self._loop_factory = loop_factory
        self._state_store = state_store
        self._authorizer = authorizer or AllowedUserAuthorizer(allowed_users or [])
        self._enable_notify_home_command = enable_notify_home_command
        self._chat_loops: dict[str, AssistantLoop] = {}
        self._active_turns: set[str] = set()

    async def run(self) -> None:
        logger.info(f"Starting {self.platform} assistant frontend...")
        await self._messenger.listen(self.handle_inbound)

    async def shutdown(self) -> None:
        loops = list(dict.fromkeys(self._chat_loops.values()))
        for loop in loops:
            await loop.shutdown()
        self._chat_loops.clear()

    async def send_response(self, text: str) -> None:
        raise NotImplementedError("MessagingFrontend sends through inbound targets")

    async def handle_inbound(self, message: InboundMessage) -> None:
        authorized = self._authorizer.is_authorized(message)
        if not authorized:
            logger.warning(
                f"{self.platform} message rejected: unauthorized sender "
                f"(chars={len(message.text)})"
            )
            logger.debug(
                f"{self.platform} authorization failed: "
                f"chat_id={message.target.chat_id}, user_id={message.target.user_id}"
            )
            await self._messenger.send_text(message.target.chat_id, "Unauthorized.")
            return

        logger.info(
            f"{self.platform} message received: {format_log_text(message.text)}"
        )
        if await self._handle_builtin_command(message):
            return

        await self._process_user_turn(message, message.text)

    async def _process_user_turn(self, message: InboundMessage, text: str) -> None:
        session_key = self._session_key(message)
        loop = self._get_loop(message)
        if session_key in self._active_turns:
            queued = loop.message_queue.enqueue(PendingMessage(content=text))
            logger.info(
                f"{self.platform} message received while a reply is running; "
                f"queued for this conversation: {format_log_text(text)}"
            )
            logger.debug(
                f"Queued {self.platform} message: session_key={session_key}, "
                f"seq={queued.seq}, queue_len={len(loop.message_queue)}, "
                f"pending_prompts={loop.message_queue.pending_prompt_count()}"
            )
            await self._messenger.send_text(
                message.target.chat_id,
                f"请求已排队（#{queued.seq}），当前任务完成后会继续处理。",
            )
            return

        self._active_turns.add(session_key)
        turn_started_at = time.monotonic()
        logger.debug(
            f"{self.platform} turn started: session_key={session_key}, "
            f"chat_id={message.target.chat_id}, chars={len(text)}, "
            f"active_turns={len(self._active_turns)}"
        )
        try:
            pending_texts = [text]
            while pending_texts:
                current_text = pending_texts.pop(0)
                confirmation_boundary_seq = await self._process_single_turn(
                    message,
                    loop,
                    current_text,
                    session_key=session_key,
                    turn_started_at=turn_started_at,
                )
                pending = loop.message_queue.drain_prompts()
                if confirmation_boundary_seq is not None:
                    stale = [
                        item
                        for item in pending
                        if item.seq is None or item.seq <= confirmation_boundary_seq
                    ]
                    pending = [
                        item
                        for item in pending
                        if item.seq is not None and item.seq > confirmation_boundary_seq
                    ]
                    if stale:
                        sequence = ", ".join(
                            f"#{item.seq}" for item in stale if item.seq is not None
                        )
                        await self._messenger.send_text(
                            message.target.chat_id,
                            f"排队消息 {sequence or '（未知）'} 是在确认详情展示前"
                            "发送的，因此不会被视为同意。请阅读详情后重新发送确认。",
                        )
                pending_texts.extend(item.content for item in pending)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.platform} frontend failed: {exc}")
            await self._messenger.send_text(message.target.chat_id, f"Error: {exc}")
        finally:
            self._active_turns.discard(session_key)

    async def _process_single_turn(
        self,
        message: InboundMessage,
        loop: AssistantLoop,
        text: str,
        *,
        session_key: str,
        turn_started_at: float,
    ) -> int | None:
        final_text = ""
        error_text = ""
        confirmation_required = False
        narration_parts: list[str] = []
        progress_messages: set[str] = set()
        async for event in loop.process(text):
            if event.type == EventType.CONFIRMATION_REQUIRED:
                confirmation_required = True
            final_text, error_text = await self._consume_turn_event(
                event,
                chat_id=message.target.chat_id,
                final_text=final_text,
                error_text=error_text,
                narration_parts=narration_parts,
                progress_messages=progress_messages,
            )
        response = final_text.strip() or error_text or "No response."
        await self._send_rich_or_text(
            message.target.chat_id,
            title="Assistant 结果",
            text=response,
            template="green",
        )
        confirmation_boundary_seq = (
            max(loop.message_queue.pending_prompt_seqs(), default=0)
            if confirmation_required
            else None
        )
        logger.info(f"{self.platform} response sent.")
        logger.debug(
            f"{self.platform} turn finished: session_key={session_key}, "
            f"chat_id={message.target.chat_id}, final_chars={len(response)}, "
            f"elapsed_ms={int((time.monotonic() - turn_started_at) * 1000)}"
        )
        return confirmation_boundary_seq

    async def _consume_turn_event(
        self,
        event: LoopEvent,
        *,
        chat_id: str | None,
        final_text: str,
        error_text: str,
        narration_parts: list[str],
        progress_messages: set[str],
    ) -> tuple[str, str]:
        if event.type == EventType.DONE and event.text:
            return event.text, error_text
        if event.type == EventType.ERROR and event.text:
            return final_text, f"Error: {event.text}"
        if event.type == EventType.TEXT_DELTA and event.text:
            narration_parts.append(event.text)
            return final_text, error_text
        if event.type not in _PROGRESS_EVENT_TYPES:
            return final_text, error_text

        narration = narration_preview("".join(narration_parts))
        narration_parts.clear()
        if narration:
            await self._send_progress_once(
                chat_id, f"💭 {narration}", progress_messages
            )
        if progress := progress_line(event):
            await self._send_progress_once(chat_id, progress, progress_messages)
        return final_text, error_text

    async def _send_progress_once(
        self, chat_id: str | None, text: str, sent: set[str]
    ) -> None:
        if text in sent:
            return
        sent.add(text)
        await self._send_rich_or_text(
            chat_id,
            title="Assistant 处理进度",
            text=text,
            template="blue",
        )

    async def _send_rich_or_text(
        self,
        chat_id: str | None,
        *,
        title: str,
        text: str,
        template: str,
    ) -> None:
        send_card = getattr(self._messenger, "send_card", None)
        if self.platform == "feishu" and callable(send_card):
            try:
                if await send_card(
                    chat_id,
                    title=title,
                    text=text,
                    template=template,
                ):
                    return
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    f"Feishu card send failed; falling back to text: {error}"
                )
        await self._messenger.send_text(chat_id, text)

    def _get_loop(self, message: InboundMessage) -> AssistantLoop:
        session_key = self._session_key(message)
        if session_key in self._chat_loops:
            return self._chat_loops[session_key]

        loop = self._loop_factory() if self._loop_factory else self._loop
        self._chat_loops[session_key] = loop
        return loop

    async def _handle_builtin_command(self, message: InboundMessage) -> bool:
        text = message.text.strip()
        if text == "/id":
            lines = [
                f"platform={self.platform}",
                f"chat_id={message.target.chat_id}",
                f"chat_type={message.target.chat_type}",
                f"user_id={message.target.user_id}",
            ]
            if message.target.receive_id_type:
                lines.append(f"receive_id_type={message.target.receive_id_type}")
            await self._messenger.send_text(message.target.chat_id, "\n".join(lines))
            return True

        if text == "/set-notify-home" and self._enable_notify_home_command:
            if self._state_store is None:
                raise RuntimeError("Messaging state store is not configured")
            self._state_store.save_notification_target(self.platform, message.target)
            await self._messenger.send_text(
                message.target.chat_id,
                "Notification target set to the current conversation.",
            )
            return True

        if text == "/clear":
            loop = self._get_loop(message)
            loop.reset()
            await self._messenger.send_text(
                message.target.chat_id, "New session started."
            )
            return True

        if text == "/cancel":
            loop = self._get_loop(message)
            await loop.cancel()
            await self._messenger.send_text(
                message.target.chat_id, "已取消当前请求并清空等待队列。"
            )
            return True

        if text == "/status":
            loop = self._get_loop(message)
            await self._messenger.send_text(message.target.chat_id, loop.status())
            return True

        if text.startswith("/") and await self._handle_skill_command(message):
            return True

        return False

    async def _handle_skill_command(self, message: InboundMessage) -> bool:
        parts = message.text.strip().split(None, 1)
        command = parts[0].lstrip("/").lower() if parts else ""
        user_text = parts[1] if len(parts) > 1 else ""
        if command == "skill":
            skill_parts = user_text.split(None, 1)
            if not skill_parts:
                await self._messenger.send_text(
                    message.target.chat_id, "用法：/skill <name> [request]"
                )
                return True
            command = skill_parts[0]
            user_text = skill_parts[1] if len(skill_parts) > 1 else ""
        skill_name = command.replace("_", "-")
        if not skill_name:
            return False
        augmented = (
            f"Use the installed Agent Skill named '{skill_name}' for this request."
            + (f"\n\nUser request: {user_text}" if user_text else "")
        )
        await self._process_user_turn(message, augmented)
        return True

    def _session_key(self, message: InboundMessage) -> str:
        return f"{self.platform}:{message.target.chat_id}:{message.target.user_id}"


def _friendly_progress(event_type: EventType, text: str) -> str:
    return progress_line(LoopEvent(event_type, text))
