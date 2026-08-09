from __future__ import annotations

import json
from pathlib import Path

import pytest

from openlist_ani.adapters.configuration.models import AISourceConfig
from openlist_ani.assistant.contracts import EventType, LoopEvent
from openlist_ani.assistant.harness.adapters import (
    CodexAgentAdapter,
    SessionSpec,
    agent_adapter_names,
    get_agent_adapter,
)
from openlist_ani.assistant.harness.runtime import (
    ClaudeCodeSession,
    CodexSession,
    PiRPCSession,
    _claude_stream_events,
    _codex_payload_events,
    _last_assistant_text,
    _map_pi_message_event,
    _split_confirmation,
    create_harness_session,
)


def _plugin(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    root = plugin / "skills"
    skill = root / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\n# secret body\n",
        encoding="utf-8",
    )
    return plugin


def _session(source, tmp_path: Path):
    plugin = _plugin(tmp_path)
    return create_harness_session(
        source,
        builtin_plugin_root=plugin,
        user_skills_root=None,
        config_path=tmp_path / "config.toml",
    )


def test_builtin_agent_adapters_are_registered():
    assert set(agent_adapter_names()) >= {"pi", "claude-code", "codex"}


@pytest.mark.asyncio
async def test_agent_probe_reports_missing_executable():
    status = await get_agent_adapter("pi").probe("definitely-missing-oani-agent")

    assert status.available is False
    assert "not found" in status.detail


@pytest.mark.asyncio
async def test_pi_probe_uses_managed_runtime_resolver(tmp_path: Path, monkeypatch):
    executable = tmp_path / "pi"
    executable.write_text("", encoding="utf-8")
    adapter = get_agent_adapter("pi")

    async def resolved(_executable="", *, config_path=None):
        return str(executable)

    class Result:
        returncode = 0
        stderr = ""
        stdout = "0.82.1"

    monkeypatch.setattr(adapter, "resolve_executable", resolved)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())

    status = await adapter.probe()

    assert status.available is True
    assert status.executable == str(executable.resolve())


def test_api_source_is_always_wrapped_by_pi(tmp_path: Path):
    source = AISourceConfig(
        type="api",
        provider="openai-compatible",
        api_key="key",
        model="model",
    )
    session = _session(source, tmp_path)
    assert isinstance(session, PiRPCSession)


def test_native_agent_selects_registered_adapter(tmp_path: Path):
    assert isinstance(
        _session(AISourceConfig(type="agent", agent="pi"), tmp_path / "pi"),
        PiRPCSession,
    )
    assert isinstance(
        _session(
            AISourceConfig(type="agent", agent="claude-code"),
            tmp_path / "claude",
        ),
        ClaudeCodeSession,
    )
    assert isinstance(
        _session(AISourceConfig(type="agent", agent="codex"), tmp_path / "codex"),
        CodexSession,
    )


def test_pi_provider_file_contains_selected_api_source(tmp_path: Path):
    source = AISourceConfig(
        type="api",
        provider="anthropic-messages",
        api_key="secret",
        model="claude-model",
        base_url="https://gateway.example",
    )
    spec = SessionSpec(
        source=source,
        builtin_plugin_root=_plugin(tmp_path),
        user_skills_root=None,
        config_path=tmp_path / "config.toml",
    )
    session = PiRPCSession(get_agent_adapter("pi"), spec)

    environment = session._prepare_api_source(source)
    path = Path(environment["PI_CODING_AGENT_DIR"]) / "models.json"
    provider = json.loads(path.read_text(encoding="utf-8"))["providers"]["openlist-ani"]

    assert provider["api"] == "anthropic-messages"
    assert provider["baseUrl"] == "https://gateway.example"
    assert provider["apiKey"] == "secret"
    assert provider["models"][0]["id"] == "claude-model"


def test_pi_project_settings_pin_managed_bash(tmp_path: Path):
    spec = SessionSpec(
        source=AISourceConfig(type="agent", agent="pi"),
        builtin_plugin_root=_plugin(tmp_path),
        user_skills_root=None,
        config_path=tmp_path / "config.toml",
    )
    session = PiRPCSession(get_agent_adapter("pi"), spec)
    shell = tmp_path / "runtime" / "git-bash" / "bin" / "bash.exe"

    path = session._prepare_project_settings(str(shell))

    assert path == session._working_dir / ".pi" / "settings.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "shellPath": str(shell.resolve())
    }


@pytest.mark.asyncio
async def test_claude_uses_native_skills_and_session_resume(
    tmp_path: Path, monkeypatch
):
    session = _session(AISourceConfig(type="agent", agent="claude-code"), tmp_path)
    calls: list[tuple[list[str], str]] = []

    async def fake_stream(command, prompt):
        calls.append((command, prompt))
        yield {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "reply"},
            },
        }
        yield {"type": "result", "result": "reply"}

    monkeypatch.setattr(session, "_stream_json_process", fake_stream)
    first = [event async for event in session.stream("first")]
    second = [event async for event in session.stream("second")]

    first_id = calls[0][0][calls[0][0].index("--session-id") + 1]
    assert calls[1][0][calls[1][0].index("--resume") + 1] == first_id
    assert calls[0][0][calls[0][0].index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--permission-mode") + 1] == "auto"
    assert "--tools" not in calls[0][0]
    assert "--mcp-config" not in calls[0][0]
    plugin_arg = calls[0][0][calls[0][0].index("--plugin-dir") + 1]
    assert Path(plugin_arg) == session._spec.builtin_plugin_root.resolve()
    assert not (session._working_dir / ".claude").exists()
    assert "secret body" not in calls[0][1]
    assert first[-1].type == EventType.DONE
    assert second[-1].text == "reply"
    await session.close()


@pytest.mark.asyncio
async def test_claude_prefers_harness_final_over_intermediate_narration(
    tmp_path: Path, monkeypatch
):
    session = _session(AISourceConfig(type="agent", agent="claude-code"), tmp_path)

    async def fake_stream(_command, _prompt):
        yield {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {
                    "type": "text_delta",
                    "text": "我先查询一下，然后继续执行工具。",
                },
            },
        }
        yield {"type": "result", "result": "这是最终整理后的答案。"}

    monkeypatch.setattr(session, "_stream_json_process", fake_stream)
    events = [event async for event in session.stream("test")]

    assert events[-1] == LoopEvent(EventType.DONE, "这是最终整理后的答案。")
    await session.close()


def test_pi_final_text_uses_last_nonempty_assistant_message():
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "我先查询一下。"}],
        },
        {"role": "toolResult", "content": [{"type": "text", "text": "result"}]},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "最终整理后的答案。"}],
        },
        {"role": "assistant", "content": [{"type": "toolCall"}]},
    ]

    assert _last_assistant_text(messages) == "最终整理后的答案。"


def test_pi_tool_events_preserve_actual_skill_and_safe_arguments():
    runs = {}
    started = _map_pi_message_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "call-1",
            "toolName": "bash",
            "args": {
                "command": (
                    "python bangumi/scripts/search.py "
                    '--json \'{"keyword":"尖帽子的魔法工房",'
                    '"token":"secret"}\''
                )
            },
        },
        runs,
    )
    finished = _map_pi_message_event(
        {
            "type": "tool_execution_end",
            "toolCallId": "call-1",
            "toolName": "bash",
            "isError": False,
        },
        runs,
    )

    assert started is not None
    assert started.type == EventType.SCRIPT_STARTED
    assert "Skill bangumi / search" in started.text
    assert "keyword=尖帽子的魔法工房" in started.text
    assert "secret" not in started.text
    assert finished is not None
    assert finished.type == EventType.SCRIPT_FINISHED
    assert "Skill bangumi / search" in finished.text
    assert finished.data["success"] is True


def test_pi_tool_label_infers_skill_from_windows_working_directory():
    event = _map_pi_message_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "call-1",
            "toolName": "bash",
            "args": {
                "command": (
                    'cd "D:\\app\\skills\\bangumi" && '
                    "python scripts/latest_episode.py "
                    "--json '{\"subject_id\":377130}'"
                )
            },
        }
    )

    assert event is not None
    assert event.text == ("执行 Skill bangumi / latest episode · subject_id=377130")
    assert "D:\\app" not in event.text


def test_native_jsonl_events_map_to_frontend_progress():
    claude = _claude_stream_events(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello"},
            },
        }
    )
    codex = _codex_payload_events(
        {
            "type": "item.started",
            "item": {
                "type": "command_execution",
                "command": "python demo/scripts/search.py --json '{}'",
            },
        }
    )

    assert claude == [LoopEvent(EventType.TEXT_DELTA, "hello")]
    assert codex[0].type == EventType.SCRIPT_STARTED
    assert codex[0].text == "执行 Skill demo / search"


def test_confirmation_marker_becomes_protocol_event_without_leaking_marker():
    response, required = _split_confirmation(
        "I will create one download. [[CONFIRMATION_REQUIRED]]"
    )

    assert response == "I will create one download."
    assert required is True


@pytest.mark.asyncio
async def test_codex_uses_native_thread_without_mcp_or_sandbox(
    tmp_path: Path, monkeypatch
):
    session = _session(AISourceConfig(type="agent", agent="codex"), tmp_path)
    calls: list[tuple[list[str], str]] = []

    async def fake_stream(command, prompt):
        calls.append((command, prompt))
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("reply", encoding="utf-8")
        yield {"type": "thread.started", "thread_id": "thread-123"}

    native_setup: list[SessionSpec] = []

    async def fake_native_setup(spec):
        native_setup.append(spec)

    monkeypatch.setattr(session, "_stream_json_process", fake_stream)
    monkeypatch.setattr(session._adapter, "ensure_native_skills", fake_native_setup)
    await _collect(session.stream("first"))
    await _collect(session.stream("second"))

    resume_index = calls[1][0].index("resume")
    assert calls[1][0][resume_index] == "resume"
    assert calls[1][0][-2:] == ["thread-123", "-"]
    assert "--dangerously-bypass-approvals-and-sandbox" in calls[0][0]
    assert "--sandbox" not in calls[0][0]
    assert all("mcp" not in item for item in calls[0][0])
    assert native_setup == [session._spec, session._spec]
    projected_skill = session._working_dir / ".agents" / "skills" / "demo"
    assert projected_skill.is_dir()
    assert projected_skill.samefile(session._spec.builtin_plugin_root / "skills" / "demo")
    await session.close()


def test_codex_projects_builtin_and_user_skills_with_user_override(
    tmp_path: Path,
):
    plugin = _plugin(tmp_path)
    user_root = tmp_path / "user-skills"
    user_demo = user_root / "demo"
    user_extra = user_root / "extra"
    user_demo.mkdir(parents=True)
    user_extra.mkdir(parents=True)
    (user_demo / "SKILL.md").write_text(
        "---\nname: demo\ndescription: user override\n---\n", encoding="utf-8"
    )
    (user_extra / "SKILL.md").write_text(
        "---\nname: extra\ndescription: extra\n---\n", encoding="utf-8"
    )
    adapter = CodexAgentAdapter()
    source = AISourceConfig(type="agent", agent="codex", executable="codex-test")
    spec = SessionSpec(
        source=source,
        builtin_plugin_root=plugin,
        user_skills_root=user_root,
        config_path=tmp_path / "config.toml",
    )
    working_directory = tmp_path / "session"
    working_directory.mkdir()

    adapter.prepare_working_directory(spec, working_directory)

    projected = working_directory / ".agents" / "skills"
    assert (projected / "demo").samefile(user_demo)
    assert (projected / "extra").samefile(user_extra)


def test_pi_and_claude_receive_skill_paths_without_projection(tmp_path: Path):
    plugin = _plugin(tmp_path)
    user_root = tmp_path / "user-skills"
    user_skill = user_root / "custom"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text(
        "---\nname: custom\ndescription: custom\n---\n", encoding="utf-8"
    )
    spec = SessionSpec(
        source=AISourceConfig(type="agent", agent="pi"),
        builtin_plugin_root=plugin,
        user_skills_root=user_root,
        config_path=tmp_path / "config.toml",
    )

    pi_args = get_agent_adapter("pi").session_arguments(spec)
    claude_args = get_agent_adapter("claude-code").session_arguments(spec)

    assert pi_args == [
        "--skill",
        str(user_root.resolve()),
        "--skill",
        str((plugin / "skills").resolve()),
    ]
    assert claude_args == [
        "--plugin-dir",
        str(user_skill.resolve()),
        "--plugin-dir",
        str(plugin.resolve()),
    ]


async def _collect(events):
    return [event async for event in events]
