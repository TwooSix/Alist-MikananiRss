from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version

from openlist_ani.assistant.builtin_skills import (
    PLUGIN_ROOT,
    SKILLS_ROOT,
)


def test_builtin_skills_are_packaged_as_native_agent_plugins() -> None:
    assert (PLUGIN_ROOT / ".claude-plugin/plugin.json").is_file()
    assert (SKILLS_ROOT / "oani/SKILL.md").is_file()


def test_native_plugin_version_tracks_python_package() -> None:
    expected = version("openlist-ani").replace(".dev", "-dev.")
    for manifest in (PLUGIN_ROOT / ".claude-plugin/plugin.json",):
        assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == expected


def test_builtin_skill_script_is_directly_executable() -> None:
    script = SKILLS_ROOT / "anime-recommend/scripts/score_candidates.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--json", json.dumps({"subjects": ""})],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip()


def test_invalid_skill_script_json_uses_argument_exit_code() -> None:
    script = SKILLS_ROOT / "oani/scripts/list_rss.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--json", "not-json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Invalid arguments" in completed.stderr
