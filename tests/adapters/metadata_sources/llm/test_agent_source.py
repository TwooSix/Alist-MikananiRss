from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from openlist_ani.adapters.configuration.models import AISourceConfig
from openlist_ani.adapters.metadata_sources.llm.agent_client import (
    AgentCommandLLMClient,
)
from openlist_ani.adapters.metadata_sources.llm.batch_parser import (
    parse_title_batch_via_llm,
)


@pytest.mark.asyncio
async def test_pi_metadata_session_is_isolated_and_tool_free(monkeypatch):
    source = AISourceConfig(type="agent", agent="pi", executable="custom-pi")
    client = AgentCommandLLMClient(source)
    run = AsyncMock(return_value="[]")
    monkeypatch.setattr(client._adapter, "run_structured", run)

    await client.complete_chat([{"role": "user", "content": "title"}])

    called_source, request = run.await_args.args
    assert called_source.executable == "custom-pi"
    assert "isolated metadata task" in request.prompt
    assert "do not inspect files" in request.prompt


@pytest.mark.asyncio
async def test_invalid_metadata_output_is_repaired_once():
    client = AsyncMock()
    client.complete_chat.side_effect = [
        "not-json",
        '[{"index":1,"status":"success","anime_name":"Example",'
        '"season":1,"episode":2,"quality":"1080p","fansub":"Group",'
        '"languages":["简"],"version":1}]',
    ]

    result = await parse_title_batch_via_llm(client, ["Example 02"])

    assert client.complete_chat.await_count == 2
    assert result[0].success is True
    assert result[0].result.anime_name == "Example"
