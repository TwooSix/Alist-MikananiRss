"""Notification message formatting and safe-size batching."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
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
        grouped: dict[str, list[Any]] = defaultdict(list)
        for item in items:
            grouped[str(_field(item, "anime_name"))].append(item)
        parts = [self._HEADER]
        for anime_name, group_items in grouped.items():
            parts.append(f"\n[{anime_name}]:")
            for item in group_items:
                parts.extend(self._render_item(item))
        return "\n".join(parts)

    def _render_item(self, item: Any) -> list[str]:
        title = str(_field(item, "title"))
        summary = _summary(item)
        if not _is_collection_summary(summary):
            return [f"  - {title}"]

        success = _count(summary, "success_count")
        skipped = _count(summary, "skipped_count")
        failed = _count(summary, "failed_count")
        deleted = _count(summary, "deleted_count")
        warnings = _count(summary, "warning_count")
        lines = [
            f"  - {title}",
            (
                f"    成功 {success} 集，跳过 {skipped} 项，"
                f"失败 {failed} 项，删除 {deleted} 个文件，警告 {warnings} 项"
            ),
        ]
        episodes = _successful_episode_labels(summary)
        if episodes:
            lines.append(f"    成功集：{'、'.join(episodes)}")
        return lines

    @staticmethod
    def _fit(message: str, limit: int) -> str:
        if len(message) <= limit:
            return message
        return f"{message[: max(0, limit - 1)]}…"


class _DisplayItem:
    def __init__(self, *, anime_name: str, title: str) -> None:
        self.anime_name = anime_name
        self.title = title


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _summary(item: Any) -> dict[str, Any]:
    value = _field(item, "summary")
    return dict(value) if isinstance(value, Mapping) else {}


def _count(summary: Mapping[str, Any], key: str) -> int:
    value = summary.get(key, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _is_collection_summary(summary: Mapping[str, Any]) -> bool:
    if not summary:
        return False
    if summary.get("collection") is False or summary.get("is_collection") is False:
        return False
    if summary.get("collection") is True or summary.get("is_collection") is True:
        return True
    item_count = (
        len(summary.get("items", ()))
        if isinstance(summary.get("items"), (list, tuple))
        else 0
    )
    decided_count = sum(
        _count(summary, key)
        for key in ("success_count", "skipped_count", "failed_count")
    )
    return (
        item_count > 1
        or decided_count > 1
        or _count(summary, "warning_count") > 0
        or _count(summary, "deleted_count") > 0
        or len(_successful_episode_labels(summary)) > 1
    )


def _successful_episode_labels(summary: Mapping[str, Any]) -> list[str]:
    raw = summary.get("successful_episodes")
    candidates = list(raw) if isinstance(raw, (list, tuple)) else []
    if not candidates:
        items = summary.get("items")
        if isinstance(items, (list, tuple)):
            candidates = [
                item
                for item in items
                if isinstance(item, Mapping) and item.get("state") == "completed"
            ]

    labels: list[str] = []
    for candidate in candidates:
        label = _episode_label(candidate)
        if label and label not in labels:
            labels.append(label)
    return labels


def _episode_label(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if not isinstance(value, Mapping):
        return str(value) if value is not None else None
    for key in ("label", "display", "title"):
        if value.get(key):
            return str(value[key])
    metadata = value.get("metadata")
    values = metadata.get("values", metadata) if isinstance(metadata, Mapping) else {}
    season = value.get("season", values.get("season"))
    episode = value.get("episode", values.get("episode"))
    try:
        episode_number = int(episode)
    except (TypeError, ValueError):
        return None
    try:
        season_number = int(season)
    except (TypeError, ValueError):
        return f"E{episode_number:02d}"
    return f"S{season_number:02d}E{episode_number:02d}"
