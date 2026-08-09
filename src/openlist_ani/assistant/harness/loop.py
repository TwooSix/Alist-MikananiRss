"""Thin event bridge over an external agent harness session."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable

from openlist_ani.assistant.contracts import EventType, LoopEvent, MessageQueue

from .runtime import HarnessSession


class HarnessLoop:
    """Translate a harness session stream into frontend events."""

    def __init__(self, session_factory: Callable[[], HarnessSession]) -> None:
        self._session_factory = session_factory
        self._session = session_factory()
        self._message_queue = MessageQueue()
        self._lock = asyncio.Lock()
        self._reset_pending = False
        self._turn_count = 0
        self._active = False

    async def process(
        self, user_text: str, **_: object
    ) -> AsyncGenerator[LoopEvent, None]:
        async with self._lock:
            self._active = True
            if self._reset_pending:
                await self._session.reset()
                self._reset_pending = False
            try:
                async for event in self._session.stream(user_text):
                    yield event
                    if event.type == EventType.DONE:
                        self._turn_count += 1
            except Exception as error:
                yield LoopEvent(type=EventType.ERROR, text=_friendly_error(error))
            finally:
                self._active = False

    def reset(self) -> None:
        self._message_queue.clear()
        self._reset_pending = True

    async def cancel(self) -> None:
        self._message_queue.clear()
        await self._session.cancel()

    def status(self) -> str:
        state = "正在处理请求" if self._active else "空闲"
        queued = self._message_queue.pending_prompt_count()
        return f"会话状态：{state}\n已完成轮次：{self._turn_count}\n排队请求：{queued}"

    async def shutdown(self) -> None:
        await self._session.close()

    @property
    def message_queue(self) -> MessageQueue:
        return self._message_queue

    @property
    def turn_count(self) -> int:
        return self._turn_count


def _friendly_error(error: Exception) -> str:
    detail = str(error)
    lowered = detail.lower()
    if "automatic pi" in lowered or "pi runtime directory" in lowered:
        return (
            "Pi 自动安装失败。请检查网络和配置目录写权限；也可以手工安装 Pi，"
            "或在 [ai.sources.<name>].executable 中指定路径。详情：" + detail
        )
    if any(
        marker in lowered
        for marker in ("no model selected", "model is not configured", "unknown model")
    ):
        return (
            "Pi 已启动，但没有可用模型。请配置一个 [ai.sources.<name>] API source，"
            "或在本机运行 pi 后使用 /login 完成原生登录和模型选择。"
        )
    if "model" in lowered and any(
        marker in lowered for marker in ("unavailable", "not available", "not found")
    ):
        return "配置的模型不可用，请检查 Agent 原生配置或 source.model。"
    if any(
        marker in lowered
        for marker in ("was not found", "not found", "could not be started")
    ):
        return (
            "Agent 未安装或无法启动。请安装对应的本地 Agent，检查执行权限，"
            "或配置 [ai.sources.<name>].executable。详情：" + detail
        )
    if "timed out" in lowered:
        return "Agent 响应超时，请稍后重试；若持续发生，请检查模型和网络连接。"
    if "rate" in lowered and "limit" in lowered:
        return "模型请求受到限流，请稍后重试。"
    if "auth" in lowered or "login" in lowered or "credential" in lowered:
        return (
            "Agent 凭据无效：API source 请检查 api_key，Agent source 请先在本机"
            "完成对应 Agent 登录。"
        )
    if "skill" in lowered:
        return "Skill 执行失败，请检查对应脚本的参数、依赖和 Backend 状态。"
    if "connection" in lowered or "backend" in lowered:
        return "无法连接 OpenList-Ani Backend，请确认主服务正在运行。"
    return detail


__all__ = ["HarnessLoop"]
