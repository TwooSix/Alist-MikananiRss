from __future__ import annotations

import hashlib
import shutil
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from openlist_ani.assistant.harness import pi_runtime


def _fake_release(tmp_path: Path) -> tuple[Path, str]:
    archive = tmp_path / "official.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("pi.exe", b"standalone-pi")
        package.writestr("photon_rs_bg.wasm", b"runtime-data")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, checksum


def _fake_linux_release(tmp_path: Path) -> tuple[Path, str]:
    payload = tmp_path / "payload" / "pi"
    payload.mkdir(parents=True)
    (payload / "pi").write_bytes(b"standalone-pi")
    (payload / "CHANGELOG.md").write_text("release data", encoding="utf-8")
    archive = tmp_path / "pi-linux-x64.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(payload, arcname="pi")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, checksum


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

    executable = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))
    reused = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))

    assert executable == reused
    assert executable.read_bytes() == b"standalone-pi"
    assert (executable.parent / "photon_rs_bg.wasm").is_file()
    assert len(downloads) == 2


def test_linux_release_with_top_level_pi_directory_is_installed(tmp_path, monkeypatch):
    archive, checksum = _fake_linux_release(tmp_path)
    monkeypatch.setattr(pi_runtime.sys, "platform", "linux")
    monkeypatch.setattr(pi_runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pi_runtime, "_pi_is_usable", lambda _path: True)

    def fake_download(_url: str, destination: Path) -> None:
        if destination.name == "SHA256SUMS":
            destination.write_text(
                f"{checksum}  pi-linux-x64.tar.gz\n", encoding="utf-8"
            )
        else:
            shutil.copyfile(archive, destination)

    monkeypatch.setattr(pi_runtime, "_download", fake_download)
    config_path = tmp_path / "instance" / "config.toml"

    executable = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))

    assert executable.name == "pi"
    assert executable.read_bytes() == b"standalone-pi"
    assert (executable.parent / "CHANGELOG.md").read_text(encoding="utf-8") == (
        "release data"
    )


def test_broken_managed_runtime_is_replaced(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    executable = pi_runtime.managed_pi_executable(config_path)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"broken")
    installs = 0

    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        pi_runtime,
        "_pi_is_usable",
        lambda path: path.read_bytes() == b"working",
    )

    def fake_install(runtime_root: Path) -> None:
        nonlocal installs
        installs += 1
        executable.write_bytes(b"working")

    monkeypatch.setattr(pi_runtime, "_install_release", fake_install)

    resolved = Path(pi_runtime.ensure_pi_runtime(config_path=config_path))

    assert resolved.read_bytes() == b"working"
    assert installs == 1


def test_explicit_pi_is_authoritative_and_never_downloaded(tmp_path, monkeypatch):
    executable = tmp_path / "my-pi"
    executable.write_bytes(b"custom")

    def unexpected_install(_runtime_root):  # pragma: no cover - assertion helper
        raise AssertionError("managed Pi must not be installed")

    monkeypatch.setattr(pi_runtime, "_install_release", unexpected_install)

    resolved = pi_runtime.ensure_pi_runtime(
        configured_executable=str(executable),
        config_path=tmp_path / "config.toml",
    )

    assert Path(resolved) == executable.resolve()


def test_path_pi_is_reused_without_managed_install(tmp_path, monkeypatch):
    executable = tmp_path / "path-pi"
    executable.write_bytes(b"existing")
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(pi_runtime, "_pi_is_usable", lambda _path: True)

    def unexpected_install(_runtime_root):  # pragma: no cover - assertion helper
        raise AssertionError("managed Pi must not be installed")

    monkeypatch.setattr(pi_runtime, "_install_release", unexpected_install)

    resolved = pi_runtime.ensure_pi_runtime(config_path=tmp_path / "config.toml")

    assert Path(resolved) == executable.resolve()


def test_broken_path_pi_falls_back_to_managed_runtime(tmp_path, monkeypatch):
    broken = tmp_path / "broken-pi"
    broken.write_bytes(b"broken")
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: str(broken))
    monkeypatch.setattr(pi_runtime, "_pi_is_usable", lambda path: path != broken)

    def fake_install(runtime_root: Path) -> None:
        runtime_root.mkdir(parents=True)
        (
            runtime_root
            / pi_runtime.managed_pi_executable(tmp_path / "config.toml").name
        ).write_bytes(b"managed")

    monkeypatch.setattr(pi_runtime, "_install_release", fake_install)

    resolved = pi_runtime.ensure_pi_runtime(config_path=tmp_path / "config.toml")

    assert Path(resolved).read_bytes() == b"managed"


def test_missing_explicit_pi_reports_how_to_enable_auto_setup(tmp_path):
    with pytest.raises(pi_runtime.PiRuntimeError, match="remove it to enable"):
        pi_runtime.ensure_pi_runtime(
            configured_executable=str(tmp_path / "missing-pi"),
            config_path=tmp_path / "config.toml",
        )


def test_checksum_failure_does_not_activate_runtime(tmp_path, monkeypatch):
    archive, _checksum = _fake_release(tmp_path)
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


def test_concurrent_setup_installs_once(tmp_path, monkeypatch):
    monkeypatch.setattr(pi_runtime.shutil, "which", lambda _name: None)
    monkeypatch.setattr(pi_runtime, "_pi_is_usable", lambda _path: True)
    config_path = tmp_path / "config.toml"
    install_count = 0
    count_lock = threading.Lock()

    def fake_install(runtime_root: Path) -> None:
        nonlocal install_count
        with count_lock:
            install_count += 1
        time.sleep(0.1)
        runtime_root.mkdir(parents=True)
        (runtime_root / pi_runtime.managed_pi_executable(config_path).name).write_bytes(
            b"managed"
        )

    monkeypatch.setattr(pi_runtime, "_install_release", fake_install)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resolved = list(
            pool.map(
                lambda _: pi_runtime.ensure_pi_runtime(config_path=config_path),
                range(2),
            )
        )

    assert resolved[0] == resolved[1]
    assert install_count == 1
    assert not (Path(resolved[0]).parent.parent / ".install.lock").exists()


def test_missing_windows_bash_is_provisioned_and_reused(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    installs = 0

    monkeypatch.setattr(pi_runtime.sys, "platform", "win32")
    monkeypatch.setattr(pi_runtime, "_find_existing_bash", lambda: None)
    monkeypatch.setattr(pi_runtime, "_bash_is_usable", lambda _path: True)

    def fake_install(runtime_root: Path) -> None:
        nonlocal installs
        installs += 1
        executable = runtime_root / "bin" / "bash.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"managed-bash")

    monkeypatch.setattr(pi_runtime, "_install_git_bash", fake_install)

    first = Path(pi_runtime.ensure_pi_shell(config_path=config_path))
    second = Path(pi_runtime.ensure_pi_shell(config_path=config_path))

    assert first == second == pi_runtime.managed_pi_shell(config_path)
    assert first.read_bytes() == b"managed-bash"
    assert installs == 1


def test_existing_windows_bash_is_reused(tmp_path, monkeypatch):
    executable = tmp_path / "bash.exe"
    executable.write_bytes(b"system-bash")
    monkeypatch.setattr(pi_runtime.sys, "platform", "win32")
    monkeypatch.setattr(pi_runtime, "_find_existing_bash", lambda: executable.resolve())

    resolved = pi_runtime.ensure_pi_shell(config_path=tmp_path / "config.toml")

    assert Path(resolved) == executable.resolve()


def test_git_bash_checksum_failure_does_not_activate_runtime(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        pi_runtime,
        "_download",
        lambda _url, destination: destination.write_bytes(b"not-portable-git"),
    )

    with pytest.raises(pi_runtime.PiRuntimeError, match="checksum mismatch"):
        pi_runtime._install_git_bash(runtime_root)

    assert not runtime_root.exists()


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("win32", "AMD64", "pi-windows-x64.zip"),
        ("linux", "aarch64", "pi-linux-arm64.tar.gz"),
        ("darwin", "arm64", "pi-darwin-arm64.tar.gz"),
    ],
)
def test_release_asset_matches_platform(system, machine, expected, monkeypatch):
    monkeypatch.setattr(pi_runtime.sys, "platform", system)
    monkeypatch.setattr(pi_runtime.platform, "machine", lambda: machine)

    assert pi_runtime._release_asset() == expected


def test_archive_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.exe", b"unsafe")

    with pytest.raises(pi_runtime.PiRuntimeError, match="unsafe path"):
        pi_runtime._extract_archive(archive, tmp_path / "destination")

    assert not (tmp_path / "outside.exe").exists()


def test_runtime_activation_replaces_stale_directory(tmp_path):
    temporary = tmp_path / "temporary"
    source = temporary / "extracted" / "pi"
    target = tmp_path / "runtime" / "pi" / pi_runtime.PI_VERSION
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (source / "new").write_text("new", encoding="utf-8")
    (target / "old").write_text("old", encoding="utf-8")

    pi_runtime._activate_runtime(source, target, temporary)

    assert (target / "new").read_text(encoding="utf-8") == "new"
    assert not (target / "old").exists()


def test_runtime_activation_restores_stale_directory_on_failure(tmp_path, monkeypatch):
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


def test_docker_preinstalled_pi_matches_managed_version():
    repository = Path(__file__).resolve().parents[2]
    dockerfile = (repository / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert f"@earendil-works/pi-coding-agent@{pi_runtime.PI_VERSION}" in dockerfile
