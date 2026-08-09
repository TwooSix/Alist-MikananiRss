"""Stable data paths for standard Skill scripts."""

from __future__ import annotations

from pathlib import Path

from openlist_ani.adapters.configuration import config


def assistant_data_dir() -> Path:
    """Return persistent Assistant data beside the active config file."""
    return Path(config.config_path).resolve().parent / "data" / "assistant"


__all__ = ["assistant_data_dir"]
