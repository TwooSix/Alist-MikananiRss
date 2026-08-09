"""Notification manager for individual durable-outbox deliveries."""

from __future__ import annotations

import asyncio

from openlist_ani.logger import logger

from .bot.base import BotBase
from .formatter import NotificationFormatter
from .retry import RetryingNotificationSink


class NotificationManager:
    """Send one durable outbox item to every configured bot."""

    def __init__(
        self,
        bots: list[BotBase] | None = None,
        sink: RetryingNotificationSink | None = None,
        formatter: NotificationFormatter | None = None,
    ) -> None:
        self._bots: list[BotBase] = bots or []
        self._sink = sink or RetryingNotificationSink()
        self._formatter = formatter or NotificationFormatter()
        self._started = False

    def add_bot(self, bot: BotBase) -> None:
        self._bots.append(bot)

    async def start(self) -> None:
        if self._started:
            return

        self._started = True
        try:
            await asyncio.gather(*(bot.start() for bot in self._bots))
        except Exception:
            self._started = False
            raise

    async def stop(self) -> None:
        self._started = False
        logger.debug("Notification manager stopped")

    async def send_notification(self, message: str) -> dict[str, bool]:
        if not self._bots:
            logger.debug("No notification bots configured, skipping notification")
            return {}

        results: dict[str, bool] = {}
        for idx, bot in enumerate(self._bots):
            bot_type = type(bot).__name__
            key = bot_type if bot_type not in results else f"{bot_type}_{idx}"
            success = await self._sink.send(bot, message)
            results[key] = success
            if success:
                logger.debug(f"Notification sent via {bot_type}")
            else:
                logger.warning(
                    f"Failed to send notification via {bot_type} after retries"
                )

        return results

    async def send_download_complete_notification(
        self, anime_name: str, title: str
    ) -> dict[str, bool]:
        message = self._formatter.download_complete_message(anime_name, title)
        return await self.send_notification(message)
