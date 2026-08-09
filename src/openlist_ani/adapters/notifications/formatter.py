"""Notification message formatting and safe-size batching."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from openlist_ani.application.ports import NotificationBatch


class NotificationFormatter:
    _HEADER = "你订阅的番剧更新啦："

    def batch_messages(
        self,
        items: list[Any],
        message_limit: int,
    ) -> list[NotificationBatch]:
        limit = max(64, message_limit)
        batches: list[NotificationBatch] = []
        current: list[Any] = []
        for item in items:
            candidate = [*current, item]
            message = self._render(candidate)
            if current and len(message) > limit:
                batches.append(
                    NotificationBatch(
                        self._fit(self._render(current), limit), tuple(current)
                    )
                )
                current = [item]
            else:
                current = candidate
        if current:
            batches.append(
                NotificationBatch(
                    self._fit(self._render(current), limit), tuple(current)
                )
            )
        return batches

    def batch_message(self, queue: dict[str, list[str]]) -> tuple[str, int]:
        items = [
            _DisplayItem(anime_name=anime_name, title=title)
            for anime_name, titles in queue.items()
            for title in titles
        ]
        return self._render(items), len(items)

    def download_complete_message(self, anime_name: str, title: str) -> str:
        return f"你订阅的番剧[{anime_name}] 更新啦：\n{title}\n"

    def _render(self, items: list[Any]) -> str:
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in items:
            grouped[str(item.anime_name)].append(str(item.title))
        parts = [self._HEADER]
        for anime_name, titles in grouped.items():
            parts.append(f"\n[{anime_name}]:")
            parts.extend(f"  - {title}" for title in titles)
        return "\n".join(parts)

    @staticmethod
    def _fit(message: str, limit: int) -> str:
        if len(message) <= limit:
            return message
        return f"{message[: max(0, limit - 1)]}…"


class _DisplayItem:
    def __init__(self, *, anime_name: str, title: str) -> None:
        self.anime_name = anime_name
        self.title = title
