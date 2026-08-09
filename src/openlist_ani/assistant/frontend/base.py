"""
Frontend abstract base class.

Defines the interface that all frontends (Telegram, CLI) must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from openlist_ani.assistant.contracts import AssistantLoop, EventType


class Frontend(ABC):
    """Abstract frontend for the assistant."""

    def __init__(self, loop: AssistantLoop) -> None:
        self._loop = loop

    @abstractmethod
    async def run(self) -> None:
        """Start the frontend event loop."""
        ...

    @abstractmethod
    async def send_response(self, text: str) -> None:
        """Send a response to the user.

        Args:
            text: The response text.
        """
        ...

    async def handle_message(self, user_text: str) -> None:
        """Process a user message through the harness bridge.

        Consumes LoopEvent objects and forwards text responses.

        Args:
            user_text: The user's input.
        """
        async for event in self._loop.process(user_text):
            if event.type == EventType.DONE:
                await self.send_response(event.text)
