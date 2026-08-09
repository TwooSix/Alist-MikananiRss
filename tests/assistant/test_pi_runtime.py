from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest

from openlist_ani.assistant.harness import pi_runtime


def _fake_release(tmp_path: Path) -> tuple[Path, str]:
    archive = tmp_path / "official.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("pi.exe", b"standalone-pi")
        package.writestr("photon_rs_bg.wasm", b"runtime-data")
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_missing_pi_is_downloaded_verified_and_reused(tmp_path, monkeypatch):
    archive, checksum = _fake_release(tmp_path)
    downloads: list[str] = []
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pi_runtime, "_pi_is_usable", lambda _path: True)
    monkeypatch.setattr(pi_runtime.sys, "platform", "win32")
    monkeypatch.setattr(pi_runtime, "_release_asset", lambda: "pi-windows-x64.zip")

    def fake_download(url: str, destination: Path) -> None:
        downloads.append(url)
        if destination.name == "SHA256SUMS":
            destination.write_text(
                f"{checksum}  pi-windows-x64.zip\n", encoding="utf-8"
            )
        else:
            shutil.copyfile(archive, destination)

    monkeypatch.setattr(pi_runtime, "_download", fake_download)
    config_path = tmp_path / "instance" / "config.toml"

    first = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))
    second = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))

    assert first == second
    assert first.read_bytes() == b"standalone-pi"
    assert len(downloads) == 2


def test_checksum_failure_does_not_activate_runtime(tmp_path, monkeypatch):
    archive, _ = _fake_release(tmp_path)
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pi_runtime, "_release_asset", lambda: "pi-windows-x64.zip")

    def fake_download(_url: str, destination: Path) -> None:
        if destination.name == "SHA256SUMS":
            destination.write_text(
                f"{'0' * 64}  pi-windows-x64.zip\n", encoding="utf-8"
            )
        else:
            shutil.copyfile(archive, destination)

    monkeypatch.setattr(pi_runtime, "_download", fake_download)
    config_path = tmp_path / "config.toml"

    with pytest.raises(pi_runtime.PiRuntimeError, match="checksum mismatch"):
        pi_runtime.ensure_pi_runtime(config_path=config_path)

    assert not pi_runtime.managed_pi_executable(config_path).exists()


def test_archive_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.exe", b"unsafe")

    with pytest.raises(pi_runtime.PiRuntimeError, match="unsafe path"):
        pi_runtime._extract_archive(archive, tmp_path / "destination")

    assert not (tmp_path / "outside.exe").exists()


def test_failed_runtime_upgrade_restores_previous_installation(tmp_path, monkeypatch):
    temporary = tmp_path / "temporary"
    source = temporary / "extracted" / "pi"
    target = tmp_path / "runtime" / "pi" / pi_runtime.PI_VERSION
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (source / "new").write_text("new", encoding="utf-8")
    (target / "old").write_text("old", encoding="utf-8")
    real_replace = pi_runtime.os.replace

    def fail_new_activation(current, destination):
        if Path(current) == source and Path(destination) == target:
            raise OSError("simulated activation failure")
        real_replace(current, destination)

    monkeypatch.setattr(pi_runtime.os, "replace", fail_new_activation)

    with pytest.raises(pi_runtime.PiRuntimeError, match="Could not activate"):
        pi_runtime._activate_runtime(source, target, temporary)

    assert (target / "old").read_text(encoding="utf-8") == "old"
    assert not (target / "new").exists()
