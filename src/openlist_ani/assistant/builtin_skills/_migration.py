"""One-time cleanup for built-in Skills copied by older OAni releases."""

from __future__ import annotations

import hashlib
import shlex
import shutil
from pathlib import Path

from openlist_ani.logger import logger

LEGACY_MANIFEST_FILENAME = ".openlist-ani-builtin-skills.json"
LEGACY_UPDATES_DIR_NAME = ".openlist-ani-updates"
LEGACY_ROOT_SKILLS_VERSION = "v1.0.0.dev260426"

# Known byte-for-byte copies shipped by older releases. Unknown directories
# are treated as user content and are never removed.
LEGACY_COPIED_BUILTIN_SKILL_HASHES: dict[str, dict[str, str]] = {
    "anime-download": {
        "e8ef39958a3b9e1b43c15789050ee9b468f8863e4680ec2ad7b23435435f1340": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
    },
    "anime-recommend": {
        "dc3fc0cf2859761d1647ede91c2ed5b20502d4c0022aec283961735edb821e32": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
        "146ccf7d4734d0db2b182d04d78ed46c82d8d768fc2e003a54657e30fec19b58": (
            "pre-release:e803f60"
        ),
    },
    "anime-search": {
        "7bff37877f7f4aa2e053ddd1a8f96e03777397e71a0aa37503ed249b2568f856": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
    },
    "bangumi": {
        "5a656ac42b42ec46e3f270b76d72ced31b98e4b73e91a966197fb2a1e69e6b25": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
    },
    "mikan": {
        "9fbd7555f9bc24b9ffcc931a19fefd6ec2f53255ae9de5e0e92298508a17b948": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
    },
    "oani": {
        "c87475d80b3ab28ae4d10004e8ea1c019832fe73f74243257874b9bac2435607": (
            LEGACY_ROOT_SKILLS_VERSION
        ),
        "6a9f901f3e6769ddb5e5d53172796652379ee4448ff2b07a48f21c8a9ac05a6a": (
            "pre-release:e803f60"
        ),
    },
}


def _is_generated_path(path: Path) -> bool:
    return any(
        part == "__pycache__" or part.endswith((".pyc", ".pyo")) for part in path.parts
    )


def _hash_path(path: Path) -> str:
    hasher = hashlib.sha256()
    if path.is_file():
        hasher.update(b"file\0")
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        return hasher.hexdigest()
    if not path.is_dir():
        raise FileNotFoundError(path)

    hasher.update(b"dir\0")
    for child in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        relative = child.relative_to(path)
        if _is_generated_path(relative) or not child.is_file():
            continue
        hasher.update(relative.as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(child.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def migrate_legacy_copied_builtin_skills(
    user_skills_dir: Path,
    builtin_skills_dir: Path,
) -> None:
    """Delete only recognized legacy copies, preserving real user overrides."""
    user_root = user_skills_dir.expanduser()
    if not user_root.is_dir():
        return

    for builtin_skill in sorted(builtin_skills_dir.iterdir()):
        if not builtin_skill.is_dir():
            continue
        local_skill = user_root / builtin_skill.name
        if not local_skill.is_dir():
            continue

        local_hash = _hash_path(local_skill)
        if local_hash == _hash_path(builtin_skill):
            _remove_path(local_skill)
            logger.info(
                f"Removed legacy copied built-in assistant skill: {local_skill}"
            )
            continue

        legacy_version = LEGACY_COPIED_BUILTIN_SKILL_HASHES.get(
            builtin_skill.name, {}
        ).get(local_hash)
        if legacy_version:
            _remove_path(local_skill)
            logger.info(
                "Removed legacy copied built-in assistant skill "
                f"{local_skill} from {legacy_version}"
            )
            continue

        local_arg = shlex.quote(str(local_skill))
        builtin_arg = shlex.quote(str(builtin_skill))
        logger.warning(
            f"{local_skill} has the same name as bundled skill "
            f"'{builtin_skill.name}' but contains user changes, so it was preserved. "
            f"Compare with: diff -ru {local_arg} {builtin_arg}."
        )

    _remove_path(user_root / LEGACY_MANIFEST_FILENAME)
    _remove_path(user_root / LEGACY_UPDATES_DIR_NAME)


__all__ = ["migrate_legacy_copied_builtin_skills"]
