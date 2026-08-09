"""Extensible adapters for local agent harnesses.

The adapter is the only place that knows how to start a particular agent.
Assistant chat sessions and one-shot metadata extraction both resolve agents
through this module, so adding a harness does not require frontend changes.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openlist_ani.adapters.configuration.models import AISourceConfig
    from .runtime import HarnessSession


@dataclass(frozen=True)
class AgentStatus:
    name: str
    executable: str
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class SessionSpec:
    source: "AISourceConfig | None"
    builtin_plugin_root: Path
    user_skills_root: Path | None
    config_path: Path


@dataclass(frozen=True)
class StructuredRequest:
    prompt: str
    model: str = ""
    timeout: float = 120.0


class AgentAdapter(ABC):
    """Contract implemented by each supported local agent harness."""

    name: str
    default_executable: str

    async def resolve_executable(
        self,
        executable: str = "",
        *,
        config_path: Path | None = None,
    ) -> str:
        """Resolve the command used to start this harness.

        Third-party adapters normally use PATH or an explicit executable. Pi
        overrides this hook to provision OpenList-Ani's managed runtime.
        """

        del config_path
        return executable or self.default_executable

    async def probe(self, executable: str = "") -> AgentStatus:
        try:
            selected = await self.resolve_executable(executable)
        except RuntimeError as error:
            return AgentStatus(
                name=self.name,
                executable=executable or self.default_executable,
                available=False,
                detail=str(error),
            )
        resolved = shutil.which(selected)
        if resolved is None and Path(selected).is_file():
            resolved = str(Path(selected).resolve())
        if resolved is None:
            return AgentStatus(
                name=self.name,
                executable=selected,
                available=False,
                detail=f"Executable '{selected}' was not found.",
            )
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return AgentStatus(
                name=self.name,
                executable=resolved,
                available=False,
                detail=f"Executable could not be started: {error}",
            )
        return AgentStatus(
            name=self.name,
            executable=resolved,
            available=completed.returncode == 0,
            detail=(
                ""
                if completed.returncode == 0
                else "Agent version probe exited with code "
                f"{completed.returncode}: "
                f"{(completed.stderr or completed.stdout).strip()[-500:]}"
            ),
        )

    @abstractmethod
    def open_session(self, spec: SessionSpec) -> "HarnessSession": ...

    @abstractmethod
    async def run_structured(
        self,
        source: "AISourceConfig",
        request: StructuredRequest,
    ) -> str: ...

    def session_arguments(self, spec: SessionSpec) -> list[str]:
        """Return harness-native arguments that expose packaged Skills."""
        del spec
        return []

    async def ensure_native_skills(self, spec: SessionSpec) -> None:
        """Let a harness perform any native plugin setup it requires."""
        del spec

    def prepare_working_directory(
        self, spec: SessionSpec, working_directory: Path
    ) -> None:
        """Expose Skills through harness-native project discovery paths."""
        del spec, working_directory


class PiAgentAdapter(AgentAdapter):
    name = "pi"
    default_executable = "pi"

    def session_arguments(self, spec: SessionSpec) -> list[str]:
        arguments: list[str] = []
        user_root = _existing_directory(spec.user_skills_root)
        if user_root is not None:
            arguments.extend(["--skill", str(user_root)])
        arguments.extend(
            ["--skill", str(_builtin_skills_root(spec.builtin_plugin_root))]
        )
        return arguments

    async def resolve_executable(
        self,
        executable: str = "",
        *,
        config_path: Path | None = None,
    ) -> str:
        from .pi_runtime import ensure_pi_runtime

        return await asyncio.to_thread(
            ensure_pi_runtime,
            configured_executable=executable,
            config_path=config_path,
        )

    def open_session(self, spec: SessionSpec) -> "HarnessSession":
        from .runtime import PiRPCSession

        return PiRPCSession(self, spec)

    async def run_structured(
        self, source: "AISourceConfig", request: StructuredRequest
    ) -> str:
        executable = await self.resolve_executable(source.executable)
        command = [
            executable,
            "--print",
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
        ]
        model = request.model or source.model
        if model:
            command.extend(["--model", model])
        return await _run_structured_process(command, request)


class ClaudeCodeAgentAdapter(AgentAdapter):
    name = "claude-code"
    default_executable = "claude"

    def session_arguments(self, spec: SessionSpec) -> list[str]:
        arguments: list[str] = []
        for plugin_root in _claude_plugin_roots(spec.user_skills_root):
            arguments.extend(["--plugin-dir", str(plugin_root)])
        arguments.extend(["--plugin-dir", str(spec.builtin_plugin_root.resolve())])
        return arguments

    def open_session(self, spec: SessionSpec) -> "HarnessSession":
        from .runtime import ClaudeCodeSession

        return ClaudeCodeSession(self, spec)

    async def run_structured(
        self, source: "AISourceConfig", request: StructuredRequest
    ) -> str:
        command = [
            source.executable or self.default_executable,
            "--print",
            "--output-format",
            "text",
            "--tools",
            "",
            "--permission-mode",
            "plan",
            "--max-turns",
            "1",
        ]
        model = request.model or source.model
        if model:
            command.extend(["--model", model])
        return await _run_structured_process(command, request)


class CodexAgentAdapter(AgentAdapter):
    name = "codex"
    default_executable = "codex"

    def prepare_working_directory(
        self, spec: SessionSpec, working_directory: Path
    ) -> None:
        _prepare_codex_project_skills(
            working_directory,
            builtin_skills_root=_builtin_skills_root(spec.builtin_plugin_root),
            user_skills_root=spec.user_skills_root,
        )

    def open_session(self, spec: SessionSpec) -> "HarnessSession":
        from .runtime import CodexSession

        return CodexSession(self, spec)

    async def run_structured(
        self, source: "AISourceConfig", request: StructuredRequest
    ) -> str:
        descriptor, output_name = tempfile.mkstemp(
            prefix="oani-codex-metadata-", suffix=".txt"
        )
        os.close(descriptor)
        output_path = Path(output_name)
        command = [
            source.executable or self.default_executable,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
        ]
        model = request.model or source.model
        if model:
            command.extend(["--model", model])
        command.append("-")
        try:
            await _run_structured_process(command, request, allow_empty=True)
            result = output_path.read_text(encoding="utf-8").strip()
            if not result:
                raise RuntimeError("Codex returned an empty final message.")
            return result
        finally:
            output_path.unlink(missing_ok=True)


_ADAPTERS: dict[str, AgentAdapter] | None = None


def _load_adapters() -> dict[str, AgentAdapter]:
    adapters: dict[str, AgentAdapter] = {
        item.name: item
        for item in (
            PiAgentAdapter(),
            ClaudeCodeAgentAdapter(),
            CodexAgentAdapter(),
        )
    }
    try:
        discovered = entry_points(group="openlist_ani.agent_adapters")
    except TypeError:  # pragma: no cover - compatibility with old importlib APIs
        discovered = entry_points().get("openlist_ani.agent_adapters", ())
    for item in discovered:
        loaded = item.load()
        adapter = loaded() if inspect.isclass(loaded) else loaded
        if not isinstance(adapter, AgentAdapter):
            raise TypeError(
                f"Agent adapter entry point '{item.name}' did not return AgentAdapter."
            )
        if adapter.name in adapters:
            raise ValueError(f"Agent adapter already registered: {adapter.name}")
        adapters[adapter.name] = adapter
    return adapters


def _existing_directory(path: Path | None) -> Path | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    return resolved if resolved.is_dir() else None


def _builtin_skills_root(plugin_root: Path) -> Path:
    skills_root = plugin_root.resolve() / "skills"
    if not skills_root.is_dir():
        raise RuntimeError(
            f"Packaged Agent Skills are missing from '{skills_root}'. "
            "Reinstall OpenList-Ani."
        )
    return skills_root


def _claude_plugin_roots(user_skills_root: Path | None) -> tuple[Path, ...]:
    """Translate the legacy raw skills_dir into Claude-native plugin roots.

    Current Claude Code accepts a root-level SKILL.md as a single-Skill plugin.
    A directory already using plugin layout is passed through unchanged; an old
    directory containing multiple Skill folders is passed as repeated
    --plugin-dir arguments without copying or parsing any SKILL.md.
    """
    root = _existing_directory(user_skills_root)
    if root is None:
        return ()
    if (
        (root / ".claude-plugin" / "plugin.json").is_file()
        or (root / "SKILL.md").is_file()
        or (root / "skills").is_dir()
    ):
        return (root,)
    return tuple(
        child.resolve()
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    )


def _prepare_codex_project_skills(
    working_directory: Path,
    *,
    builtin_skills_root: Path,
    user_skills_root: Path | None,
) -> Path:
    """Link Skills into Codex's documented project-local discovery directory.

    Codex has no transient arbitrary Skill-directory flag. It discovers project
    Skills from ``$CWD/.agents/skills``, so each isolated Assistant session gets
    a link-only projection there. No Skill content is copied or loaded by OAni.
    """

    skills: dict[str, Path] = {
        path.name: path for path in _skill_directories(builtin_skills_root)
    }
    user_root = _existing_directory(user_skills_root)
    if user_root is not None:
        for path in _skill_directories(user_root):
            skills[path.name] = path

    destination = working_directory / ".agents" / "skills"
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in sorted(skills.items()):
        _link_skill_directory(source, destination / name)
    return destination


def _skill_directories(root: Path) -> tuple[Path, ...]:
    resolved = root.expanduser().resolve()
    if (resolved / "SKILL.md").is_file():
        return (resolved,)
    plugin_skills = resolved / "skills"
    if plugin_skills.is_dir():
        resolved = plugin_skills
    return tuple(
        child.resolve()
        for child in sorted(resolved.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    )


def _link_skill_directory(source: Path, destination: Path) -> None:
    try:
        destination.symlink_to(source, target_is_directory=True)
        return
    except OSError as error:
        if os.name != "nt":
            raise RuntimeError(
                f"Could not expose Agent Skill '{source.name}' to Codex: {error}"
            ) from error

    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(destination), str(source)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"Could not expose Agent Skill '{source.name}' to Codex: "
            f"{detail[-500:] or 'directory link creation failed'}"
        )


def agent_adapters() -> dict[str, AgentAdapter]:
    global _ADAPTERS
    if _ADAPTERS is None:
        _ADAPTERS = _load_adapters()
    return dict(_ADAPTERS)


def agent_adapter_names() -> tuple[str, ...]:
    return tuple(agent_adapters())


def get_agent_adapter(name: str) -> AgentAdapter:
    key = name.strip().lower()
    try:
        return agent_adapters()[key]
    except KeyError as error:
        available = ", ".join(agent_adapter_names()) or "<none>"
        raise ValueError(
            f"Unknown agent adapter '{name}'. Available agents: {available}."
        ) from error


async def _run_structured_process(
    command: list[str],
    request: StructuredRequest,
    *,
    allow_empty: bool = False,
) -> str:
    with tempfile.TemporaryDirectory(prefix="oani-metadata-") as working_dir:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise RuntimeError(
                f"Agent executable '{command[0]}' could not be started. Install it, "
                "check its execute permission, or configure executable in "
                "[ai.sources.<name>]."
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request.prompt.encode("utf-8")),
                timeout=request.timeout,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"Agent process timed out after {request.timeout:.0f} seconds."
            ) from error
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Agent process exited with code {process.returncode}: "
            f"{detail[-1000:] or 'no diagnostic output'}"
        )
    result = stdout.decode("utf-8", errors="replace").strip()
    if not result and not allow_empty:
        raise RuntimeError("Agent returned an empty response.")
    return result


__all__ = [
    "AgentAdapter",
    "AgentStatus",
    "SessionSpec",
    "StructuredRequest",
    "agent_adapter_names",
    "agent_adapters",
    "get_agent_adapter",
]
