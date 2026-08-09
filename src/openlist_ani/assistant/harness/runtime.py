"""Local agent sessions used by messaging and CLI frontends."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from pathlib import Path

from openlist_ani.adapters.configuration.models import AISourceConfig
from openlist_ani.assistant.contracts import EventType, LoopEvent

from .adapters import AgentAdapter, SessionSpec, get_agent_adapter

_LOCAL_SYSTEM_PROMPT = """You are the OpenList-Ani assistant.
Use the standard Agent Skills installed in this session when they match the
user's request. Follow each selected SKILL.md and run its scripts from the
Skill directory. Ask for explicit confirmation before downloads,
subscriptions, collection changes, or other write operations. Give concise,
actionable errors when a dependency is unavailable.
When you need explicit confirmation, end the user-facing response with the
exact marker [[CONFIRMATION_REQUIRED]]. Never emit that marker otherwise.
"""

_CONFIRMATION_MARKER = "[[CONFIRMATION_REQUIRED]]"
_RPC_STREAM_LIMIT = 1024 * 1024
_CANCELLED_MESSAGE = "已取消当前请求。"
_CONFIRMATION_MESSAGE = "等待你确认后再执行写操作。"
_CANCELLED_EVENT = "oani.cancelled"


def _harness_environment(config_path: Path) -> dict[str, str]:
    """Build the environment inherited by harnesses and Skill scripts.

    Agent shells run packaged Skill scripts from their Skill directories. Those
    directories can be read-only (notably in the Docker image and system-wide
    wheel installs), so child processes must not initialize the application's
    cwd-relative file logger there. This only changes the copied child
    environment; logging in the Assistant and Backend processes is unaffected.
    """

    environment = os.environ.copy()
    environment["CONFIG_PATH"] = str(config_path)
    environment["OPENLIST_ANI_FILE_LOGGING"] = "0"
    return environment


class HarnessSession(ABC):
    @abstractmethod
    async def stream(self, prompt: str) -> AsyncGenerator[LoopEvent, None]: ...

    async def reset(self) -> None:  # NOSONAR - optional awaitable session hook
        return None

    async def cancel(self) -> None:  # NOSONAR - optional awaitable session hook
        return None

    async def close(self) -> None:  # NOSONAR - optional awaitable session hook
        return None


class PiRPCSession(HarnessSession):
    """Persistent Pi session using its LF-delimited RPC protocol."""

    def __init__(self, adapter: AgentAdapter, spec: SessionSpec) -> None:
        self._adapter = adapter
        self._spec = spec
        self._source = spec.source
        self._config_path = spec.config_path.resolve()
        self._temporary = tempfile.TemporaryDirectory(prefix="oani-pi-session-")
        self._working_dir = Path(self._temporary.name)
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        self._lock = asyncio.Lock()
        self._provider_dir: Path | None = None
        self._tool_runs: dict[str, tuple[str, float]] = {}
        self._session_announced = False
        self._cancelled = False

    async def stream(self, prompt: str) -> AsyncGenerator[LoopEvent, None]:
        async with self._lock:
            self._cancelled = False
            await self._ensure_started()
            if not self._session_announced:
                self._session_announced = True
                yield LoopEvent(EventType.SESSION_STARTED, "Pi session started")
            yield LoopEvent(EventType.THINKING, "正在理解请求…")

            await self._send_prompt(prompt)

            accepted = False
            latest_parts: list[str] = []
            while True:
                payload = await self._read_turn_payload()
                if payload is None:
                    yield LoopEvent(EventType.DONE, _CANCELLED_MESSAGE)
                    return
                events, accepted, done = _pi_turn_events(
                    payload,
                    accepted=accepted,
                    latest_parts=latest_parts,
                    tool_runs=self._tool_runs,
                )
                for event in events:
                    yield event
                if done:
                    return

    async def _send_prompt(self, prompt: str) -> None:
        process = self._require_process()
        request = json.dumps(
            {"id": "prompt", "type": "prompt", "message": prompt},
            ensure_ascii=False,
        )
        assert process.stdin is not None
        process.stdin.write((request + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _read_turn_payload(self) -> dict | None:
        try:
            return await self._read_payload()
        except RuntimeError:
            if self._cancelled:
                return None
            raise

    async def reset(self) -> None:
        self._session_announced = False
        if self._process is None or self._process.returncode is not None:
            return
        async with self._lock:
            process = self._require_process()
            assert process.stdin is not None
            process.stdin.write(b'{"id":"reset","type":"new_session"}\n')
            await process.stdin.drain()
            while True:
                payload = await self._read_payload()
                if payload.get("type") == "response" and payload.get("id") == "reset":
                    if not payload.get("success"):
                        raise RuntimeError(
                            f"Pi could not reset the session: {payload.get('error')}"
                        )
                    return

    async def cancel(self) -> None:
        self._cancelled = True
        await self._stop_process()

    async def close(self) -> None:
        await self._stop_process()
        self._temporary.cleanup()

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        await self._adapter.ensure_native_skills(self._spec)
        source = self._source
        configured_executable = (
            source.executable
            if source and source.type == "agent" and source.executable
            else ""
        )
        executable = await self._adapter.resolve_executable(
            configured_executable,
            config_path=self._config_path,
        )
        managed_shell = ""
        if sys.platform == "win32":
            from .pi_runtime import ensure_pi_shell

            managed_shell = await asyncio.to_thread(
                ensure_pi_shell, config_path=self._config_path
            )

        command = [
            executable,
            "--mode",
            "rpc",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-skills",
            "--system-prompt",
            _LOCAL_SYSTEM_PROMPT,
        ]
        if managed_shell:
            # Pi's bundled Windows runtime resolves Bash with ``where.exe``
            # before every tool invocation. That lookup can fail
            # intermittently even while the same Bash executable is healthy.
            # A trusted, session-local setting gives Pi the already-verified
            # absolute path and avoids PATH discovery entirely.
            self._prepare_project_settings(managed_shell)
            command.append("--approve")
        command.extend(self._adapter.session_arguments(self._spec))

        environment = _harness_environment(self._config_path)
        environment["PI_SKIP_VERSION_CHECK"] = "1"
        if sys.platform == "win32":
            # Skill CLIs emit JSON through Pi's shell pipe. Keep the byte
            # encoding deterministic instead of inheriting the active OEM
            # code page from a Telegram/desktop launch.
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
        if managed_shell:
            path_key = next(
                (key for key in environment if key.lower() == "path"), "PATH"
            )
            environment[path_key] = os.pathsep.join(
                [str(Path(managed_shell).parent), environment.get(path_key, "")]
            ).rstrip(os.pathsep)
        if source is not None and source.type == "api":
            environment.update(self._prepare_api_source(source))
            command.extend(["--provider", "openlist-ani", "--model", source.model])
        elif source is not None and source.model:
            command.extend(["--model", source.model])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                cwd=self._working_dir,
                limit=_RPC_STREAM_LIMIT,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise RuntimeError(
                f"Agent executable '{executable}' could not be started. Install the "
                "pinned Pi runtime, check execute permission, or configure "
                "[ai.sources.<name>].executable."
            ) from error
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    def _prepare_project_settings(self, managed_shell: str) -> Path:
        directory = self._working_dir / ".pi"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / "settings.json"
        path.write_text(
            json.dumps({"shellPath": str(Path(managed_shell).resolve())}),
            encoding="utf-8",
        )
        with contextlib.suppress(PermissionError):
            path.chmod(0o600)
        return path

    def _prepare_api_source(self, source: AISourceConfig) -> dict[str, str]:
        directory = self._working_dir / "pi-config"
        directory.mkdir(mode=0o700, exist_ok=True)
        self._provider_dir = directory
        api = (
            "openai-completions"
            if source.provider == "openai-compatible"
            else "anthropic-messages"
        )
        provider: dict[str, object] = {
            "baseUrl": source.base_url,
            "api": api,
            "apiKey": source.api_key,
            "models": [{"id": source.model, "name": source.model}],
        }
        if source.provider == "openai-compatible":
            provider["authHeader"] = True
        path = directory / "models.json"
        path.write_text(
            json.dumps({"providers": {"openlist-ani": provider}}, ensure_ascii=False),
            encoding="utf-8",
        )
        with contextlib.suppress(PermissionError):
            path.chmod(0o600)
        return {"PI_CODING_AGENT_DIR": str(directory)}

    async def _read_payload(self) -> dict:
        process = self._require_process()
        assert process.stdout is not None
        line = await process.stdout.readline()
        if not line:
            detail = "\n".join(self._stderr_tail[-10:]).strip()
            raise RuntimeError(
                "Pi RPC process exited unexpectedly"
                + (f": {detail}" if detail else ".")
            )
        try:
            return json.loads(line.decode("utf-8").rstrip("\r\n"))
        except json.JSONDecodeError as error:
            raise RuntimeError("Pi RPC returned invalid JSONL output.") from error

    async def _drain_stderr(self) -> None:
        process = self._require_process()
        assert process.stderr is not None
        while line := await process.stderr.readline():
            self._stderr_tail.append(line.decode("utf-8", errors="replace").strip())
            del self._stderr_tail[:-20]

    async def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("Pi RPC process is not running.")
        return self._process


class _CommandAgentSession(HarnessSession):
    def __init__(self, adapter: AgentAdapter, spec: SessionSpec) -> None:
        if spec.source is None:
            raise ValueError(f"{adapter.name} requires an agent source")
        self._adapter = adapter
        self._spec = spec
        self._source = spec.source
        self._config_path = spec.config_path.resolve()
        self._temporary = tempfile.TemporaryDirectory(
            prefix=f"oani-{adapter.name}-session-"
        )
        self._working_dir = Path(self._temporary.name)
        self._current_process: asyncio.subprocess.Process | None = None
        self._session_announced = False
        self._cancelled = False

    async def cancel(self) -> None:
        self._cancelled = True
        process = self._current_process
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

    async def close(self) -> None:
        await self.cancel()
        self._temporary.cleanup()

    async def _run_process(self, command: list[str], prompt: str) -> str:
        environment = _harness_environment(self._config_path)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=environment,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise RuntimeError(
                f"Agent executable '{command[0]}' could not be started. Install it, "
                "check execute permission, or set [ai.sources.<name>].executable."
            ) from error
        self._current_process = process
        self._cancelled = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")), timeout=300
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError("Agent process timed out after 300 seconds.") from error
        finally:
            self._current_process = None
        if self._cancelled:
            return _CANCELLED_MESSAGE
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Agent process exited with code {process.returncode}: "
                f"{detail[-1000:] or 'no diagnostic output'}"
            )
        return stdout.decode("utf-8", errors="replace").strip()

    async def _stream_json_process(
        self, command: list[str], prompt: str
    ) -> AsyncGenerator[dict, None]:
        """Yield a command harness's JSONL output while the turn is running."""
        environment = _harness_environment(self._config_path)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=environment,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise RuntimeError(
                f"Agent executable '{command[0]}' could not be started. Install it, "
                "check execute permission, or set [ai.sources.<name>].executable."
            ) from error

        self._current_process = process
        self._cancelled = False
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        stderr_task = asyncio.create_task(process.stderr.read())
        invalid_tail: list[str] = []
        try:
            async with asyncio.timeout(300):
                while line := await process.stdout.readline():
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    try:
                        payload = json.loads(decoded)
                    except json.JSONDecodeError:
                        invalid_tail.append(decoded)
                        del invalid_tail[:-5]
                        continue
                    if isinstance(payload, dict):
                        yield payload
                return_code = await process.wait()
        except TimeoutError as error:
            process.kill()
            await process.wait()
            await stderr_task
            raise RuntimeError("Agent process timed out after 300 seconds.") from error
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            if not stderr_task.done():
                await stderr_task
            self._current_process = None

        stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
        if self._cancelled:
            yield {"type": _CANCELLED_EVENT}
            return
        if return_code != 0:
            detail = stderr or "\n".join(invalid_tail)
            raise RuntimeError(
                f"Agent process exited with code {return_code}: "
                f"{detail[-1000:] or 'no diagnostic output'}"
            )

    def _start_events(self) -> list[LoopEvent]:
        events: list[LoopEvent] = []
        if not self._session_announced:
            self._session_announced = True
            events.append(
                LoopEvent(
                    EventType.SESSION_STARTED, f"{self._adapter.name} session started"
                )
            )
        events.append(LoopEvent(EventType.THINKING, "正在理解请求…"))
        return events


class ClaudeCodeSession(_CommandAgentSession):
    def __init__(self, adapter: AgentAdapter, spec: SessionSpec) -> None:
        super().__init__(adapter, spec)
        self._session_id = str(uuid.uuid4())
        self._started = False

    async def stream(self, prompt: str) -> AsyncGenerator[LoopEvent, None]:
        for event in self._start_events():
            yield event
        await self._adapter.ensure_native_skills(self._spec)
        command = self._command()
        response_parts: list[str] = []
        result_text = ""
        tool_runs: dict[str, tuple[str, float]] = {}
        async for payload in self._stream_json_process(command, prompt):
            if payload.get("type") == _CANCELLED_EVENT:
                yield LoopEvent(EventType.DONE, _CANCELLED_MESSAGE)
                return
            for event in _claude_stream_events(payload, tool_runs):
                if event.type == EventType.TEXT_DELTA:
                    response_parts.append(event.text)
                yield event
            if payload.get("type") == "result" and isinstance(
                payload.get("result"), str
            ):
                result_text = payload["result"]
        self._started = True
        response = result_text.strip() or "".join(response_parts).strip()
        for event in _final_response_events(
            response, empty_error="Claude Code returned an empty final message."
        ):
            yield event

    def _command(self) -> list[str]:
        command = [
            self._source.executable or self._adapter.default_executable,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode",
            "auto",
            "--append-system-prompt",
            _LOCAL_SYSTEM_PROMPT,
        ]
        command.extend(self._adapter.session_arguments(self._spec))
        if self._source.model:
            command.extend(["--model", self._source.model])
        if self._started:
            command.extend(["--resume", self._session_id])
        else:
            command.extend(["--session-id", self._session_id])
        return command

    async def reset(self) -> None:
        await self.cancel()
        self._session_id = str(uuid.uuid4())
        self._started = False
        self._session_announced = False


class CodexSession(_CommandAgentSession):
    def __init__(self, adapter: AgentAdapter, spec: SessionSpec) -> None:
        super().__init__(adapter, spec)
        adapter.prepare_working_directory(spec, self._working_dir)
        self._thread_id: str | None = None

    async def stream(self, prompt: str) -> AsyncGenerator[LoopEvent, None]:
        for event in self._start_events():
            yield event
        await self._adapter.ensure_native_skills(self._spec)
        descriptor, output_name = tempfile.mkstemp(
            prefix="oani-codex-", suffix=".txt", dir=self._working_dir
        )
        os.close(descriptor)
        output_path = Path(output_name)
        command, request = self._command(prompt, output_path)
        try:
            async for payload in self._stream_json_process(command, request):
                if payload.get("type") == _CANCELLED_EVENT:
                    yield LoopEvent(EventType.DONE, _CANCELLED_MESSAGE)
                    return
                if thread_id := _codex_thread_id(payload):
                    self._thread_id = thread_id
                for event in _codex_payload_events(payload):
                    yield event
            if self._thread_id is None:
                raise RuntimeError(
                    "Codex did not report a thread ID; upgrade the configured "
                    "Codex CLI so native session resume is available."
                )
            for event in _final_response_events(
                output_path.read_text(encoding="utf-8").strip(),
                empty_error="Codex returned an empty final message.",
            ):
                yield event
        finally:
            output_path.unlink(missing_ok=True)

    def _command(self, prompt: str, output_path: Path) -> tuple[list[str], str]:
        command = [self._source.executable or self._adapter.default_executable, "exec"]
        first_turn = self._thread_id is None
        if not first_turn:
            command.append("resume")
        command.extend(
            [
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
            ]
        )
        if self._source.model:
            command.extend(["--model", self._source.model])
        if first_turn:
            command.append("-")
            request = _LOCAL_SYSTEM_PROMPT + "\n\n" + prompt
        else:
            command.extend([self._thread_id, "-"])
            request = prompt
        return command, request

    async def reset(self) -> None:
        await self.cancel()
        self._thread_id = None
        self._session_announced = False


def create_harness_session(
    source: AISourceConfig | None,
    *,
    builtin_plugin_root: Path,
    user_skills_root: Path | None,
    config_path: Path,
) -> HarnessSession:
    agent_name = "pi" if source is None or source.type == "api" else source.agent
    adapter = get_agent_adapter(agent_name)
    return adapter.open_session(
        SessionSpec(
            source=source,
            builtin_plugin_root=builtin_plugin_root,
            user_skills_root=user_skills_root,
            config_path=config_path,
        )
    )


def _pi_turn_events(
    payload: dict,
    *,
    accepted: bool,
    latest_parts: list[str],
    tool_runs: dict[str, tuple[str, float]],
) -> tuple[list[LoopEvent], bool, bool]:
    event_type = payload.get("type")
    if event_type == "response" and payload.get("id") == "prompt":
        return _pi_prompt_response(payload)
    if event_type == "message_update":
        return _pi_message_update(payload, accepted, latest_parts)
    if event_type in {
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    }:
        mapped = _map_pi_message_event(payload, tool_runs)
        return ([mapped] if mapped is not None else []), accepted, False
    if event_type == "agent_end":
        response = _last_assistant_text(payload.get("messages", []))
        response = response or "".join(latest_parts).strip()
        return _final_response_events(response, empty_error=""), accepted, True
    if event_type == "extension_error":
        raise RuntimeError(
            f"Pi extension error: {payload.get('error', 'unknown error')}"
        )
    if not accepted and event_type == "error":
        raise RuntimeError(str(payload.get("error") or "Pi session failed"))
    return [], accepted, False


def _pi_prompt_response(payload: dict) -> tuple[list[LoopEvent], bool, bool]:
    if not payload.get("success"):
        raise RuntimeError(
            f"Pi rejected the prompt: {payload.get('error', 'unknown error')}"
        )
    return [], True, False


def _pi_message_update(
    payload: dict, accepted: bool, latest_parts: list[str]
) -> tuple[list[LoopEvent], bool, bool]:
    event = payload.get("assistantMessageEvent") or {}
    if str(event.get("type") or "") == "text_start":
        latest_parts.clear()
    mapped = _map_pi_message_event(event)
    if mapped is None:
        return [], accepted, False
    if mapped.type == EventType.TEXT_DELTA:
        latest_parts.append(mapped.text)
    return [mapped], accepted, False


def _final_response_events(response: str, *, empty_error: str) -> list[LoopEvent]:
    if not response and empty_error:
        raise RuntimeError(empty_error)
    response, confirmation_required = _split_confirmation(response)
    events: list[LoopEvent] = []
    if confirmation_required:
        events.append(LoopEvent(EventType.CONFIRMATION_REQUIRED, _CONFIRMATION_MESSAGE))
    events.append(LoopEvent(EventType.DONE, response))
    return events


def _map_pi_message_event(
    event: dict,
    tool_runs: dict[str, tuple[str, float]] | None = None,
) -> LoopEvent | None:
    event_type = str(event.get("type") or "")
    if event_type == "text_delta" and event.get("delta"):
        return LoopEvent(EventType.TEXT_DELTA, str(event["delta"]))
    if event_type in {"tool_execution_start", "tool_start"}:
        return _pi_tool_start_event(event, tool_runs)
    if event_type in {"tool_execution_update", "tool_update"}:
        return None
    if event_type in {"tool_execution_end", "tool_end"}:
        return _pi_tool_end_event(event, tool_runs)
    return None


def _pi_tool_start_event(
    event: dict, tool_runs: dict[str, tuple[str, float]] | None
) -> LoopEvent:
    tool_name = str(event.get("toolName") or event.get("tool_name") or "tool")
    arguments = event.get("args") or event.get("arguments") or {}
    label, is_skill = _friendly_tool_label(tool_name, arguments)
    tool_call_id = str(event.get("toolCallId") or event.get("tool_call_id") or "")
    if tool_runs is not None and tool_call_id:
        tool_runs[tool_call_id] = (label, time.monotonic())
    return LoopEvent(
        EventType.SKILL_SELECTED if is_skill else EventType.SCRIPT_STARTED,
        f"读取 {label}" if is_skill else f"执行 {label}",
        data={
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "arguments": _safe_tool_arguments(arguments),
        },
    )


def _pi_tool_end_event(
    event: dict, tool_runs: dict[str, tuple[str, float]] | None
) -> LoopEvent:
    tool_name = str(event.get("toolName") or event.get("tool_name") or "script")
    tool_call_id = str(event.get("toolCallId") or event.get("tool_call_id") or "")
    stored = tool_runs.pop(tool_call_id, None) if tool_runs and tool_call_id else None
    if stored is None:
        label, _ = _friendly_tool_label(tool_name, event.get("args") or {})
        started = None
    else:
        label, started = stored
    duration_ms = (
        max(0, int((time.monotonic() - started) * 1000))
        if started is not None
        else None
    )
    is_error = bool(event.get("isError") or event.get("is_error"))
    suffix = "失败" if is_error else "完成"
    if duration_ms is not None:
        suffix += f"（{_format_duration(duration_ms)}）"
    return LoopEvent(
        EventType.SCRIPT_FINISHED,
        f"{label} {suffix}",
        data={
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "success": not is_error,
            "duration_ms": duration_ms,
        },
    )


def _friendly_tool_label(tool_name: str, arguments: object) -> tuple[str, bool]:
    lowered = tool_name.lower()
    if skill_label := _skill_tool_label(lowered, arguments):
        return skill_label
    if lowered in {"bash", "shell"}:
        return _shell_tool_label(arguments), False
    if lowered == "read":
        path = str(arguments.get("path") or "") if isinstance(arguments, dict) else ""
        return (f"read · {Path(path).name}" if path else "read"), False
    detail = _argument_summary(arguments)
    return (f"{tool_name} · {detail}" if detail else tool_name), False


def _skill_tool_label(
    lowered_tool_name: str, arguments: object
) -> tuple[str, bool] | None:
    if not isinstance(arguments, dict):
        return None
    if lowered_tool_name == "read":
        path = str(arguments.get("path") or "")
        if path.endswith("SKILL.md"):
            return f"Skill {Path(path).parent.name}", True
    command = str(arguments.get("command") or arguments.get("cmd") or "")
    if "scripts/" not in command and "scripts\\" not in command:
        return None
    normalized_command = command.replace("\\", "/")
    script_path = _script_path_from_command(normalized_command)
    if script_path is None:
        return None
    action = script_path.stem.replace("_", " ")
    skill = script_path.parent.parent.name or _skill_name_from_command(
        normalized_command
    )
    detail = _script_argument_summary(command)
    label = f"Skill {skill} / {action}"
    return (f"{label} · {detail}" if detail else label), False


def _skill_name_from_command(command: str) -> str:
    match = re.search(r"/skills/(?P<skill>[\w.-]+)(?:[/'\"\s]|$)", command)
    return match.group("skill") if match else "unknown"


def _shell_tool_label(arguments: object) -> str:
    command = ""
    if isinstance(arguments, dict):
        command = str(arguments.get("command") or arguments.get("cmd") or "")
    preview = _safe_command_preview(command)
    return f"Bash · {preview}" if preview else "Bash"


def _script_path_from_command(command: str) -> Path | None:
    """Extract a short Skill script path without regex backtracking."""
    for token in command.split():
        token = token.strip("'\"")
        marker = "scripts/"
        marker_start = token.find(marker)
        suffix_end = token.find(".py", marker_start)
        if marker_start < 0 or suffix_end < 0:
            continue
        parent = token[:marker_start].rstrip("/").rsplit("/", 1)[-1]
        relative = token[marker_start : suffix_end + len(".py")]
        return Path(parent, relative) if parent else Path(relative)
    return None


_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|cookie|password|secret|token)"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|authorization|cookie|password|secret|token)\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
)
_URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]+")


def _safe_tool_arguments(arguments: object) -> dict[str, object]:
    if not isinstance(arguments, dict):
        return {}
    safe: dict[str, object] = {}
    for key, value in arguments.items():
        if _SENSITIVE_KEY_RE.search(str(key)):
            safe[str(key)] = "[已隐藏]"
        elif str(key) in {"command", "cmd"}:
            safe[str(key)] = _safe_command_preview(str(value))
        else:
            safe[str(key)] = _safe_value(value)
    return safe


def _safe_value(value: object) -> object:
    if isinstance(value, dict):
        return _safe_tool_arguments(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:5]]
    if isinstance(value, str):
        return _URL_QUERY_RE.sub(r"\1?[已隐藏]", value)[:160]
    return value


def _script_argument_summary(command: str) -> str:
    match = re.search(r"--json\s+(['\"])(.*?)\1", command)
    if not match:
        return ""
    try:
        payload = json.loads(match.group(2))
    except json.JSONDecodeError:
        return ""
    return _argument_summary(payload)


def _argument_summary(arguments: object) -> str:
    if not isinstance(arguments, dict):
        return ""
    parts: list[str] = []
    for key, value in arguments.items():
        if len(parts) >= 3:
            break
        if _SENSITIVE_KEY_RE.search(str(key)):
            continue
        safe = _safe_value(value)
        rendered = (
            json.dumps(safe, ensure_ascii=False) if not isinstance(safe, str) else safe
        )
        parts.append(f"{key}={rendered}")
    return ", ".join(parts)


def _safe_command_preview(command: str) -> str:
    collapsed = " ".join(command.split())
    collapsed = _ASSIGNMENT_SECRET_RE.sub(r"\1[已隐藏]", collapsed)
    collapsed = _URL_QUERY_RE.sub(r"\1?[已隐藏]", collapsed)
    if len(collapsed) > 180:
        return collapsed[:179] + "…"
    return collapsed


def _format_duration(duration_ms: int) -> str:
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.1f}s"


def _claude_stream_events(
    payload: dict,
    tool_runs: dict[str, tuple[str, float]] | None = None,
) -> list[LoopEvent]:
    return [
        *_claude_text_events(payload),
        *_claude_tool_start_events(payload, tool_runs),
        *_claude_tool_result_events(payload, tool_runs),
    ]


def _claude_text_events(payload: dict) -> list[LoopEvent]:
    if payload.get("type") == "stream_event":
        native = payload.get("event")
        if isinstance(native, dict) and native.get("type") == "content_block_delta":
            delta = native.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    return [LoopEvent(EventType.TEXT_DELTA, text)]
    return []


def _claude_content(payload: dict, payload_type: str) -> list[dict]:
    if payload.get("type") != payload_type:
        return []
    message = payload.get("message")
    content = message.get("content", []) if isinstance(message, dict) else []
    return (
        [block for block in content if isinstance(block, dict)]
        if isinstance(content, list)
        else []
    )


def _claude_tool_start_events(
    payload: dict, tool_runs: dict[str, tuple[str, float]] | None
) -> list[LoopEvent]:
    events: list[LoopEvent] = []
    for block in _claude_content(payload, "assistant"):
        if block.get("type") != "tool_use":
            continue
        tool_name = str(block.get("name") or "tool")
        tool_call_id = str(block.get("id") or "")
        arguments = block.get("input") or {}
        label, is_skill = _friendly_tool_label(tool_name, arguments)
        if tool_runs is not None and tool_call_id:
            tool_runs[tool_call_id] = (label, time.monotonic())
        events.append(
            LoopEvent(
                EventType.SKILL_SELECTED if is_skill else EventType.SCRIPT_STARTED,
                f"读取 {label}" if is_skill else f"执行 {label}",
                data={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "arguments": _safe_tool_arguments(arguments),
                },
            )
        )
    return events


def _claude_tool_result_events(
    payload: dict, tool_runs: dict[str, tuple[str, float]] | None
) -> list[LoopEvent]:
    events: list[LoopEvent] = []
    for block in _claude_content(payload, "user"):
        if block.get("type") != "tool_result":
            continue
        tool_call_id = str(block.get("tool_use_id") or "")
        stored = tool_runs.pop(tool_call_id, None) if tool_runs is not None else None
        label = stored[0] if stored else "Agent tool"
        duration_ms = (
            max(0, int((time.monotonic() - stored[1]) * 1000)) if stored else None
        )
        is_error = bool(block.get("is_error"))
        suffix = "失败" if is_error else "完成"
        if duration_ms is not None:
            suffix += f"（{_format_duration(duration_ms)}）"
        events.append(
            LoopEvent(
                EventType.SCRIPT_FINISHED,
                f"{label} {suffix}",
                data={
                    "tool_call_id": tool_call_id,
                    "success": not is_error,
                    "duration_ms": duration_ms,
                },
            )
        )
    return events


def _codex_payload_events(payload: dict) -> list[LoopEvent]:
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    item_type = item.get("type")
    if item_type == "agent_message" and payload.get("type") == "item.completed":
        text = item.get("text")
        return [LoopEvent(EventType.TEXT_DELTA, text)] if isinstance(text, str) else []
    if item_type != "command_execution":
        return []
    label, _ = _friendly_tool_label("shell", {"command": item.get("command", "")})
    if not label:
        return []
    completed = payload.get("type") == "item.completed"
    event_type = EventType.SCRIPT_FINISHED if completed else EventType.SCRIPT_STARTED
    success = item.get("status") not in {"failed", "error"}
    text = f"执行 {label}"
    if completed:
        outcome = "完成" if success else "失败"
        text = f"{label} {outcome}"
    return [LoopEvent(event_type, text, data={"success": success})]


def _last_assistant_text(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return text.strip()
    return ""


def _split_confirmation(response: str) -> tuple[str, bool]:
    required = _CONFIRMATION_MARKER in response
    return response.replace(_CONFIRMATION_MARKER, "").strip(), required


def _codex_thread_id(payload: dict) -> str | None:
    if payload.get("type") != "thread.started":
        return None
    thread_id = payload.get("thread_id") or payload.get("threadId")
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    return None


__all__ = [
    "ClaudeCodeSession",
    "CodexSession",
    "HarnessSession",
    "PiRPCSession",
    "create_harness_session",
]
