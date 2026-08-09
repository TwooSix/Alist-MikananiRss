"""Hard guard shared by mutating standard Skill scripts."""

from __future__ import annotations


def confirmation_error(confirmed: object) -> str | None:
    if confirmed is True:
        return None
    return (
        "Confirmation required: show the exact write operation to the user, "
        "wait for a later explicit confirmation message, then run this script "
        "again with confirmed=true."
    )


__all__ = ["confirmation_error"]
