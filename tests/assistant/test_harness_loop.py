from __future__ import annotations

import pytest

from openlist_ani.assistant.contracts import EventType, LoopEvent
from openlist_ani.assistant.harness.loop import HarnessLoop
from openlist_ani.assistant.harness.runtime import HarnessSession


class FakeSession(HarnessSession):
    def __init__(self) -> None:
        self.reset_count = 0
        self.closed = False

    async def stream(self, prompt: str):
        yield LoopEvent(EventType.THINKING, "thinking")
        yield LoopEvent(EventType.TEXT_DELTA, "hello ")
        yield LoopEvent(EventType.TEXT_DELTA, prompt)
        yield LoopEvent(EventType.DONE, "hello " + prompt)

    async def reset(self) -> None:
        self.reset_count += 1

    async def close(self) -> None:
        self.closed = True

    async def cancel(self) -> None:
        self.cancelled = True


@pytest.mark.asyncio
async def test_harness_loop_only_bridges_frontend_events():
    session = FakeSession()
    loop = HarnessLoop(lambda: session)

    events = [event async for event in loop.process("world")]

    assert [event.type for event in events] == [
        EventType.THINKING,
        EventType.TEXT_DELTA,
        EventType.TEXT_DELTA,
        EventType.DONE,
    ]
    assert events[-1].text == "hello world"


@pytest.mark.asyncio
async def test_harness_owns_reset_and_shutdown_only():
    session = FakeSession()
    loop = HarnessLoop(lambda: session)

    loop.reset()
    await anext(loop.process("again"))
    await loop.shutdown()

    assert session.reset_count == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_missing_agent_is_reported_with_actionable_error():
    class MissingAgentSession(FakeSession):
        async def stream(self, prompt: str):
            raise RuntimeError("Agent executable 'pi' could not be started")
            yield  # pragma: no cover

    loop = HarnessLoop(MissingAgentSession)

    events = [event async for event in loop.process("hello")]

    assert events[0].type == EventType.ERROR
    assert "Agent 未安装或无法启动" in events[0].text
    assert "executable" in events[0].text


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("No model selected", "配置一个 [ai.sources.<name>]"),
        ("Automatic Pi 0.82.1 setup failed: offline", "Pi 自动安装失败"),
        ("Authentication failed", "API source 请检查 api_key"),
    ],
)
@pytest.mark.asyncio
async def test_runtime_failures_have_upgrade_friendly_guidance(detail, expected):
    class FailedSession(FakeSession):
        async def stream(self, prompt: str):
            raise RuntimeError(detail)
            yield  # pragma: no cover

    loop = HarnessLoop(FailedSession)

    events = [event async for event in loop.process("hello")]

    assert events[0].type == EventType.ERROR
    assert expected in events[0].text
