"""Versioned, comment-preserving migration for ``config.toml``.

Migration is deliberately kept outside the Pydantic models.  The on-disk
document is backed up before it is changed, transformed in memory, validated,
then atomically replaced.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import tomlkit
from pydantic import ValidationError
from tomlkit.container import Container, OutOfOrderTableProxy
from tomlkit.items import Item, Table
from tomlkit.toml_document import TOMLDocument

from .models import CURRENT_CONFIG_VERSION, UserConfig


class ConfigMigrationError(RuntimeError):
    """Raised when a persisted migration cannot be completed safely."""


@dataclass(frozen=True)
class MigrationResult:
    config: UserConfig
    migrated: bool = False
    persisted: bool = True
    backup_path: Path | None = None


Migration = Callable[[TOMLDocument], None]
TomlTable = Table | OutOfOrderTableProxy


def migrate_config(path: Path) -> MigrationResult:
    """Load and, when necessary, migrate ``path`` to the current schema."""
    with _migration_lock(path):
        original = path.read_bytes()
        document = _parse_document(original, path)
        version = _document_version(document)
        if version == CURRENT_CONFIG_VERSION:
            return MigrationResult(config=_validate_document(document, path))
        if version > CURRENT_CONFIG_VERSION:
            raise ConfigMigrationError(
                f"Configuration {path} uses schema version {version}, but this "
                f"application supports up to version {CURRENT_CONFIG_VERSION}."
            )

        backup_path: Path | None = None
        try:
            backup_path = _create_backup(path, original, version)
        except OSError:
            # Read-only mounts still get runtime compatibility, but are never
            # overwritten without a verified backup.
            migrated_document = _apply_migrations(document, version)
            config = _validate_document(migrated_document, path)
            return MigrationResult(
                config=config,
                migrated=True,
                persisted=False,
                backup_path=None,
            )

        try:
            migrated_document = _apply_migrations(document, version)
            config = _validate_document(migrated_document, path)
            encoded = tomlkit.dumps(migrated_document).encode("utf-8")
            # Validate the exact bytes which will replace the original file.
            reparsed = _parse_document(encoded, path)
            config = _validate_document(reparsed, path)
        except Exception as error:
            raise ConfigMigrationError(
                f"Failed to migrate {path}; the original file was not replaced. "
                f"Backup: {backup_path}. Reason: {error}"
            ) from error

        try:
            _atomic_replace(path, encoded)
        except OSError:
            # Windows read-only files and single-file container mounts can allow
            # the backup but reject atomic replacement. The validated in-memory
            # document is still safe to use, and the original remains untouched.
            return MigrationResult(
                config=config,
                migrated=True,
                persisted=False,
                backup_path=backup_path,
            )

        return MigrationResult(
            config=config,
            migrated=True,
            persisted=True,
            backup_path=backup_path,
        )


def _parse_document(raw: bytes, path: Path) -> TOMLDocument:
    try:
        return tomlkit.parse(raw.decode("utf-8"))
    except Exception as error:
        raise ConfigMigrationError(
            f"Cannot parse configuration {path}: {error}"
        ) from error


def _document_version(document: TOMLDocument) -> int:
    value = document.get("config_version", 1)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigMigrationError("config_version must be an integer.")
    return value


def _validate_document(document: TOMLDocument, path: Path) -> UserConfig:
    try:
        raw = tomllib.loads(tomlkit.dumps(document))
        return UserConfig.model_validate(raw)
    except Exception as error:
        raise ConfigMigrationError(
            f"Migrated configuration {path} does not validate: "
            f"{_safe_validation_message(error)}"
        ) from error


def _safe_validation_message(error: Exception) -> str:
    """Format validation errors without echoing tokens or API keys."""
    if not isinstance(error, ValidationError):
        return type(error).__name__
    messages = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "config"
        messages.append(f"{location}: {item.get('msg', 'invalid value')}")
    return "; ".join(messages)


def _apply_migrations(document: TOMLDocument, version: int) -> TOMLDocument:
    migrations: dict[int, Migration] = {1: _migrate_v1_to_v2}
    current = version
    while current < CURRENT_CONFIG_VERSION:
        try:
            migration = migrations[current]
        except KeyError as error:
            raise ConfigMigrationError(
                f"No configuration migration is available from version {current}."
            ) from error
        migration(document)
        current += 1
    return document


def _migrate_v1_to_v2(document: TOMLDocument) -> None:
    legacy_llm = _table(document.get("llm"))
    source_name = _migrate_llm(document, legacy_llm)
    _migrate_metadata(document, legacy_llm, source_name)
    _migrate_assistant(document, source_name)
    _migrate_downloader(document)

    for legacy_key in (
        "llm",
        "metadata_parser",
        "metadata_validator",
        "file_renamer",
        "openlist",
    ):
        document.pop(legacy_key, None)
    document.pop("config_version", None)
    # tomlkit keeps root scalar keys before table declarations when dumping.
    document["config_version"] = CURRENT_CONFIG_VERSION


def _migrate_llm(document: TOMLDocument, legacy_llm: TomlTable | None) -> str | None:
    if legacy_llm is None:
        return None
    api_key = _string(legacy_llm.get("openai_api_key"))
    model = _string(legacy_llm.get("openai_model"))
    # An incomplete v1 example should not turn into an invalid API source.
    # With no source configured, v2 intentionally falls back to native Pi.
    if not api_key or not model:
        return None

    provider_type = _string(legacy_llm.get("provider_type")) or "openai"
    provider = (
        "anthropic-messages"
        if provider_type.strip().lower() == "anthropic"
        else "openai-compatible"
    )
    candidate: dict[str, object] = {
        "type": "api",
        "provider": provider,
        "api_key": api_key,
        "model": model,
    }
    base_url = _string(legacy_llm.get("openai_base_url"))
    if base_url:
        candidate["base_url"] = base_url

    ai = _ensure_table(document, "ai")
    sources = _ensure_table(ai, "sources")
    name = "legacy-llm"
    suffix = 2
    while name in sources:
        existing = _table(sources.get(name))
        if existing is not None and _table_values(existing) == candidate:
            return name
        name = f"legacy-llm-{suffix}"
        suffix += 1
    source = tomlkit.table()
    for key, value in candidate.items():
        source[key] = value
    sources[name] = source
    return name


def _migrate_metadata(
    document: TOMLDocument,
    legacy_llm: TomlTable | None,
    source_name: str | None,
) -> None:
    metadata = _ensure_table(document, "metadata")
    raw_pipeline = metadata.get("pipeline")
    if raw_pipeline is None:
        raw_pipeline = metadata.pop("providers", None)

    if raw_pipeline is not None:
        pipeline = _normalise_pipeline(list(raw_pipeline))
    else:
        pipeline = _legacy_metadata_pipeline(document, source_name)
    metadata["pipeline"] = pipeline

    if "ai" in pipeline and source_name and "ai_source" not in metadata:
        metadata["ai_source"] = source_name

    _migrate_tmdb_settings(metadata, legacy_llm)


def _legacy_metadata_pipeline(
    document: TOMLDocument, source_name: str | None
) -> list[str]:
    parser = _table(document.get("metadata_parser"))
    validator = _table(document.get("metadata_validator"))
    explicit_parser = _string(parser.get("provider")) if parser else ""
    if explicit_parser:
        first = "ai" if explicit_parser.lower() == "llm" else explicit_parser.lower()
    else:
        first = "ai" if source_name else "regex"
    pipeline = [first]
    validator_name = (
        _string(validator.get("provider")) if validator else "tmdb"
    ) or "tmdb"
    if validator_name.lower() != "none":
        pipeline.append(validator_name.lower())
    return _normalise_pipeline(pipeline)


def _migrate_tmdb_settings(metadata: TomlTable, legacy_llm: TomlTable | None) -> None:
    tmdb = _ensure_table(metadata, "tmdb")
    if legacy_llm is None:
        return
    key = _string(legacy_llm.get("tmdb_api_key"))
    language = _string(legacy_llm.get("tmdb_language"))
    if key and "api_key" not in tmdb:
        tmdb["api_key"] = key
    if language and "language" not in tmdb:
        tmdb["language"] = language


def _migrate_assistant(document: TOMLDocument, source_name: str | None) -> None:
    assistant = _table(document.get("assistant"))
    if assistant is None:
        return
    if (
        bool(assistant.get("enabled", False))
        and source_name
        and "backend" not in assistant
    ):
        assistant["backend"] = source_name
    for legacy_key in (
        "max_context_tokens",
        "session_compact_threshold",
        "data_dir",
        "auto_dream",
    ):
        assistant.pop(legacy_key, None)


def _migrate_downloader(document: TOMLDocument) -> None:
    downloader = _ensure_table(document, "downloader")
    downloader.pop("provider", None)
    legacy_openlist = _table(document.get("openlist"))
    if legacy_openlist is None:
        _ensure_table(downloader, "openlist")
        return

    for key in ("download_path", "rename_format"):
        if key in legacy_openlist and key not in downloader:
            downloader[key] = legacy_openlist[key]
    if "torrent_to_magnet" in legacy_openlist:
        rss = _ensure_table(document, "rss")
        if "torrent_to_magnet" not in rss:
            rss["torrent_to_magnet"] = legacy_openlist["torrent_to_magnet"]
    openlist = _ensure_table(downloader, "openlist")
    for key in ("url", "token", "offline_download_tool"):
        if key in legacy_openlist and key not in openlist:
            openlist[key] = legacy_openlist[key]


def _normalise_pipeline(values: list[object]) -> list[str]:
    normalised: list[str] = []
    for value in values:
        item = str(value).strip().lower()
        if item == "llm":
            item = "ai"
        if item and item not in normalised:
            normalised.append(item)
    return normalised


def _ensure_table(container: Container, key: str) -> TomlTable:
    existing = _table(container.get(key))
    if existing is not None:
        return existing
    created = tomlkit.table()
    container[key] = created
    return created


def _table(value: Item | object | None) -> TomlTable | None:
    return value if isinstance(value, (Table, OutOfOrderTableProxy)) else None


def _string(value: object | None) -> str:
    return value if isinstance(value, str) else ""


def _table_values(table: TomlTable) -> dict[str, object]:
    return dict(table.unwrap().items())


def _create_backup(path: Path, original: bytes, version: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    base = path.with_name(f"{path.name}.bak.v{version}.{stamp}")
    candidate = base
    suffix = 2
    while True:
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            candidate = path.with_name(f"{base.name}.{suffix}")
            suffix += 1
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            shutil.copymode(path, candidate)
    except Exception:
        with contextlib.suppress(OSError):
            candidate.unlink()
        raise
    return candidate


def _atomic_replace(path: Path, encoded: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


@contextlib.contextmanager
def _migration_lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    """Acquire a small cross-platform advisory lock beside the config file."""
    lock_path = path.with_name(f".{path.name}.migrate.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
    except OSError:
        # A read-only mount cannot be locked or migrated persistently.  The
        # caller will still perform a validated in-memory migration.
        yield
        return
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            _lock_handle(handle)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise ConfigMigrationError(
                    f"Timed out waiting for configuration migration lock: {lock_path}"
                )
            time.sleep(0.05)
    try:
        yield
    finally:
        _unlock_handle(handle)
        handle.close()


def _lock_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle) -> None:
    with contextlib.suppress(OSError):
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["ConfigMigrationError", "MigrationResult", "migrate_config"]
