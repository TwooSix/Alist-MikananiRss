"""Tests for one-time migration of legacy copied built-in Skills."""

from __future__ import annotations

from pathlib import Path

from openlist_ani.assistant.builtin_skills import _migration as migration


def _write_skill(root: Path, name: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo skill\n---\n{body}",
        encoding="utf-8",
    )
    return skill_dir


def _read_skill(skills_dir: Path, name: str) -> str:
    return (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")


def test_deletes_current_copied_builtin_from_user_skills(
    tmp_path: Path,
) -> None:
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "skills"
    _write_skill(builtin_dir, "demo", "# bundled current\n")
    _write_skill(user_dir, "demo", "# bundled current\n")

    migration.migrate_legacy_copied_builtin_skills(user_dir, builtin_dir)

    assert not (user_dir / "demo").exists()


def test_deletes_known_legacy_copied_builtin_from_user_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "skills"
    _write_skill(builtin_dir, "demo", "# bundled current\n")
    legacy_dir = _write_skill(user_dir, "demo", "# old bundled\n")
    legacy_hash = migration._hash_path(legacy_dir)
    monkeypatch.setattr(
        migration,
        "LEGACY_COPIED_BUILTIN_SKILL_HASHES",
        {"demo": {legacy_hash: "old-release"}},
    )

    migration.migrate_legacy_copied_builtin_skills(user_dir, builtin_dir)

    assert not (user_dir / "demo").exists()


def test_preserves_unrecognized_builtin_override_and_warns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "skills"
    _write_skill(builtin_dir, "demo", "# bundled current\n")
    _write_skill(user_dir, "demo", "# user override\n")
    warnings: list[str] = []
    monkeypatch.setattr(migration.logger, "warning", warnings.append)

    migration.migrate_legacy_copied_builtin_skills(user_dir, builtin_dir)

    assert _read_skill(user_dir, "demo").endswith("# user override\n")
    assert len(warnings) == 1


def test_leaves_non_builtin_user_skill_alone(tmp_path: Path) -> None:
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "skills"
    _write_skill(builtin_dir, "demo", "# bundled current\n")
    _write_skill(user_dir, "custom", "# custom\n")

    migration.migrate_legacy_copied_builtin_skills(user_dir, builtin_dir)

    assert (user_dir / "custom").exists()
