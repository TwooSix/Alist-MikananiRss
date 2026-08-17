from __future__ import annotations

import os

import pytest

from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    CONFIRMATION_STATE_ENV,
    ConfirmationTurnState,
)
from openlist_ani.assistant.contracts import EventType, LoopEvent
from openlist_ani.assistant.harness.runtime import (
    _harness_environment,
    _pi_turn_events,
)


def test_harness_environment_disables_child_file_logging(monkeypatch, tmp_path):
    config_path = (tmp_path / "config.toml").resolve()
    monkeypatch.setenv("OPENLIST_ANI_FILE_LOGGING", "1")

    environment = _harness_environment(config_path)

    assert environment["CONFIG_PATH"] == str(config_path)
    assert environment["OPENLIST_ANI_FILE_LOGGING"] == "0"
    assert os.environ["OPENLIST_ANI_FILE_LOGGING"] == "1"


def test_harness_environment_exposes_only_its_session_confirmation_state(
    tmp_path, monkeypatch
):
    config_path = (tmp_path / "config.toml").resolve()
    monkeypatch.delenv(CONFIRMATION_STATE_ENV, raising=False)
    confirmation = ConfirmationTurnState(
        tmp_path / "oani-test-session" / "confirmation-state.json"
    )

    environment = _harness_environment(config_path, confirmation)

    assert environment[CONFIRMATION_STATE_ENV] == str(confirmation.path)
    assert CONFIRMATION_STATE_ENV not in os.environ


def test_pi_waits_for_agent_settled_before_finishing_a_turn():
    latest_parts: list[str] = []

    events, accepted, done = _pi_turn_events(
        {
            "type": "agent_end",
            "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}
            ],
            "willRetry": True,
        },
        accepted=True,
        latest_parts=latest_parts,
        tool_runs={},
    )

    assert events == []
    assert accepted is True
    assert done is False
    assert latest_parts == ["ok"]

    events, accepted, done = _pi_turn_events(
        {"type": "agent_settled"},
        accepted=accepted,
        latest_parts=latest_parts,
        tool_runs={},
    )

    assert events == [LoopEvent(EventType.DONE, "ok")]
    assert accepted is True
    assert done is True


def test_pi_reports_an_empty_response_only_after_agent_settles():
    latest_parts: list[str] = []

    events, accepted, done = _pi_turn_events(
        {"type": "agent_end", "messages": [], "willRetry": True},
        accepted=True,
        latest_parts=latest_parts,
        tool_runs={},
    )

    assert events == []
    assert accepted is True
    assert done is False

    with pytest.raises(RuntimeError, match="empty response after the agent settled"):
        _pi_turn_events(
            {"type": "agent_settled"},
            accepted=accepted,
            latest_parts=latest_parts,
            tool_runs={},
        )
