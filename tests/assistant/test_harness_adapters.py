from __future__ import annotations

from pathlib import Path

from openlist_ani.assistant.builtin_skills import PLUGIN_ROOT, SKILLS_ROOT
from openlist_ani.assistant.harness.adapters import (
    ClaudeCodeAgentAdapter,
    CodexAgentAdapter,
    PiAgentAdapter,
    SessionSpec,
)

EXPECTED_BUILTIN_SKILLS = {
    "anime-download",
    "anime-recommend",
    "anime-search",
    "bangumi",
    "mikan",
    "oani",
}


def _session_spec(tmp_path: Path, user_skills_root: Path | None = None) -> SessionSpec:
    return SessionSpec(
        source=None,
        builtin_plugin_root=PLUGIN_ROOT,
        user_skills_root=user_skills_root,
        config_path=tmp_path / "config.toml",
    )


def test_builtin_skills_use_each_harness_native_discovery_path(tmp_path):
    spec = _session_spec(tmp_path)

    assert PiAgentAdapter().session_arguments(spec) == [
        "--skill",
        str(SKILLS_ROOT.resolve()),
    ]
    assert ClaudeCodeAgentAdapter().session_arguments(spec) == [
        "--plugin-dir",
        str(PLUGIN_ROOT.resolve()),
    ]

    CodexAgentAdapter().prepare_working_directory(spec, tmp_path)
    projection = tmp_path / ".agents" / "skills"
    links = {path.name: path for path in projection.iterdir()}

    assert set(links) == EXPECTED_BUILTIN_SKILLS
    assert all(
        path.resolve() == (SKILLS_ROOT / name).resolve() for name, path in links.items()
    )
    assert all((path / "SKILL.md").is_file() for path in links.values())


def test_codex_projection_prefers_same_named_user_skill_directory(tmp_path):
    user_root = tmp_path / "user-skills"
    user_skill = user_root / "oani"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text(
        "---\nname: oani\ndescription: User override.\n---\n",
        encoding="utf-8",
    )
    working_directory = tmp_path / "session"

    CodexAgentAdapter().prepare_working_directory(
        _session_spec(tmp_path, user_root), working_directory
    )

    projected = working_directory / ".agents" / "skills" / "oani"
    assert projected.resolve() == user_skill.resolve()
