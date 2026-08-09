"""Provision the pinned standalone Pi runtime without requiring Node.js.

The official Pi releases contain self-contained archives for every platform
supported by OpenList-Ani.  Source and wheel installations resolve an existing
Pi first, then install the pinned archive into Assistant's persistent data
directory when needed.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

PI_VERSION = "0.82.1"
PI_RELEASE_BASE_URL = (
    "https://github.com/earendil-works/pi/releases/download/v{version}"
)
GIT_BASH_VERSION = "2.55.0.3"
GIT_BASH_ASSET = f"PortableGit-{GIT_BASH_VERSION}-64-bit.7z.exe"
GIT_BASH_URL = (
    "https://github.com/git-for-windows/git/releases/download/"
    f"v2.55.0.windows.3/{GIT_BASH_ASSET}"
)
GIT_BASH_SHA256 = "ab00566336b5472120f9a52d34f2e79c5406535792acb0548001ffd0bd090e5d"
_DOWNLOAD_TIMEOUT_SECONDS = 120
_LOCK_TIMEOUT_SECONDS = 180
_STALE_LOCK_SECONDS = 600
_USER_AGENT = f"OpenList-Ani Pi runtime installer/{PI_VERSION}"


class PiRuntimeError(RuntimeError):
    """Raised when a usable Pi executable cannot be resolved or installed."""


def ensure_pi_runtime(
    *,
    configured_executable: str = "",
    config_path: Path | None = None,
) -> str:
    """Return a Pi executable, installing the pinned standalone build if absent.

    A configured executable is authoritative and is never replaced.  An
    existing ``pi`` on PATH is also reused so native login and package-manager
    installations continue to work across upgrades.
    """

    if configured_executable:
        resolved = _resolve_existing_executable(configured_executable)
        if resolved is None:
            raise PiRuntimeError(
                f"Configured Pi executable '{configured_executable}' was not found. "
                "Fix [ai.sources.<name>].executable or remove it to enable "
                "automatic Pi setup."
            )
        return str(resolved)

    environment_override = os.environ.get("OPENLIST_ANI_PI_EXECUTABLE", "").strip()
    if environment_override:
        resolved = _resolve_existing_executable(environment_override)
        if resolved is None:
            raise PiRuntimeError(
                "OPENLIST_ANI_PI_EXECUTABLE points to a missing executable: "
                f"'{environment_override}'."
            )
        return str(resolved)

    existing = shutil.which("pi")
    if existing and _pi_is_usable(Path(existing)):
        return str(Path(existing).resolve())

    runtime_root = _runtime_root(config_path)
    executable = _managed_executable(runtime_root)
    if executable.is_file() and _pi_is_usable(executable):
        return str(executable)

    try:
        runtime_root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PiRuntimeError(
            f"Cannot create the Pi runtime directory '{runtime_root.parent}': "
            f"{error}. Install Pi manually and put it on PATH, or configure "
            "[ai.sources.<name>].executable."
        ) from error

    lock_path = runtime_root.parent / ".install.lock"
    with _installation_lock(
        lock_path,
        executable,
        readiness_probe=_pi_is_usable,
    ):
        if executable.is_file() and _pi_is_usable(executable):
            return str(executable)
        _install_release(runtime_root)

    if not executable.is_file() or not _pi_is_usable(executable):
        raise PiRuntimeError("Pi installation completed without a usable executable.")
    return str(executable)


def managed_pi_executable(config_path: Path | None = None) -> Path:
    """Return the expected path of OpenList-Ani's managed Pi executable."""

    return _managed_executable(_runtime_root(config_path))


def ensure_pi_shell(*, config_path: Path | None = None) -> str:
    """Return a Bash executable usable by Pi, provisioning PortableGit on Windows."""

    if sys.platform != "win32":
        return ""

    existing = _find_existing_bash()
    if existing is not None:
        return str(existing)

    runtime_root = _git_bash_runtime_root(config_path)
    executable = _managed_git_bash(runtime_root)
    if executable.is_file() and _bash_is_usable(executable):
        return str(executable)

    try:
        runtime_root.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PiRuntimeError(
            f"Cannot create the managed Git Bash directory "
            f"'{runtime_root.parent}': {error}. Install Git for Windows or add "
            "bash.exe to PATH."
        ) from error

    lock_path = runtime_root.parent / ".install.lock"
    with _installation_lock(
        lock_path,
        executable,
        component="Git Bash",
        readiness_probe=_bash_is_usable,
    ):
        if executable.is_file() and _bash_is_usable(executable):
            return str(executable)
        _install_git_bash(runtime_root)

    if not executable.is_file() or not _bash_is_usable(executable):
        raise PiRuntimeError(
            "Git Bash installation completed without a usable bash.exe."
        )
    return str(executable)


def managed_pi_shell(config_path: Path | None = None) -> Path:
    """Return the expected managed Git Bash executable path."""

    return _managed_git_bash(_git_bash_runtime_root(config_path))


def _resolve_existing_executable(value: str) -> Path | None:
    expanded = Path(value).expanduser()
    if expanded.is_file():
        return expanded.resolve()
    located = shutil.which(value)
    return Path(located).resolve() if located else None


def _runtime_root(config_path: Path | None) -> Path:
    if config_path is None:
        selected = Path(os.environ.get("CONFIG_PATH", "config.toml"))
    else:
        selected = Path(config_path)
    return (
        selected.expanduser().resolve().parent
        / "data"
        / "assistant"
        / "runtime"
        / "pi"
        / PI_VERSION
    )


def _git_bash_runtime_root(config_path: Path | None) -> Path:
    if config_path is None:
        selected = Path(os.environ.get("CONFIG_PATH", "config.toml"))
    else:
        selected = Path(config_path)
    return (
        selected.expanduser().resolve().parent
        / "data"
        / "assistant"
        / "runtime"
        / "git-bash"
        / GIT_BASH_VERSION
    )


def _managed_executable(runtime_root: Path) -> Path:
    filename = "pi.exe" if sys.platform == "win32" else "pi"
    return runtime_root / filename


def _managed_git_bash(runtime_root: Path) -> Path:
    return runtime_root / "bin" / "bash.exe"


def _find_existing_bash() -> Path | None:
    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable, "").strip()
        if root:
            candidates.append(Path(root) / "Git" / "bin" / "bash.exe")
    located = shutil.which("bash.exe") or shutil.which("bash")
    if located:
        candidates.append(Path(located))
    for candidate in candidates:
        if candidate.is_file() and _bash_is_usable(candidate):
            return candidate.resolve()
    return None


def _release_asset() -> str:
    systems = {
        "win32": "windows",
        "linux": "linux",
        "darwin": "darwin",
    }
    system = systems.get(sys.platform)
    if system is None:
        raise PiRuntimeError(
            f"Automatic Pi setup does not support platform '{sys.platform}'. "
            "Install Pi manually and configure its executable."
        )

    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        architecture = "x64"
    elif machine in {"aarch64", "arm64"}:
        architecture = "arm64"
    else:
        raise PiRuntimeError(
            f"Automatic Pi setup does not support architecture '{machine}'. "
            "Install Pi manually and configure its executable."
        )
    suffix = "zip" if system == "windows" else "tar.gz"
    return f"pi-{system}-{architecture}.{suffix}"


def _install_release(runtime_root: Path) -> None:
    asset = _release_asset()
    base_url = PI_RELEASE_BASE_URL.format(version=PI_VERSION)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".pi-install-", dir=runtime_root.parent
        ) as temporary_name:
            temporary = Path(temporary_name)
            checksums_path = temporary / "SHA256SUMS"
            archive_path = temporary / asset
            _download(f"{base_url}/SHA256SUMS", checksums_path)
            _download(f"{base_url}/{asset}", archive_path)
            expected = _expected_checksum(checksums_path, asset)
            actual = _sha256(archive_path)
            if actual != expected:
                raise PiRuntimeError(
                    f"Pi archive checksum mismatch for {asset}; expected "
                    f"{expected}, got {actual}. The downloaded file was discarded."
                )

            extracted = temporary / "extracted"
            extracted.mkdir()
            _extract_archive(archive_path, extracted)
            release_root = _locate_release_root(extracted, asset=asset)
            executable = _managed_executable(release_root)
            executable.chmod(
                executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            if not _pi_is_usable(executable):
                raise PiRuntimeError(
                    f"Downloaded Pi {PI_VERSION} could not pass its version probe. "
                    "The archive was not activated."
                )
            _activate_runtime(release_root, runtime_root, temporary)
    except PiRuntimeError:
        raise
    except (
        OSError,
        urllib.error.URLError,
        zipfile.BadZipFile,
        tarfile.TarError,
    ) as error:
        raise PiRuntimeError(
            f"Automatic Pi {PI_VERSION} setup failed: {error}. Check network and "
            "write access, or install Pi manually and configure executable."
        ) from error


def _install_git_bash(runtime_root: Path) -> None:
    try:
        with tempfile.TemporaryDirectory(
            prefix=".git-bash-install-", dir=runtime_root.parent
        ) as temporary_name:
            temporary = Path(temporary_name)
            archive_path = temporary / GIT_BASH_ASSET
            _download(GIT_BASH_URL, archive_path)
            actual = _sha256(archive_path)
            if actual != GIT_BASH_SHA256:
                raise PiRuntimeError(
                    f"Git Bash archive checksum mismatch; expected "
                    f"{GIT_BASH_SHA256}, got {actual}. The downloaded file was "
                    "discarded."
                )

            extracted = temporary / "extracted"
            extracted.mkdir()
            completed = subprocess.run(
                [str(archive_path), "-y", f"-o{extracted}"],
                capture_output=True,
                timeout=_DOWNLOAD_TIMEOUT_SECONDS,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).decode(
                    "utf-8", errors="replace"
                )
                raise PiRuntimeError(
                    "PortableGit extraction failed with code "
                    f"{completed.returncode}: {detail.strip()[-500:]}"
                )
            executable = _managed_git_bash(extracted)
            if not executable.is_file() or not _bash_is_usable(executable):
                raise PiRuntimeError(
                    f"Official PortableGit archive '{GIT_BASH_ASSET}' does not "
                    "contain a usable bin/bash.exe."
                )
            try:
                os.replace(extracted, runtime_root)
            except OSError as error:
                if not _managed_git_bash(runtime_root).is_file():
                    raise PiRuntimeError(
                        f"Could not activate Git Bash at '{runtime_root}': {error}"
                    ) from error
    except PiRuntimeError:
        raise
    except (OSError, urllib.error.URLError, subprocess.SubprocessError) as error:
        raise PiRuntimeError(
            f"Automatic Git Bash {GIT_BASH_VERSION} setup failed: {error}. "
            "Check network and write access, or install Git for Windows."
        ) from error


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with (
        urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output, length=1024 * 1024)


def _expected_checksum(path: Path, asset: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset:
            checksum = parts[0].lower()
            if len(checksum) == 64 and all(c in "0123456789abcdef" for c in checksum):
                return checksum
    raise PiRuntimeError(f"Official SHA256SUMS does not contain '{asset}'.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pi_is_usable(executable: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _bash_is_usable(executable: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _extract_archive(archive: Path, destination: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                _validate_member_path(destination, member.filename)
            package.extractall(destination)
        return

    with tarfile.open(archive, mode="r:gz") as package:
        members = package.getmembers()
        for member in members:
            _validate_member_path(destination, member.name)
            if member.issym() or member.islnk():
                link_parent = PurePosixPath(member.name).parent
                _validate_member_path(
                    destination, str(link_parent / PurePosixPath(member.linkname))
                )
        package.extractall(destination, members=members)


def _locate_release_root(extracted: Path, *, asset: str) -> Path:
    """Locate the directory whose direct child is the Pi executable.

    Official Windows archives currently place the executable at the archive
    root, while Linux archives use a single top-level ``pi/`` directory. Keep
    the accepted layouts narrow so an unexpected or ambiguous archive cannot
    silently activate the wrong file.
    """

    executable_name = _managed_executable(extracted).name
    candidates: list[Path] = []
    if (extracted / executable_name).is_file():
        candidates.append(extracted)
    candidates.extend(
        child
        for child in extracted.iterdir()
        if child.is_dir() and (child / executable_name).is_file()
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PiRuntimeError(
            f"Official Pi archive '{asset}' does not contain the expected "
            f"executable '{executable_name}' at its root or inside a single "
            "top-level directory."
        )
    raise PiRuntimeError(
        f"Official Pi archive '{asset}' contains multiple possible "
        f"'{executable_name}' runtime roots; refusing ambiguous installation."
    )


def _activate_runtime(source: Path, target: Path, temporary: Path) -> None:
    """Atomically activate a verified runtime and restore a stale target on error."""

    previous = temporary / "previous-runtime"
    moved_previous = False
    try:
        if target.exists() or target.is_symlink():
            os.replace(target, previous)
            moved_previous = True
        os.replace(source, target)
    except OSError as error:
        if moved_previous and not target.exists():
            try:
                os.replace(previous, target)
            except OSError:
                pass
        raise PiRuntimeError(
            f"Could not activate the downloaded Pi runtime at '{target}': {error}"
        ) from error


def _validate_member_path(destination: Path, member_name: str) -> None:
    normalized = PurePosixPath(member_name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise PiRuntimeError(f"Pi archive contains an unsafe path: '{member_name}'.")
    target = (destination / Path(*normalized.parts)).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as error:
        raise PiRuntimeError(
            f"Pi archive contains a path outside the runtime: '{member_name}'."
        ) from error


@contextmanager
def _installation_lock(
    lock_path: Path,
    executable: Path,
    *,
    component: str = "Pi",
    readiness_probe: Callable[[Path], bool] | None = None,
):
    def is_ready() -> bool:
        return executable.is_file() and (
            readiness_probe is None or readiness_probe(executable)
        )

    started = time.monotonic()
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if is_ready():
                yield
                return
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > _STALE_LOCK_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() - started >= _LOCK_TIMEOUT_SECONDS:
                raise PiRuntimeError(
                    f"Timed out waiting for another process to install {component} at "
                    f"'{executable.parent}'."
                )
            time.sleep(0.2)
            continue
        except OSError as error:
            raise PiRuntimeError(
                f"Cannot create {component} installation lock '{lock_path}': {error}."
            ) from error
        else:
            try:
                os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            finally:
                os.close(descriptor)
            break
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


__all__ = [
    "GIT_BASH_VERSION",
    "PI_VERSION",
    "PiRuntimeError",
    "ensure_pi_runtime",
    "ensure_pi_shell",
    "managed_pi_executable",
    "managed_pi_shell",
]
