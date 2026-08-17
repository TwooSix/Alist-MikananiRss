"""Small frontend contract shared by agent-harness adapters.

This module deliberately contains no model provider, tool execution, context,
memory, session, or subagent logic. Those concerns belong to the selected
external agent harness.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol


class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    THINKING = "thinking"
    SKILL_SELECTED = "skill_selected"
    SCRIPT_STARTED = "script_started"
    SCRIPT_FINISHED = "script_finished"
    CONFIRMATION_REQUIRED = "confirmation_required"
    TEXT_DELTA = "text_delta"
    QUEUED = "queued"
    RETRYING = "retrying"
    ERROR = "error"
    DONE = "done"


@dataclass
class LoopEvent:
    type: EventType
    text: str = ""
    detail: str = ""
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class PendingMessage:
    content: str
    mode: Literal["prompt", "notification"] = "prompt"
    timestamp: float = field(default_factory=time.time)
    seq: int | None = None


class MessageQueue:
    """Minimal queue used by chat frontends when a harness turn is busy."""

    def __init__(self) -> None:
        self._queue: list[PendingMessage] = []
        self._changed = asyncio.Event()
        self._next_seq = 1

    def enqueue(self, message: PendingMessage) -> PendingMessage:
        if message.seq is None:
            message.seq = self._next_seq
            self._next_seq += 1
        self._queue.append(message)
        self._changed.set()
        return message

    def has_pending_prompts(self) -> bool:
        return any(item.mode == "prompt" for item in self._queue)

    def pending_prompt_count(self) -> int:
        return sum(item.mode == "prompt" for item in self._queue)

    def pending_prompt_seqs(self) -> list[int]:
        return [
            item.seq
            for item in self._queue
            if item.mode == "prompt" and item.seq is not None
        ]

    def oldest_prompt_age_ms(self) -> int | None:
        timestamps = [item.timestamp for item in self._queue if item.mode == "prompt"]
        if not timestamps:
            return None
        return max(0, int((time.time() - min(timestamps)) * 1000))

    def drain_prompts(self) -> list[PendingMessage]:
        prompts = [item for item in self._queue if item.mode == "prompt"]
        self._queue = [item for item in self._queue if item.mode != "prompt"]
        if not self._queue:
            self._changed.clear()
        return prompts

    def clear(self) -> None:
        self._queue.clear()
        self._changed.clear()

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)


class AssistantLoop(Protocol):
    message_queue: MessageQueue

    def process(
        self, user_text: str, **kwargs: object
    ) -> AsyncGenerator[LoopEvent, None]: ...

    def reset(self) -> None: ...

    async def cancel(self) -> None: ...

    def status(self) -> str: ...

    async def shutdown(self) -> None: ...


__all__ = [
    "AssistantLoop",
    "EventType",
    "LoopEvent",
    "MessageQueue",
    "PendingMessage",
]
