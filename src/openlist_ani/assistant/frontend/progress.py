"""User-facing rendering for agent progress events."""

from __future__ import annotations

import re

from openlist_ani.assistant.contracts import EventType, LoopEvent

_MAX_NARRATION_CHARS = 180


def narration_preview(text: str) -> str:
    """Return a compact preview of the agent's public narration."""

    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return ""
    if len(collapsed) > _MAX_NARRATION_CHARS:
        return "…" + collapsed[-(_MAX_NARRATION_CHARS - 1) :]
    return collapsed


def progress_line(event: LoopEvent) -> str:
    """Render a concrete harness event without replacing it with a generic label."""

    text = event.text.strip() or event.type.value
    if event.type == EventType.SKILL_SELECTED:
        return f"🧩 {text}"
    if event.type == EventType.SCRIPT_STARTED:
        return f"🔧 {text}"
    if event.type == EventType.SCRIPT_FINISHED:
        icon = "✅" if event.data.get("success", True) else "❌"
        return f"{icon} {text}"
    if event.type == EventType.RETRYING:
        return f"🔄 {text}"
    if event.type == EventType.CONFIRMATION_REQUIRED:
        return f"⚠️ {text}"
    return f"⏳ {text}"


__all__ = ["narration_preview", "progress_line"]
