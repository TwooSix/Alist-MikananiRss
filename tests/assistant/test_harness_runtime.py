from __future__ import annotations

import os

from openlist_ani.assistant.harness.runtime import _harness_environment


def test_harness_environment_disables_child_file_logging(monkeypatch, tmp_path):
    config_path = (tmp_path / "config.toml").resolve()
    monkeypatch.setenv("OPENLIST_ANI_FILE_LOGGING", "1")

    environment = _harness_environment(config_path)

    assert environment["CONFIG_PATH"] == str(config_path)
    assert environment["OPENLIST_ANI_FILE_LOGGING"] == "0"
    assert os.environ["OPENLIST_ANI_FILE_LOGGING"] == "1"
