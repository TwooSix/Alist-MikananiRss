from __future__ import annotations

import os

from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    CONFIRMATION_STATE_ENV,
    ConfirmationTurnState,
)
from openlist_ani.assistant.harness.runtime import _harness_environment


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
    confirmation = ConfirmationTurnState(tmp_path / "confirmation-state.json")

    environment = _harness_environment(config_path, confirmation)

    assert environment[CONFIRMATION_STATE_ENV] == str(confirmation.path)
    assert CONFIRMATION_STATE_ENV not in os.environ
