"""Tool-free one-shot metadata extraction through registered agent adapters."""

from __future__ import annotations

from openlist_ani.adapters.configuration.models import AISourceConfig
from openlist_ani.assistant.harness.adapters import (
    StructuredRequest,
    get_agent_adapter,
)

from .client import LLMClient, LLM_REQUEST_TIMEOUT


class AgentCommandError(RuntimeError):
    pass


class AgentCommandLLMClient(LLMClient):
    """Expose a registered agent through the metadata LLM interface.

    The adapter starts a new, tool-free process for each request. Assistant
    history, Skills and project context are never shared with Metadata.
    """

    def __init__(
        self,
        source: AISourceConfig,
        *,
        timeout: float = LLM_REQUEST_TIMEOUT,
    ) -> None:
        if source.type != "agent" or not source.agent:
            raise ValueError("AgentCommandLLMClient requires an agent source.")
        self._source = source
        self._timeout = timeout
        self._adapter = get_agent_adapter(source.agent)

    async def complete_chat(
        self, messages: list[dict[str, str]], model: str | None = None
    ) -> str:
        request = StructuredRequest(
            prompt=_flatten_messages(messages),
            model=model or self._source.model,
            timeout=self._timeout,
        )
        try:
            return await self._adapter.run_structured(self._source, request)
        except Exception as error:
            raise AgentCommandError(str(error)) from error


def _flatten_messages(messages: list[dict[str, str]]) -> str:
    sections: list[str] = []
    for message in messages:
        role = message.get("role", "user").strip().upper()
        content = message.get("content", "")
        sections.append(f"<{role}>\n{content}\n</{role}>")
    return (
        "Follow the SYSTEM instructions below. This is an isolated metadata "
        "task: do not inspect files, run commands, use Skills, or use tools.\n\n"
        + "\n\n".join(sections)
    )


__all__ = ["AgentCommandError", "AgentCommandLLMClient"]
