from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src/openlist_ani/assistant/builtin_skills/plugins/oani/skills"


@pytest.mark.parametrize(
    ("script", "payload"),
    [
        (
            "oani/scripts/create_download.py",
            {"download_url": "magnet:?xt=urn:btih:test", "title": "test"},
        ),
        ("oani/scripts/add_rss.py", {"url": "https://example.test/feed.xml"}),
    ],
)
def test_write_skill_scripts_refuse_unconfirmed_execution(script, payload):
    completed = subprocess.run(
        [sys.executable, str(SKILLS / script), "--json", json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("Confirmation required:")


def test_confirmed_profile_write_uses_persistent_config_relative_data_dir(tmp_path):
    config_path = tmp_path / "config.toml"
    environment = os.environ.copy()
    environment["CONFIG_PATH"] = str(config_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILLS / "anime-recommend/scripts/save_profile.py"),
            "--json",
            json.dumps({"profile": "# Taste\n- mecha", "confirmed": True}),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "Anime taste profile saved."
    assert (tmp_path / "data/assistant/memory/anime_taste.md").read_text(
        encoding="utf-8"
    ) == "# Taste\n- mecha\n"
