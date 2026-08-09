"""Filesystem locations for the packaged OAni Agent Skills plugin."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = PACKAGE_ROOT / "plugins" / "oani"
SKILLS_ROOT = PLUGIN_ROOT / "skills"

__all__ = ["PACKAGE_ROOT", "PLUGIN_ROOT", "SKILLS_ROOT"]
