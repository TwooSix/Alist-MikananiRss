"""Persist a user-confirmed anime taste profile."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    confirmation_error,
)
from openlist_ani.assistant.builtin_skills.support.data_paths import assistant_data_dir


async def run(profile: str = "", confirmed: bool = False, **kwargs) -> str:
    if error := confirmation_error(confirmed):
        return error
    if not profile.strip():
        return "Error: 'profile' must contain the profile Markdown."

    directory = assistant_data_dir() / "memory"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "anime_taste.md"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".anime_taste.", suffix=".tmp", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(profile.strip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return "Anime taste profile saved."


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
