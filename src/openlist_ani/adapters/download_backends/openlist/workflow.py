"""OpenList offline-download command processor."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

from openlist_ani.domain.naming import format_anime_episode
from openlist_ani.logger import logger

from .client import OpenListClient
from .file_conflicts import OpenListFileConflictResolver
from .file_detection import OpenListFileDetector
from .models import (
    DownloadBackendError,
    OfflineDownloadTool,
    OpenListWorkflowContext,
    OpenlistTask,
    OpenlistTaskState,
)
from .task_snapshot_cache import OpenListTaskSnapshotCache

OPENLIST_TEMP_ROOT_DIRECTORY_NAME = ".oani-download-tmp"
OPENLIST_WORKFLOW_STATE_KEY = "workflow_state"


class OpenListWorkflowState(StrEnum):
    INIT = "init"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    DOWNLOAD_DONE = "download_done"
    TRANSFER_DONE = "transfer_done"
    FILE_DETECTED = "file_detected"
    FILE_RESOLVED = "file_resolved"
    MOVING = "moving"
    MOVED = "moved"
    DONE = "done"


class OpenListRemoteTaskFailed(DownloadBackendError):
    """Raised when OpenList marks a remote task as failed."""


WorkflowCheckpoint = Callable[[OpenListWorkflowContext], Awaitable[None]]


def _join_openlist_path(base_path: str, *parts: str) -> str:
    root = (base_path or "/").rstrip("/") or "/"
    suffix = "/".join(part.strip("/") for part in parts if part.strip("/"))
    if not suffix:
        return root
    if root == "/":
        return f"/{suffix}"
    return f"{root}/{suffix}"


def _temp_root_path(base_path: str) -> str:
    return _join_openlist_path(base_path, OPENLIST_TEMP_ROOT_DIRECTORY_NAME)


def _directory_creation_paths(base_path: str, target_path: str) -> list[str]:
    base = (base_path or "/").rstrip("/") or "/"
    target = (target_path or "/").rstrip("/") or "/"
    if target == base:
        return []

    prefix = "/" if base == "/" else f"{base}/"
    if not target.startswith(prefix):
        return [target]

    relative_path = target[len(prefix) :]
    parts = [part for part in relative_path.split("/") if part]
    return [
        _join_openlist_path(base, *parts[:index]) for index in range(1, len(parts) + 1)
    ]


def _workflow_state(task: OpenListWorkflowContext) -> OpenListWorkflowState:
    raw_state = task.downloader_data.get(OPENLIST_WORKFLOW_STATE_KEY)
    if raw_state:
        try:
            return OpenListWorkflowState(raw_state)
        except ValueError:
            logger.warning(f"Unknown OpenList workflow state: {raw_state}; restarting")

    if task.downloader_data.get("materialized_filename"):
        return OpenListWorkflowState.DONE
    if task.downloader_data.get("resolved_filename"):
        return OpenListWorkflowState.FILE_RESOLVED
    if task.downloader_data.get("downloaded_filename"):
        return OpenListWorkflowState.FILE_DETECTED
    if task.downloader_data.get("task_id"):
        return OpenListWorkflowState.SUBMITTED
    return OpenListWorkflowState.INIT


class OpenListDownloadWorkflow:
    """Command Processor for one OpenList offline-download lifecycle."""

    _TRANSFER_CHECK_MAX_RETRIES = 3
    _TRANSFER_CHECK_INTERVAL_SECONDS = 5

    def __init__(
        self,
        client: OpenListClient,
        offline_download_tool: OfflineDownloadTool | str,
        file_detector: OpenListFileDetector,
        conflict_resolver: OpenListFileConflictResolver,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        task_snapshot_cache: OpenListTaskSnapshotCache | None = None,
    ) -> None:
        self._client = client
        self._offline_download_tool = offline_download_tool
        self._file_detector = file_detector
        self._conflict_resolver = conflict_resolver
        self._sleep = sleep
        self._task_snapshot_cache = task_snapshot_cache or OpenListTaskSnapshotCache(
            client
        )
        self._fresh_submission_intents: set[str] = set()

    async def run(
        self,
        task: OpenListWorkflowContext,
        checkpoint: WorkflowCheckpoint | None = None,
    ) -> OpenListWorkflowContext:
        try:
            while True:
                state = _workflow_state(task)
                if state == OpenListWorkflowState.DONE:
                    return task
                await self._run_state_step(task, state, checkpoint)
        except OpenListRemoteTaskFailed:
            await self._safe_cleanup(task)
            self._reset_remote_task(task)
            await self._checkpoint(task, OpenListWorkflowState.INIT, checkpoint)
            raise
        finally:
            if _workflow_state(task) == OpenListWorkflowState.DONE:
                await self._safe_cleanup(task)

    async def _run_state_step(
        self,
        task: OpenListWorkflowContext,
        state: OpenListWorkflowState,
        checkpoint: WorkflowCheckpoint | None,
    ) -> None:
        step = {
            OpenListWorkflowState.INIT: (
                self._prepare_submission,
                OpenListWorkflowState.SUBMITTING,
            ),
            OpenListWorkflowState.SUBMITTING: (
                self._submit_download,
                OpenListWorkflowState.SUBMITTED,
            ),
            OpenListWorkflowState.SUBMITTED: (
                self._wait_download_complete,
                OpenListWorkflowState.DOWNLOAD_DONE,
            ),
            OpenListWorkflowState.DOWNLOAD_DONE: (
                self._wait_transfer_complete,
                OpenListWorkflowState.TRANSFER_DONE,
            ),
            OpenListWorkflowState.TRANSFER_DONE: (
                self._detect_file,
                OpenListWorkflowState.FILE_DETECTED,
            ),
            OpenListWorkflowState.FILE_DETECTED: (
                self._resolve_file_to_move,
                OpenListWorkflowState.FILE_RESOLVED,
            ),
            OpenListWorkflowState.FILE_RESOLVED: (
                self._prepare_move,
                OpenListWorkflowState.MOVING,
            ),
            OpenListWorkflowState.MOVING: (
                self._move_to_target_directory,
                OpenListWorkflowState.MOVED,
            ),
        }.get(state)
        if step is None:
            await self._checkpoint(task, OpenListWorkflowState.DONE, checkpoint)
            return

        handler, next_state = step
        if state == OpenListWorkflowState.FILE_DETECTED:
            await handler(task, checkpoint)
        else:
            await handler(task)
        await self._checkpoint(task, next_state, checkpoint)
        if next_state == OpenListWorkflowState.SUBMITTING:
            self._fresh_submission_intents.add(task.id)

    async def _checkpoint(
        self,
        task: OpenListWorkflowContext,
        state: OpenListWorkflowState,
        checkpoint: WorkflowCheckpoint | None,
    ) -> None:
        task.downloader_data[OPENLIST_WORKFLOW_STATE_KEY] = state.value
        if checkpoint is not None:
            await checkpoint(task)

    @staticmethod
    def _reset_remote_task(task: OpenListWorkflowContext) -> None:
        for key in (
            OPENLIST_WORKFLOW_STATE_KEY,
            "task_id",
            "downloaded_filename",
            "downloaded_sidecars",
            "resolved_filename",
            "move_plan",
            "file_parent_path",
        ):
            task.downloader_data.pop(key, None)

    async def _prepare_submission(self, task: OpenListWorkflowContext) -> None:
        task.downloader_data["temp_path"] = _join_openlist_path(
            _temp_root_path(task.base_path), task.id
        )

    async def _submit_download(self, task: OpenListWorkflowContext) -> None:
        if task.downloader_data.get("task_id"):
            logger.debug(
                f"OpenList download already submitted: {task.downloader_data['task_id']}"
            )
            return

        temp_path = task.downloader_data.get("temp_path")
        if not temp_path:
            raise DownloadBackendError("No temp_path available for submission")

        fresh_intent = task.id in self._fresh_submission_intents
        self._fresh_submission_intents.discard(task.id)
        if not fresh_intent:
            recovered = await self._find_existing_submission(task, temp_path)
            if recovered is not None:
                task.downloader_data["task_id"] = recovered.id
                logger.info(
                    f"Recovered uncertain OpenList submission: "
                    f"job={task.id}, task={recovered.id}"
                )
                return

        logger.debug(
            f"OpenList submit: title={task.title}, "
            f"url={task.download_url}, temp={temp_path}"
        )

        tasks = await self._client.add_offline_download(
            urls=[task.download_url],
            path=temp_path,
            tool=self._offline_download_tool,
        )
        if not tasks:
            raise DownloadBackendError("Failed to create offline download task")

        self._task_snapshot_cache.invalidate()
        task.downloader_data["task_id"] = tasks[0].id
        logger.debug(f"OpenList task created: {tasks[0].id}")

    async def _find_existing_submission(
        self,
        task: OpenListWorkflowContext,
        temp_path: str,
    ) -> OpenlistTask | None:
        undone = await self._task_snapshot_cache.get_offline_download_undone()
        done = await self._task_snapshot_cache.get_offline_download_done()
        if undone is None or done is None:
            raise DownloadBackendError(
                "Cannot safely reconcile an uncertain OpenList submission"
            )
        references = (task.id, temp_path)
        matches = [
            item
            for item in [*undone, *done]
            if any(
                reference and reference in f"{item.name or ''} {item.status or ''}"
                for reference in references
            )
        ]
        if len(matches) > 1:
            logger.warning(
                f"Multiple OpenList tasks match job {task.id}; "
                f"using {matches[0].id}"
            )
        return matches[0] if matches else None

    def _ensure_task_succeeded(self, matching_done: OpenlistTask, label: str) -> None:
        if matching_done.state != OpenlistTaskState.SUCCEEDED:
            details = matching_done.error or matching_done.status
            message = f"{label} failed with state: {matching_done.state}"
            if details:
                message = f"{message}: {details}"
            logger.warning(message)
            raise OpenListRemoteTaskFailed(message)

    async def _wait_download_complete(self, task: OpenListWorkflowContext) -> None:
        task_id = task.downloader_data.get("task_id")
        if not task_id:
            raise DownloadBackendError("No task ID available")

        while True:
            matching = await self._find_undone_download_task(task_id)
            if matching is not None:
                if await self._handle_undone_download_task(task, matching):
                    return
                continue

            if await self._download_task_is_done(task_id):
                return

            raise DownloadBackendError(
                f"Task {task_id} not found in undone or done lists"
            )

    async def _find_undone_download_task(self, task_id: str) -> OpenlistTask | None:
        undone = await self._task_snapshot_cache.get_offline_download_undone()
        if undone is None:
            raise DownloadBackendError("Failed to fetch undone download tasks")
        return next((t for t in undone if t.id == task_id), None)

    async def _handle_undone_download_task(
        self, task: OpenListWorkflowContext, matching: OpenlistTask
    ) -> bool:
        progress = float(matching.progress) if matching.progress else None
        self._log_progress(task, progress, is_transfer=False)
        if self._is_complete_progress(progress) and await self._transfer_task_exists(
            task
        ):
            logger.debug(
                f"OpenList download task {matching.id} is still in undone list "
                "at 100%, but transfer task exists; advancing to transfer"
            )
            return True

        await self._sleep(5)
        return False

    async def _download_task_is_done(self, task_id: str) -> bool:
        done = await self._task_snapshot_cache.get_offline_download_done()
        if done is None:
            raise DownloadBackendError("Failed to fetch done download tasks")

        matching_done = next((t for t in done if t.id == task_id), None)
        if matching_done is None:
            return False

        self._ensure_task_succeeded(matching_done, "Task")
        return True

    async def _transfer_task_exists(self, task: OpenListWorkflowContext) -> bool:
        task_uuid = task.id
        undone = await self._task_snapshot_cache.get_offline_download_transfer_undone()
        if undone is None:
            logger.debug("Could not probe undone transfer tasks")
        elif any(task_uuid in transfer.name for transfer in undone):
            return True

        done = await self._task_snapshot_cache.get_offline_download_transfer_done()
        if done is None:
            logger.debug("Could not probe done transfer tasks")
            return False
        return any(task_uuid in transfer.name for transfer in done)

    @staticmethod
    def _is_complete_progress(progress: float | None) -> bool:
        return progress is not None and progress >= 100.0

    async def _wait_transfer_complete(self, task: OpenListWorkflowContext) -> None:
        task_uuid = task.id
        not_found_count = 0

        while True:
            undone = (
                await self._task_snapshot_cache.get_offline_download_transfer_undone()
            )
            if undone is None:
                raise DownloadBackendError("Failed to fetch undone transfer tasks")

            matching_undone = next((t for t in undone if task_uuid in t.name), None)
            if matching_undone is not None:
                progress = (
                    float(matching_undone.progress)
                    if matching_undone.progress
                    else None
                )
                self._log_progress(task, progress, is_transfer=True)
                not_found_count = 0
                await self._sleep(self._TRANSFER_CHECK_INTERVAL_SECONDS)
                continue

            done = await self._task_snapshot_cache.get_offline_download_transfer_done()
            if done is None:
                raise DownloadBackendError("Failed to fetch done transfer tasks")

            matching_done = next((t for t in done if task_uuid in t.name), None)
            if matching_done is not None:
                self._ensure_task_succeeded(matching_done, "Transfer")
                return

            not_found_count += 1
            if not_found_count >= self._TRANSFER_CHECK_MAX_RETRIES:
                logger.debug(
                    f"No transfer task for {task_uuid} after "
                    f"{self._TRANSFER_CHECK_MAX_RETRIES} checks, skipping"
                )
                return

            await self._sleep(self._TRANSFER_CHECK_INTERVAL_SECONDS)

    async def _detect_file(self, task: OpenListWorkflowContext) -> None:
        temp_path = task.downloader_data.get("temp_path")
        if not temp_path:
            raise DownloadBackendError("No temp_path available")

        detected = await self._file_detector.detect(temp_path)
        if not detected:
            raise DownloadBackendError("Could not detect downloaded file")

        task.downloader_data["downloaded_filename"] = detected.video_relative_path
        task.downloader_data["downloaded_sidecars"] = [
            {"relative_path": item.relative_path, "suffix": item.suffix}
            for item in detected.sidecars
        ]

    async def _resolve_file_to_move(
        self,
        task: OpenListWorkflowContext,
        checkpoint: WorkflowCheckpoint | None,
    ) -> None:
        downloaded_filename = task.downloader_data.get("downloaded_filename")
        temp_path = task.downloader_data.get("temp_path")
        if not downloaded_filename:
            raise DownloadBackendError("No downloaded filename available")
        if not temp_path:
            raise DownloadBackendError("No temp_path available")

        if "/" in downloaded_filename:
            sub_dir, bare_filename = downloaded_filename.rsplit("/", 1)
            file_parent_path = f"{temp_path.rstrip('/')}/{sub_dir}"
        else:
            bare_filename = downloaded_filename
            file_parent_path = temp_path

        sidecars: list[dict[str, str]] = []
        for item in task.downloader_data.get("downloaded_sidecars", []):
            relative_path = str(item.get("relative_path") or "")
            if not relative_path:
                continue
            sidecar_parent, sidecar_name = (
                relative_path.rsplit("/", 1)
                if "/" in relative_path
                else ("", relative_path)
            )
            expected_parent = (
                downloaded_filename.rsplit("/", 1)[0]
                if "/" in downloaded_filename
                else ""
            )
            if sidecar_parent != expected_parent:
                continue
            sidecars.append(
                {"source": sidecar_name, "suffix": str(item.get("suffix") or "")}
            )

        final_dir_path = task.target_directory_path
        if not final_dir_path:
            raise DownloadBackendError("No target directory path available")
        for directory_path in _directory_creation_paths(task.base_path, final_dir_path):
            if not await self._client.mkdir(directory_path):
                raise DownloadBackendError(
                    f"Failed to create directory: {directory_path}"
                )

        existing_plan = task.downloader_data.get("move_plan")
        if existing_plan:
            move_plan = [dict(item) for item in existing_plan]
        else:
            source_entries = await self._client.list_files(file_parent_path)
            target_entries = await self._client.list_files(final_dir_path)
            if source_entries is None or target_entries is None:
                raise DownloadBackendError("Cannot plan OpenList file moves")
            source_names = {entry.name for entry in source_entries}
            target_names = {entry.name for entry in target_entries}
            originals = [bare_filename, *(item["source"] for item in sidecars)]
            missing = [name for name in originals if name not in source_names]
            if missing:
                raise DownloadBackendError(
                    f"Move sources are missing before planning: {', '.join(missing)}"
                )

            reserved_names = set(target_names)
            move_plan = []
            for index, original in enumerate(originals):
                resolved = original
                if resolved in reserved_names:
                    resolved = self._conflict_resolver.next_available_name(
                        original, reserved_names | source_names
                    )
                reserved_names.add(resolved)
                plan_item = {
                    "kind": "video" if index == 0 else "subtitle",
                    "source": original,
                    "filename": resolved,
                }
                if index > 0:
                    plan_item["suffix"] = sidecars[index - 1]["suffix"]
                move_plan.append(plan_item)

            task.downloader_data["file_parent_path"] = file_parent_path
            task.downloader_data["resolved_filename"] = move_plan[0]["filename"]
            task.downloader_data["move_plan"] = move_plan
            await self._checkpoint(
                task, OpenListWorkflowState.FILE_DETECTED, checkpoint
            )

        for item in move_plan:
            source = item["source"]
            resolved = item["filename"]
            if source == resolved:
                continue
            current = await self._client.list_files(file_parent_path)
            if current is None:
                raise DownloadBackendError("Cannot reconcile move-plan renames")
            current_names = {entry.name for entry in current}
            if source not in current_names and resolved in current_names:
                continue
            if source not in current_names or resolved in current_names:
                raise DownloadBackendError(
                    f"Ambiguous move-plan rename state: {source} -> {resolved}"
                )
            if not await self._client.rename_file(
                f"{file_parent_path.rstrip('/')}/{source}", resolved
            ):
                raise DownloadBackendError(
                    f"Failed to prepare move filename: {source} -> {resolved}"
                )
            await self._sleep(self._TRANSFER_CHECK_INTERVAL_SECONDS)

    async def _prepare_move(self, task: OpenListWorkflowContext) -> None:
        if not task.downloader_data.get("file_parent_path"):
            raise DownloadBackendError("No file_parent_path available")
        if not task.downloader_data.get("resolved_filename"):
            raise DownloadBackendError("No resolved_filename available")
        if not task.downloader_data.get("move_plan"):
            task.downloader_data["move_plan"] = [
                {
                    "kind": "video",
                    "source": task.downloader_data["resolved_filename"],
                    "filename": task.downloader_data["resolved_filename"],
                }
            ]

    async def _move_to_target_directory(self, task: OpenListWorkflowContext) -> None:
        file_parent_path = task.downloader_data.get("file_parent_path")
        move_plan = task.downloader_data.get("move_plan") or []
        if not file_parent_path:
            raise DownloadBackendError("No file_parent_path available")
        if not move_plan:
            resolved = task.downloader_data.get("resolved_filename")
            if not resolved:
                raise DownloadBackendError("No move_plan available")
            move_plan = [
                {
                    "kind": "video",
                    "source": resolved,
                    "filename": resolved,
                }
            ]
            task.downloader_data["move_plan"] = move_plan

        final_dir_path = task.target_directory_path
        if not final_dir_path:
            raise DownloadBackendError("No target directory path available")

        source_entries = await self._client.list_files(file_parent_path)
        target_entries = await self._client.list_files(final_dir_path)
        if source_entries is None or target_entries is None:
            raise DownloadBackendError("Cannot reconcile an uncertain OpenList move")
        source_names = {entry.name for entry in source_entries}
        target_names = {entry.name for entry in target_entries}
        pending: list[str] = []
        for item in move_plan:
            filename = item["filename"]
            in_source = filename in source_names
            in_target = filename in target_names
            if in_source and not in_target:
                pending.append(filename)
                continue
            if not in_source and in_target:
                continue
            raise DownloadBackendError(
                f"Ambiguous OpenList move state for '{filename}': "
                f"source={in_source}, target={in_target}"
            )

        if pending:
            logger.debug(
                f"OpenList move: {file_parent_path} -> {final_dir_path}; "
                f"files={pending}"
            )
            if not await self._client.move_file(
                file_parent_path, final_dir_path, pending
            ):
                raise DownloadBackendError(f"Failed to move files to: {final_dir_path}")

            await self._sleep(self._TRANSFER_CHECK_INTERVAL_SECONDS)

        if pending:
            refreshed_source = await self._client.list_files(file_parent_path)
            refreshed_target = await self._client.list_files(final_dir_path)
            if refreshed_source is None or refreshed_target is None:
                raise DownloadBackendError("Cannot verify completed OpenList move")
            refreshed_source_names = {entry.name for entry in refreshed_source}
            refreshed_target_names = {entry.name for entry in refreshed_target}
        else:
            refreshed_source_names = source_names
            refreshed_target_names = target_names
        unresolved = [
            item["filename"]
            for item in move_plan
            if item["filename"] in refreshed_source_names
            or item["filename"] not in refreshed_target_names
        ]
        if unresolved:
            raise DownloadBackendError(
                f"OpenList move verification failed: {', '.join(unresolved)}"
            )

        self._record_materialized_files(task, final_dir_path, move_plan)

    @staticmethod
    def _record_materialized_files(
        task: OpenListWorkflowContext,
        directory_path: str,
        move_plan: list[dict[str, str]],
    ) -> None:
        video = next(item for item in move_plan if item["kind"] == "video")
        filename = video["filename"]
        task.output_path = f"{directory_path}/{filename}"
        task.downloader_data["materialized_directory_path"] = directory_path
        task.downloader_data["materialized_filename"] = filename
        task.downloader_data["materialized_sidecars"] = [
            {"filename": item["filename"], "suffix": item.get("suffix", "")}
            for item in move_plan
            if item["kind"] == "subtitle"
        ]

    async def _safe_cleanup(self, task: OpenListWorkflowContext) -> None:
        if not task.downloader_data.get("temp_path"):
            return
        try:
            logger.debug(f"Cleaning up temporary directory: {task.id}")
            await self._client.remove_path(_temp_root_path(task.base_path), [task.id])
        except Exception as e:
            logger.warning(f"Cleanup failed for {task.id}: {e}")

    def _log_progress(
        self,
        task: OpenListWorkflowContext,
        progress: float | None,
        is_transfer: bool = False,
    ) -> None:
        if progress is None:
            return

        bounded_progress = max(0.0, min(progress, 100.0))
        task.progress = bounded_progress
        bucket_size = 25
        bucket_index = min(int(bounded_progress // bucket_size), 4)
        if bucket_index == 0:
            return
        bucket_key = (
            "_transfer_progress_bucket" if is_transfer else "_download_progress_bucket"
        )
        last_bucket = task.downloader_data.get(bucket_key)

        if last_bucket != bucket_index:
            task.downloader_data[bucket_key] = bucket_index
            label = format_anime_episode(
                task.anime_name,
                task.season,
                task.episode,
            )
            task_ref = task.id[:8]
            openlist_task_id = task.downloader_data.get("task_id", "unknown")
            logger.info(
                f"{'Transferring' if is_transfer else 'Downloading'} "
                f"[{label}]: {bucket_index * bucket_size}% "
                f"(task={task_ref}, openlist_task={openlist_task_id})"
            )
