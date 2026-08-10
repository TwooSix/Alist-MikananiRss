"""Hard guards shared by mutating standard Skill scripts.

The download workflow additionally uses a session-local confirmation ticket.
The harness owns the turn counter and advances it only when a new user prompt
starts.  A ticket issued by preflight therefore cannot be consumed by a model
that simply passes ``confirmed=true`` later in the same agent turn.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIRMATION_STATE_ENV = "OPENLIST_ANI_CONFIRMATION_STATE"
_TICKET_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")


def confirmation_error(confirmed: object) -> str | None:
    if confirmed is True:
        return None
    return (
        "Confirmation required: show the exact write operation to the user, "
        "wait for a later explicit confirmation message, then run this script "
        "again with confirmed=true."
    )


@dataclass(frozen=True)
class ConfirmationTicketCheck:
    """Result of validating and consuming one download confirmation ticket."""

    accepted: bool
    message: str = ""


class ConfirmationTurnState:
    """Harness-owned state that identifies one frontend session and its turns."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._session_id = secrets.token_urlsafe(24)
        self.reset()

    def begin_turn(self) -> None:
        state = _read_state(self.path)
        if state.get("session_id") != self._session_id:
            state = _new_state(self._session_id)
        state["turn"] = int(state.get("turn") or 0) + 1
        _write_state(self.path, state)

    def reset(self) -> None:
        self._session_id = secrets.token_urlsafe(24)
        ticket_directory = _ticket_directory(self.path)
        if ticket_directory.is_dir():
            for ticket_file in ticket_directory.glob("*.json"):
                ticket_file.unlink(missing_ok=True)
        _write_state(self.path, _new_state(self._session_id))

    def apply_environment(self, environment: dict[str, str]) -> None:
        environment[CONFIRMATION_STATE_ENV] = str(self.path)


def issue_download_confirmation_ticket(
    *,
    download_url: str,
    title: str,
    collection_hint: bool,
    override_policy: bool,
    acknowledged_conflicts: list[str] | tuple[str, ...] = (),
    policy_review_token: str | None = None,
) -> str:
    """Issue a ticket bound to this session, turn, and exact download request."""

    path, state = _active_state()
    ticket = secrets.token_urlsafe(24)
    current_turn = int(state.get("turn") or 0)
    record = {
        "session_id": state["session_id"],
        "issued_turn": current_turn,
        "request": _request_binding(
            download_url=download_url,
            title=title,
            collection_hint=collection_hint,
            override_policy=override_policy,
            acknowledged_conflicts=acknowledged_conflicts,
            policy_review_token=policy_review_token,
        ),
    }
    # Each request gets a separate atomic file so parallel preflights for a
    # batch cannot overwrite one another's tickets.
    ticket_path = _ticket_path(path, ticket)
    assert ticket_path is not None  # token_urlsafe output matches _TICKET_RE
    _write_state(ticket_path, record)
    return ticket


def consume_download_confirmation_ticket(
    ticket: str | None,
    *,
    download_url: str,
    title: str,
    collection_hint: bool,
    override_policy: bool,
    acknowledged_conflicts: list[str] | tuple[str, ...] = (),
    policy_review_token: str | None = None,
) -> ConfirmationTicketCheck:
    """Accept only a matching ticket issued before the current user turn."""

    if not ticket:
        return ConfirmationTicketCheck(
            False,
            "Confirmation ticket required: run preflight_download.py, show the "
            "exact operation, and wait for a later explicit user confirmation.",
        )
    try:
        path, state = _active_state()
    except RuntimeError as error:
        return ConfirmationTicketCheck(False, str(error))
    ticket_path = _ticket_path(path, ticket)
    record = _read_state(ticket_path) if ticket_path is not None else {}
    if ticket_path is None or not record:
        return ConfirmationTicketCheck(
            False,
            "Confirmation ticket is missing, expired, already used, or belongs "
            "to another Assistant session. Run preflight_download.py again.",
        )
    current_turn = int(state.get("turn") or 0)
    issued_turn = int(record.get("issued_turn") or 0)
    if current_turn - issued_turn > 20:
        ticket_path.unlink(missing_ok=True)
        return ConfirmationTicketCheck(
            False,
            "Confirmation ticket expired. Run preflight_download.py again.",
        )
    if current_turn <= issued_turn:
        return ConfirmationTicketCheck(
            False,
            "Confirmation required from a later user turn. Do not create the "
            "download in the same turn that displayed the review.",
        )
    expected = _request_binding(
        download_url=download_url,
        title=title,
        collection_hint=collection_hint,
        override_policy=override_policy,
        acknowledged_conflicts=acknowledged_conflicts,
        policy_review_token=policy_review_token,
    )
    if (
        record.get("session_id") != state.get("session_id")
        or record.get("request") != expected
    ):
        return ConfirmationTicketCheck(
            False,
            "Confirmation ticket does not match this exact download request and "
            "policy review. Run preflight_download.py again.",
        )
    ticket_path.unlink(missing_ok=True)
    return ConfirmationTicketCheck(True)


def _active_state() -> tuple[Path, dict[str, Any]]:
    raw_path = os.environ.get(CONFIRMATION_STATE_ENV, "").strip()
    if not raw_path:
        raise RuntimeError(
            "Assistant confirmation context is unavailable. Run this write "
            "through an active OpenList-Ani Assistant session."
        )
    path = Path(raw_path)
    state = _read_state(path)
    if not state.get("session_id") or int(state.get("turn") or 0) <= 0:
        raise RuntimeError(
            "Assistant confirmation context is invalid. Start a new Assistant "
            "turn and run preflight_download.py again."
        )
    return path, state


def _request_binding(
    *,
    download_url: str,
    title: str,
    collection_hint: bool,
    override_policy: bool,
    acknowledged_conflicts: list[str] | tuple[str, ...],
    policy_review_token: str | None,
) -> dict[str, Any]:
    return {
        "download_url": download_url,
        "title": title,
        "collection_hint": bool(collection_hint),
        "override_policy": bool(override_policy),
        "acknowledged_conflicts": sorted(set(acknowledged_conflicts)),
        "policy_review_token": policy_review_token or None,
    }


def _new_state(session_id: str) -> dict[str, Any]:
    return {"version": 1, "session_id": session_id, "turn": 0}


def _ticket_directory(state_path: Path) -> Path:
    return state_path.with_name(f"{state_path.name}.tickets")


def _ticket_path(state_path: Path, ticket: str) -> Path | None:
    if _TICKET_RE.fullmatch(ticket) is None:
        return None
    return _ticket_directory(state_path) / f"{ticket}.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


__all__ = [
    "CONFIRMATION_STATE_ENV",
    "ConfirmationTicketCheck",
    "ConfirmationTurnState",
    "confirmation_error",
    "consume_download_confirmation_ticket",
    "issue_download_confirmation_ticket",
]
