from __future__ import annotations

from types import SimpleNamespace

import pytest

from openlist_ani.assistant.contracts import EventType, LoopEvent
from openlist_ani.assistant.harness import loop as loop_module
from openlist_ani.assistant.harness.loop import HarnessLoop
from openlist_ani.assistant.harness.runtime import HarnessSession


class FakeSession(HarnessSession):
    async def stream(self, prompt: str):
        yield LoopEvent(EventType.THINKING, "thinking")
        yield LoopEvent(EventType.DONE, "hello " + prompt)

    async def reset(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def cancel(self) -> None:
        pass


@pytest.mark.asyncio
async def test_harness_streams_the_agent_result_to_the_frontend():
    events = [event async for event in HarnessLoop(FakeSession).process("world")]

    assert events[-1] == LoopEvent(EventType.DONE, "hello world")


@pytest.mark.asyncio
async def test_missing_agent_is_reported_with_actionable_error():
    class MissingAgentSession(FakeSession):
        async def stream(self, prompt: str):
            raise RuntimeError("Agent executable 'pi' could not be started")
            yield  # pragma: no cover

    events = [
        event async for event in HarnessLoop(MissingAgentSession).process("hello")
    ]

    assert events[0].type == EventType.ERROR
    assert "Agent 未安装或无法启动" in events[0].text


@pytest.mark.asyncio
async def test_harness_failure_is_written_to_the_error_log(monkeypatch):
    class FailedSession(FakeSession):
        async def stream(self, prompt: str):
            raise RuntimeError("Pi rejected the prompt: already processing")
            yield  # pragma: no cover

    logged: list[str] = []
    monkeypatch.setattr(
        loop_module,
        "logger",
        SimpleNamespace(error=lambda message: logged.append(message)),
    )

    events = [event async for event in HarnessLoop(FailedSession).process("hello")]

    assert events[0].type == EventType.ERROR
    assert logged == [
        "Assistant harness turn failed (RuntimeError): "
        "Pi rejected the prompt: already processing"
    ]


@pytest.mark.asyncio
async def test_common_runtime_failures_include_recovery_guidance():
    cases = [
        ("No model selected", "配置一个 [ai.sources.<name>]"),
        ("Automatic Pi setup failed: offline", "Pi 自动安装失败"),
        ("Authentication failed", "API source 请检查 api_key"),
    ]

    for detail, expected in cases:

        class FailedSession(FakeSession):
            async def stream(self, prompt: str):
                raise RuntimeError(detail)
                yield  # pragma: no cover

        events = [event async for event in HarnessLoop(FailedSession).process("hello")]
        assert events[0].type == EventType.ERROR
        assert expected in events[0].text
