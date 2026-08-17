"""Standalone database migration entry point."""

from __future__ import annotations

from openlist_ani.adapters.persistence import LegacyMigrationRunner


def main() -> None:
    LegacyMigrationRunner().run()


if __name__ == "__main__":
    main()
