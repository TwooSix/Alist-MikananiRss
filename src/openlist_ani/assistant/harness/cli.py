"""Small local CLI for the harness-backed assistant."""

from __future__ import annotations

from openlist_ani.assistant.contracts import EventType
from openlist_ani.assistant.frontend.progress import narration_preview, progress_line


class HarnessCLIFrontend:
    def __init__(self, loop) -> None:
        self._loop = loop

    async def run(self) -> None:
        print("OpenList-Ani assistant. Type /clear, /cancel, /status or /quit.")
        while True:
            try:
                text = await _read_input("you> ")
            except (EOFError, KeyboardInterrupt):
                return
            text = text.strip()
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                return
            if text == "/clear":
                self._loop.reset()
                print("New session started.")
                continue
            if text == "/cancel":
                await self._loop.cancel()
                print("Current turn and queued requests cancelled.")
                continue
            if text == "/status":
                print(self._loop.status())
                continue
            narration_parts: list[str] = []
            async for event in self._loop.process(text):
                if event.type == EventType.TEXT_DELTA and event.text:
                    narration_parts.append(event.text)
                elif event.type == EventType.ERROR:
                    print(f"Error: {event.text}")
                elif event.type == EventType.DONE:
                    print(event.text)
                elif event.type in {
                    EventType.THINKING,
                    EventType.SKILL_SELECTED,
                    EventType.SCRIPT_STARTED,
                    EventType.SCRIPT_FINISHED,
                    EventType.RETRYING,
                    EventType.CONFIRMATION_REQUIRED,
                }:
                    narration = narration_preview("".join(narration_parts))
                    narration_parts.clear()
                    if narration:
                        print(f"[💭 {narration}]")
                    print(f"[{progress_line(event)}]")

    async def shutdown(self) -> None:
        await self._loop.shutdown()


async def _read_input(prompt: str) -> str:
    import asyncio

    return await asyncio.to_thread(input, prompt)


__all__ = ["HarnessCLIFrontend"]
