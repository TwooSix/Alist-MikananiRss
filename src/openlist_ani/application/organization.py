"""Backend-neutral planning and durable execution for downloaded resources.

The application layer owns all naming and recovery decisions.  Concrete storage
adapters only expose primitive file-system operations; this keeps a future local
backend from having to reimplement OpenList-specific workflow code.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from openlist_ani.application.ports import (
    CheckpointCallback,
    DownloadManifest,
    OrganizationRequest,
    OrganizationResult,
)
from openlist_ani.domain import DownloadJob

MAX_CONFLICT_SUFFIX = 99


class OrganizationError(RuntimeError):
    """A storage state cannot be reconciled safely."""


class OrganizationCleanupPending(OrganizationError):
    """A durable cleanup must be retried without consuming the job retry cap."""


class FilenameConflictError(OrganizationError):
    """No bounded conflict-free filename could be found."""


def next_available_name(
    filename: str,
    existing_names: Iterable[str],
    *,
    max_suffix: int = MAX_CONFLICT_SUFFIX,
) -> str:
    """Return ``filename`` or a deterministic ``(n)`` variant.

    This function is intentionally storage agnostic and is shared by all
    organizer drivers.
    """

    existing = set(existing_names)
    if filename not in existing:
        return filename
    stem, extension = os.path.splitext(filename)
    for index in range(1, max_suffix + 1):
        candidate = f"{stem} ({index}){extension}"
        if candidate not in existing:
            return candidate
    raise FilenameConflictError(
        f"Cannot resolve filename conflict: '{filename}' "
        f"(tried up to ({max_suffix}))"
    )


def normalize_relative_path(path: str) -> str:
    """Normalize and validate a backend-neutral relative manifest path."""

    raw = str(path or "").replace("\\", "/")
    if raw.startswith("/") or (len(raw) >= 3 and raw[0].isalpha() and raw[1:3] == ":/"):
        raise OrganizationError(f"Unsafe relative source path: {path!r}")
    normalized = raw.strip("/")
    normalized = posixpath.normpath(normalized)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise OrganizationError(f"Unsafe relative source path: {path!r}")
    return normalized


@dataclass(frozen=True)
class StorageEntry:
    name: str
    is_directory: bool = False
    size: int = 0


class StorageOperations(Protocol):
    """Primitive operations required by the durable organizer."""

    @property
    def backend_name(self) -> str: ...

    def join(self, root: str, *parts: str) -> str: ...

    async def list_directory(self, path: str) -> tuple[StorageEntry, ...]: ...

    async def ensure_directory(self, base_path: str, target_path: str) -> None: ...

    async def rename(self, full_path: str, new_name: str) -> None: ...

    async def move(
        self,
        source_directory: str,
        target_directory: str,
        filenames: tuple[str, ...],
    ) -> None: ...

    async def remove_files(
        self,
        directory: str,
        filenames: tuple[str, ...],
    ) -> None: ...

    async def remove_staging_tree(
        self,
        path: str,
        *,
        job_id: str,
        base_path: str,
    ) -> None: ...


@dataclass(frozen=True)
class PlannedFile:
    kind: str
    source_relative_path: str
    target_filename: str
    expected_size: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_relative_path": self.source_relative_path,
            "target_filename": self.target_filename,
            "expected_size": self.expected_size,
            # Ownership is established only after source/target state and the
            # target fingerprint have been verified following a mutation.
            "target_owned": False,
            "state": "pending",
        }


@dataclass(frozen=True)
class OrganizationPlan:
    item_key: str
    target_directory_path: str
    files: tuple[PlannedFile, ...]

    def as_dict(self) -> dict:
        return {
            "item_key": self.item_key,
            "target_directory_path": self.target_directory_path,
            "files": [item.as_dict() for item in self.files],
            "state": "pending",
            "attempts": 0,
        }


class OrganizationPlanner:
    """Pure planner for video/subtitle names within one destination directory."""

    def plan(
        self,
        request: OrganizationRequest,
        occupied_names: Iterable[str] = (),
        source_names_by_directory: dict[str, set[str]] | None = None,
        source_sizes: dict[str, int] | None = None,
    ) -> OrganizationPlan:
        occupied = set(occupied_names)
        source_names_by_directory = source_names_by_directory or {}
        source_sizes = source_sizes or {}
        video_source = normalize_relative_path(request.video_relative_path)
        video_target = next_available_name(
            request.target_filename,
            occupied | _source_sibling_names(video_source, source_names_by_directory),
        )
        occupied.add(video_target)
        files = [
            PlannedFile(
                "video",
                video_source,
                video_target,
                max(-1, int(source_sizes.get(video_source, 0))),
            )
        ]

        video_stem = os.path.splitext(video_target)[0]
        for sidecar in request.sidecars:
            source = normalize_relative_path(sidecar.relative_path)
            extension = os.path.splitext(source)[1]
            desired = f"{video_stem}{sidecar.suffix}{extension}"
            target = next_available_name(
                desired,
                occupied | _source_sibling_names(source, source_names_by_directory),
            )
            occupied.add(target)
            files.append(
                PlannedFile(
                    "subtitle",
                    source,
                    target,
                    max(-1, int(source_sizes.get(source, 0))),
                )
            )

        return OrganizationPlan(
            item_key=request.item_key,
            target_directory_path=request.target_directory_path,
            files=tuple(files),
        )


class DurableOrganizationExecutor:
    """Execute a complete organization plan with crash-safe reconciliation."""

    _CHECKPOINT_VERSION = 2
    _MAX_ITEM_ATTEMPTS = 3

    def __init__(
        self,
        storage: StorageOperations,
        *,
        planner: OrganizationPlanner | None = None,
    ) -> None:
        self._storage = storage
        self._planner = planner or OrganizationPlanner()

    async def organize(
        self,
        job: DownloadJob,
        manifest: DownloadManifest,
        requests: tuple[OrganizationRequest, ...],
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> tuple[OrganizationResult, ...]:
        checkpoint = await self._load_or_create_checkpoint(
            job, manifest, requests, checkpoint_callback
        )
        plans = checkpoint["plans"]
        retryable_errors: list[Exception] = []

        for plan in plans:
            if plan.get("state") in {"completed", "failed"}:
                continue
            if plan.get("state") == "cleanup_pending":
                try:
                    await self._cleanup_failed_plan(manifest, plan)
                except Exception as error:
                    plan["error"] = f"Failed-item cleanup: {error}"
                    retryable_errors.append(OrganizationCleanupPending(plan["error"]))
                    await self._save(checkpoint, checkpoint_callback)
                else:
                    plan["state"] = "failed"
                    await self._save(checkpoint, checkpoint_callback)
                continue
            try:
                await self._execute_plan(
                    job,
                    manifest,
                    plan,
                    checkpoint,
                    checkpoint_callback,
                )
            except Exception as error:
                plan["attempts"] = int(plan.get("attempts", 0)) + 1
                plan["error"] = str(error)
                if plan["attempts"] >= self._MAX_ITEM_ATTEMPTS:
                    # Persist the rollback intent before deleting anything from
                    # the media library.  A crash then resumes cleanup instead
                    # of retrying organization or losing ownership evidence.
                    plan["state"] = "cleanup_pending"
                    await self._save(checkpoint, checkpoint_callback)
                    try:
                        await self._cleanup_failed_plan(manifest, plan)
                    except Exception as cleanup_error:
                        plan["error"] = f"Failed-item cleanup: {cleanup_error}"
                        retryable_errors.append(
                            OrganizationCleanupPending(plan["error"])
                        )
                    else:
                        plan["state"] = "failed"
                else:
                    plan["state"] = "pending"
                    retryable_errors.append(error)
                await self._save(checkpoint, checkpoint_callback)
            else:
                plan["state"] = "completed"
                plan.pop("error", None)
                await self._save(checkpoint, checkpoint_callback)

        if retryable_errors:
            # Do not clean staging while any item can still be retried.
            first_error = retryable_errors[0]
            if isinstance(first_error, OrganizationCleanupPending):
                raise first_error
            raise OrganizationError(str(first_error)) from first_error

        if manifest.cleanup_root and checkpoint.get("cleanup_state") != "completed":
            try:
                await self._storage.remove_staging_tree(
                    manifest.cleanup_root,
                    job_id=job.id,
                    base_path=str(job.artifact.get("base_path") or "/"),
                )
            except Exception as error:
                checkpoint["cleanup_error"] = str(error)
                await self._save(checkpoint, checkpoint_callback)
                raise OrganizationCleanupPending(
                    f"Staging cleanup is still pending: {error}"
                ) from error
            checkpoint["cleanup_state"] = "completed"
            checkpoint.pop("cleanup_error", None)
            await self._save(checkpoint, checkpoint_callback)

        return tuple(self._result_from_plan(plan) for plan in plans)

    async def _load_or_create_checkpoint(
        self,
        job: DownloadJob,
        manifest: DownloadManifest,
        requests: tuple[OrganizationRequest, ...],
        checkpoint_callback: CheckpointCallback | None,
    ) -> dict:
        base_path = str(job.artifact.get("base_path") or "/")
        self._validate_manifest_requests(manifest, requests, base_path)
        saved = job.artifact.get("organization_checkpoint")
        if not saved:
            # Older organizer checkpoints used this key.  Only accept v2-shaped
            # values directly; single-asset v1 plans are upgraded below.
            candidate = job.artifact.get("organize_plan")
            if isinstance(candidate, dict) and candidate.get("version") == 2:
                saved = candidate
            elif (
                manifest.legacy_materialized
                and len(requests) == 1
                and isinstance(candidate, dict)
                and isinstance(candidate.get("files"), list)
            ):
                legacy_files = [
                    {
                        "kind": str(item.get("kind") or "subtitle"),
                        "source_relative_path": str(item["source"]),
                        "target_filename": str(item["target"]),
                        "target_owned": True,
                        "state": "pending",
                    }
                    for item in candidate["files"]
                    if item.get("source") and item.get("target")
                ]
                if legacy_files:
                    saved = {
                        "version": self._CHECKPOINT_VERSION,
                        "root_path": manifest.root_path,
                        "plans": [
                            {
                                "item_key": requests[0].item_key,
                                "target_directory_path": requests[
                                    0
                                ].target_directory_path,
                                "files": legacy_files,
                                "state": "pending",
                                "attempts": 0,
                            }
                        ],
                        "cleanup_state": "not_required",
                    }
        if isinstance(saved, dict) and saved.get("version") == self._CHECKPOINT_VERSION:
            if saved.get("root_path") != manifest.root_path:
                raise OrganizationError(
                    "Organization checkpoint root does not match manifest"
                )
            self._validate_saved_checkpoint(saved, requests, manifest)
            return _copy_checkpoint(saved)

        keys = [request.item_key for request in requests]
        if len(keys) != len(set(keys)):
            raise OrganizationError(
                "Organization request item_key values must be unique"
            )

        source_names_by_directory = _manifest_names_by_directory(manifest)
        source_sizes = _manifest_source_sizes(manifest)
        reserved_by_directory: dict[str, set[str]] = {}
        plans: list[dict] = []
        for request in requests:
            target = request.target_directory_path
            if target not in reserved_by_directory:
                if not (
                    manifest.legacy_materialized
                    and target.rstrip("/") == manifest.root_path.rstrip("/")
                ):
                    await self._storage.ensure_directory(base_path, target)
                entries = await self._storage.list_directory(target)
                reserved_by_directory[target] = {entry.name for entry in entries}
            occupied = set(reserved_by_directory[target])
            if manifest.legacy_materialized and target.rstrip(
                "/"
            ) == manifest.root_path.rstrip("/"):
                owned_source_names = {
                    posixpath.basename(normalize_relative_path(path))
                    for path in (
                        request.video_relative_path,
                        *(sidecar.relative_path for sidecar in request.sidecars),
                    )
                    if not posixpath.dirname(normalize_relative_path(path))
                }
                occupied.difference_update(owned_source_names)
                source_name = posixpath.basename(
                    normalize_relative_path(request.video_relative_path)
                )
                if source_name not in occupied and request.target_filename in occupied:
                    # Legacy recovery: rename may have succeeded before its
                    # plan/checkpoint was saved.
                    occupied.remove(request.target_filename)
            plan = self._planner.plan(
                request,
                occupied,
                source_names_by_directory=source_names_by_directory,
                source_sizes=source_sizes,
            )
            plans.append(plan.as_dict())
            reserved_by_directory[target].update(
                item.target_filename for item in plan.files
            )

        checkpoint = {
            "version": self._CHECKPOINT_VERSION,
            "root_path": manifest.root_path,
            "plans": plans,
            "cleanup_state": "pending" if manifest.cleanup_root else "not_required",
        }
        # The entire plan must be durable before the first remote mutation.
        await self._save(checkpoint, checkpoint_callback)
        return checkpoint

    @staticmethod
    def _validate_manifest_requests(
        manifest: DownloadManifest,
        requests: tuple[OrganizationRequest, ...],
        base_path: str,
    ) -> None:
        if manifest.cleanup_root and (
            manifest.cleanup_root.rstrip("/") != manifest.root_path.rstrip("/")
        ):
            raise OrganizationError("Manifest cleanup root must match its staging root")
        inventory = {
            normalize_relative_path(item.relative_path) for item in manifest.files
        }
        requested: set[str] = set()
        for request in requests:
            _validate_target_directory(base_path, request.target_directory_path)
            paths = [
                request.video_relative_path,
                *(sidecar.relative_path for sidecar in request.sidecars),
            ]
            for raw_path in paths:
                path = normalize_relative_path(raw_path)
                if path not in inventory:
                    raise OrganizationError(
                        f"Organization source is absent from manifest: {path}"
                    )
                if path in requested:
                    raise OrganizationError(
                        f"Downloaded file is assigned more than once: {path}"
                    )
                requested.add(path)

    @staticmethod
    def _validate_saved_checkpoint(
        checkpoint: dict,
        requests: tuple[OrganizationRequest, ...],
        manifest: DownloadManifest,
    ) -> None:
        plans = checkpoint.get("plans")
        if not isinstance(plans, list):
            raise OrganizationError("Organization checkpoint plans are invalid")
        request_by_key = {request.item_key: request for request in requests}
        plan_keys = [str(plan.get("item_key") or "") for plan in plans]
        if len(plan_keys) != len(set(plan_keys)) or set(plan_keys) != set(
            request_by_key
        ):
            raise OrganizationError(
                "Organization checkpoint does not match requested item keys"
            )
        source_sizes = _manifest_source_sizes(manifest)
        for plan in plans:
            request = request_by_key[str(plan["item_key"])]
            if str(plan.get("target_directory_path") or "") != str(
                request.target_directory_path
            ):
                raise OrganizationError(
                    "Organization checkpoint target directory changed"
                )
            expected_sources = {
                normalize_relative_path(request.video_relative_path),
                *(
                    normalize_relative_path(sidecar.relative_path)
                    for sidecar in request.sidecars
                ),
            }
            actual_sources = {
                normalize_relative_path(str(item.get("source_relative_path") or ""))
                for item in plan.get("files", [])
            }
            if actual_sources != expected_sources:
                raise OrganizationError(
                    "Organization checkpoint source inventory changed"
                )
            for item in plan.get("files", []):
                source = normalize_relative_path(
                    str(item.get("source_relative_path") or "")
                )
                expected_size = source_sizes[source]
                saved_size = item.get("expected_size")
                if saved_size is not None and int(saved_size) != expected_size:
                    raise OrganizationError(
                        "Organization checkpoint source size changed"
                    )
                item["expected_size"] = expected_size
                item.setdefault("target_owned", False)

    async def _execute_plan(
        self,
        job: DownloadJob,
        manifest: DownloadManifest,
        plan: dict,
        checkpoint: dict,
        checkpoint_callback: CheckpointCallback | None,
    ) -> None:
        target_directory = str(plan["target_directory_path"])
        base_path = str(job.artifact.get("base_path") or "/")
        if not (
            manifest.legacy_materialized
            and target_directory.rstrip("/") == manifest.root_path.rstrip("/")
        ):
            await self._storage.ensure_directory(base_path, target_directory)

        final_paths: list[str] = []
        for file_plan in plan.get("files", []):
            if file_plan.get("state") == "completed" and file_plan.get("final_path"):
                verified_path = await self._execute_file(
                    manifest.root_path,
                    target_directory,
                    file_plan,
                )
                if verified_path != str(file_plan["final_path"]):
                    raise OrganizationError(
                        "Completed organization path changed during recovery"
                    )
                final_paths.append(verified_path)
                continue
            final_path = await self._execute_file(
                manifest.root_path,
                target_directory,
                file_plan,
            )
            file_plan["state"] = "completed"
            file_plan["final_path"] = final_path
            file_plan["target_owned"] = not manifest.legacy_materialized
            final_paths.append(final_path)
            plan["final_path"] = final_paths[0]
            plan["sidecar_paths"] = final_paths[1:]
            # Persist each materialized file immediately.  If the remote
            # mutation succeeds but this save is interrupted, the next pass
            # reconciles source/target state and writes the same fingerprint.
            await self._save(checkpoint, checkpoint_callback)
        if not final_paths:
            raise OrganizationError(
                f"Organization item {plan['item_key']} has no files"
            )
        plan["final_path"] = final_paths[0]
        plan["sidecar_paths"] = final_paths[1:]

    async def _cleanup_failed_plan(
        self,
        manifest: DownloadManifest,
        plan: dict,
    ) -> None:
        """Remove only target files proven to have been materialized by a plan."""

        # Legacy v1 assets were already placed in the media directory before
        # the shared executor received them.  Their ownership cannot be proven
        # strongly enough for rollback, so never delete them here.
        if manifest.legacy_materialized:
            plan.pop("final_path", None)
            plan.pop("sidecar_paths", None)
            return

        target_directory = str(plan["target_directory_path"])
        for file_plan in plan.get("files", []):
            if file_plan.get("state") == "removed":
                continue
            if file_plan.get("state") != "completed" or not file_plan.get(
                "target_owned"
            ):
                # A pending file is still in staging (or ambiguous) and will be
                # removed with the staging tree, never from the media library.
                continue

            relative = normalize_relative_path(str(file_plan["source_relative_path"]))
            source_parent_rel, source_name = posixpath.split(relative)
            source_directory = (
                self._storage.join(manifest.root_path, source_parent_rel)
                if source_parent_rel
                else manifest.root_path
            )
            target_name = str(file_plan["target_filename"])
            source_entries = await self._storage.list_directory(source_directory)
            target_entries = (
                source_entries
                if source_directory.rstrip("/") == target_directory.rstrip("/")
                else await self._storage.list_directory(target_directory)
            )
            source_names = {entry.name for entry in source_entries}
            target_by_name = {entry.name: entry for entry in target_entries}

            same_file = (
                source_directory.rstrip("/") == target_directory.rstrip("/")
                and source_name == target_name
            )
            if not same_file and source_name in source_names:
                raise OrganizationError(
                    f"Refusing to delete ambiguous failed target: source still exists "
                    f"for {source_name}"
                )
            if target_name in target_by_name:
                target_entry = target_by_name[target_name]
                expected_size = int(file_plan.get("verified_size", -1))
                if expected_size < 0 or target_entry.size != expected_size:
                    raise OrganizationError(
                        "Refusing to delete failed target because its fingerprint "
                        f"changed: {target_name}"
                    )
                await self._storage.remove_files(target_directory, (target_name,))
            # If both source and target are absent, a prior cleanup succeeded
            # before its checkpoint and is safe to confirm idempotently.
            file_plan["state"] = "removed"
            file_plan.pop("final_path", None)
        plan.pop("final_path", None)
        plan.pop("sidecar_paths", None)

    async def _execute_file(
        self,
        root_path: str,
        target_directory: str,
        file_plan: dict,
    ) -> str:
        relative = normalize_relative_path(str(file_plan["source_relative_path"]))
        source_parent_rel, source_name = posixpath.split(relative)
        source_directory = (
            self._storage.join(root_path, source_parent_rel)
            if source_parent_rel
            else root_path
        )
        target_name = str(file_plan["target_filename"])
        if not target_name or "/" in target_name or "\\" in target_name:
            raise OrganizationError(f"Unsafe target filename: {target_name!r}")

        source_entries = await self._storage.list_directory(source_directory)
        target_entries = (
            source_entries
            if source_directory.rstrip("/") == target_directory.rstrip("/")
            else await self._storage.list_directory(target_directory)
        )
        source_names = {entry.name for entry in source_entries}
        target_names = {entry.name for entry in target_entries}
        if source_name in source_names:
            self._verified_size(source_entries, source_name, file_plan, "source")

        if source_directory.rstrip("/") == target_directory.rstrip("/"):
            await self._reconcile_same_directory(
                source_directory, source_name, target_name, source_names
            )
            refreshed = await self._storage.list_directory(target_directory)
            self._verified_size(refreshed, target_name, file_plan, "target")
            return self._storage.join(target_directory, target_name)

        if source_name not in source_names and target_name not in source_names:
            if target_name in target_names:
                self._verified_size(target_entries, target_name, file_plan, "target")
                return self._storage.join(target_directory, target_name)
            raise OrganizationError(
                f"Organization source is missing: {source_directory}/{source_name}"
            )
        if target_name in target_names:
            raise OrganizationError(
                f"Organization source and target both exist: {source_name} -> {target_name}"
            )

        current_name = source_name
        if source_name != target_name:
            if source_name in source_names:
                if target_name in source_names:
                    raise OrganizationError(
                        f"Cannot rename source because target exists in staging: {target_name}"
                    )
                await self._storage.rename(
                    self._storage.join(source_directory, source_name), target_name
                )
            current_name = target_name

        # Reconcile a rename/move that succeeded before its checkpoint.
        source_entries = await self._storage.list_directory(source_directory)
        target_entries = await self._storage.list_directory(target_directory)
        source_names = {entry.name for entry in source_entries}
        target_names = {entry.name for entry in target_entries}
        if current_name not in source_names:
            if current_name in target_names:
                self._verified_size(target_entries, current_name, file_plan, "target")
                return self._storage.join(target_directory, current_name)
            raise OrganizationError(f"Renamed source disappeared: {current_name}")
        if current_name in target_names:
            raise OrganizationError(
                f"Ambiguous move state for {current_name}: present in source and target"
            )

        await self._storage.move(source_directory, target_directory, (current_name,))
        source_entries = await self._storage.list_directory(source_directory)
        target_entries = await self._storage.list_directory(target_directory)
        if current_name in {
            entry.name for entry in source_entries
        } or current_name not in {entry.name for entry in target_entries}:
            raise OrganizationError(f"Move verification failed for {current_name}")
        self._verified_size(target_entries, current_name, file_plan, "target")
        return self._storage.join(target_directory, current_name)

    @staticmethod
    def _verified_size(
        entries: tuple[StorageEntry, ...],
        name: str,
        file_plan: dict,
        location: str,
    ) -> int:
        entry = next(
            (candidate for candidate in entries if candidate.name == name), None
        )
        if entry is None or entry.is_directory:
            raise OrganizationError(f"Organization {location} file is missing: {name}")
        expected = max(-1, int(file_plan.get("expected_size", 0)))
        if expected >= 0 and entry.size != expected:
            raise OrganizationError(
                f"Organization {location} size changed for {name}: "
                f"expected {expected}, got {entry.size}"
            )
        file_plan["verified_size"] = entry.size
        return entry.size

    async def _reconcile_same_directory(
        self,
        directory: str,
        source_name: str,
        target_name: str,
        names: set[str],
    ) -> None:
        if source_name == target_name and source_name in names:
            return
        if source_name not in names and target_name in names:
            return
        if source_name not in names:
            raise OrganizationError(
                f"Rename source is missing: {directory}/{source_name}"
            )
        if target_name in names:
            raise OrganizationError(
                f"Rename source and target both exist: {source_name} -> {target_name}"
            )
        await self._storage.rename(
            self._storage.join(directory, source_name), target_name
        )
        refreshed = await self._storage.list_directory(directory)
        refreshed_names = {entry.name for entry in refreshed}
        if source_name in refreshed_names or target_name not in refreshed_names:
            raise OrganizationError(
                f"Rename verification failed: {source_name} -> {target_name}"
            )

    @staticmethod
    async def _save(
        checkpoint: dict,
        callback: CheckpointCallback | None,
    ) -> None:
        if callback is not None:
            await callback(_copy_checkpoint(checkpoint))

    @staticmethod
    def _result_from_plan(plan: dict) -> OrganizationResult:
        return OrganizationResult(
            item_key=str(plan["item_key"]),
            state=str(plan.get("state") or "failed"),
            final_path=plan.get("final_path"),
            sidecar_paths=tuple(plan.get("sidecar_paths") or ()),
            error=plan.get("error"),
        )


def _copy_checkpoint(value: dict) -> dict:
    """Copy the JSON-shaped checkpoint without sharing mutable nested values."""

    return {
        **value,
        "plans": [
            {
                **plan,
                "files": [dict(item) for item in plan.get("files", [])],
                "sidecar_paths": list(plan.get("sidecar_paths", [])),
            }
            for plan in value.get("plans", [])
        ],
    }


def _validate_target_directory(base_path: str, target_path: str) -> None:
    """Require every metadata-derived target to be a strict child of base."""

    raw_base = str(base_path or "/").replace("\\", "/")
    raw_target = str(target_path or "").replace("\\", "/")
    target_parts = [part for part in raw_target.split("/") if part]
    if not raw_target or any(part in {".", ".."} for part in target_parts):
        raise OrganizationError(f"Unsafe organization target: {target_path!r}")

    normalized_base = posixpath.normpath(raw_base)
    normalized_target = posixpath.normpath(raw_target)
    prefix = "/" if normalized_base == "/" else normalized_base.rstrip("/") + "/"
    if normalized_target == normalized_base or not normalized_target.startswith(prefix):
        raise OrganizationError(
            f"Organization target escapes base path: {target_path!r}"
        )


def _manifest_names_by_directory(manifest: DownloadManifest) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for item in manifest.files:
        relative = normalize_relative_path(item.relative_path)
        parent, name = posixpath.split(relative)
        output.setdefault(parent, set()).add(name)
    return output


def _manifest_source_sizes(manifest: DownloadManifest) -> dict[str, int]:
    return {
        normalize_relative_path(item.relative_path): (
            -1
            if manifest.legacy_materialized and int(item.size) == 0
            else max(0, int(item.size))
        )
        for item in manifest.files
    }


def _source_sibling_names(
    relative_path: str,
    names_by_directory: dict[str, set[str]],
) -> set[str]:
    parent, own_name = posixpath.split(normalize_relative_path(relative_path))
    return set(names_by_directory.get(parent, set())) - {own_name}
