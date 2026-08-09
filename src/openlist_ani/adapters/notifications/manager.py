"""Notification manager for durable per-target deliveries."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict

from openlist_ani.application.ports import NotificationBatch, NotificationTarget
from openlist_ani.logger import logger

from .bot.base import BotBase
from .formatter import NotificationFormatter
from .retry import RetryingNotificationSink


class NotificationManager:
    def __init__(
        self,
        bots: list[BotBase] | None = None,
        sink: RetryingNotificationSink | None = None,
        formatter: NotificationFormatter | None = None,
    ) -> None:
        self._bots: list[BotBase] = bots or []
        self._sink = sink or RetryingNotificationSink()
        self._formatter = formatter or NotificationFormatter()
        self._targets: dict[str, BotBase] = {}
        self._started = False
        self._rebuild_targets()

    def add_bot(self, bot: BotBase) -> None:
        self._bots.append(bot)
        self._rebuild_targets()

    def targets(self) -> tuple[NotificationTarget, ...]:
        return tuple(
            NotificationTarget(key=key, message_limit=bot.message_limit)
            for key, bot in self._targets.items()
        )

    def format_download_batches(
        self,
        target_key: str,
        items: list[object],
    ) -> list[NotificationBatch]:
        bot = self._target(target_key)
        return self._formatter.batch_messages(items, bot.message_limit)

    async def send_to_target(self, target_key: str, message: str) -> bool:
        bot = self._target(target_key)
        success = await self._sink.send(bot, message)
        if success:
            logger.debug(f"Notification sent via {type(bot).__name__}")
        else:
            logger.warning(
                f"Failed to send notification via {type(bot).__name__} after retries"
            )
        return success

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
        if not self._targets:
            logger.debug("No notification bots configured, skipping notification")
            return {}
        results = await asyncio.gather(
            *(self.send_to_target(key, message) for key in self._targets)
        )
        return dict(zip(self._targets, results))

    async def send_download_complete_notification(
        self, anime_name: str, title: str
    ) -> dict[str, bool]:
        message = self._formatter.download_complete_message(anime_name, title)
        return await self.send_notification(message)

    def _target(self, target_key: str) -> BotBase:
        try:
            return self._targets[target_key]
        except KeyError as error:
            raise ValueError("Unknown notification target") from error

    def _rebuild_targets(self) -> None:
        counts: dict[str, int] = defaultdict(int)
        targets: dict[str, BotBase] = {}
        for bot in self._bots:
            bot_type = type(bot).__name__.removesuffix("Bot").lower()
            identity = bot.notification_identity().encode("utf-8")
            digest = hashlib.sha256(identity).hexdigest()[:16]
            base_key = f"{bot_type}:{digest}"
            ordinal = counts[base_key]
            counts[base_key] += 1
            key = f"{base_key}:{ordinal}"
            targets[key] = bot
        self._targets = targets
