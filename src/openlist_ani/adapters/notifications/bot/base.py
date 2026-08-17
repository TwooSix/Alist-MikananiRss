import asyncio
from abc import ABC, abstractmethod


class BotBase(ABC):
    message_limit = 3500

    async def start(self) -> None:
        """Run optional bot startup work."""
        await asyncio.sleep(0)

    @abstractmethod
    async def send_message(self, message: str) -> bool: ...

    def notification_identity(self) -> str:
        """Return stable target identity material; callers must hash it."""
        return type(self).__name__
