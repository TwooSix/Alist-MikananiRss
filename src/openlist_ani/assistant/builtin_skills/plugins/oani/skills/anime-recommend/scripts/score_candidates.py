"""Entry point for scoring calendar candidates."""

from __future__ import annotations

from openlist_ani.assistant.builtin_skills.support.anime_recommend_scoring import run

__all__ = ["run"]


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
