"""Gating tests for OpenList startup validation."""

from unittest.mock import AsyncMock

import pytest

from openlist_ani.adapters.download_backends.openlist import OpenListHealthCheck


async def _validate(client: AsyncMock, tool: str = "qBittorrent") -> bool:
    return await OpenListHealthCheck(
        client=client,
        base_url="http://localhost:5244",
        offline_download_tool=tool,
    ).validate()


@pytest.mark.asyncio
async def test_unhealthy_openlist_blocks_startup():
    client = AsyncMock()
    client.is_healthy.return_value = False

    assert await _validate(client) is False


@pytest.mark.asyncio
async def test_missing_download_tool_blocks_startup():
    client = AsyncMock()
    client.is_healthy.return_value = True
    client.get_offline_download_tools.return_value = ["aria2"]

    assert await _validate(client) is False


@pytest.mark.asyncio
async def test_available_download_tool_allows_startup():
    client = AsyncMock()
    client.is_healthy.return_value = True
    client.get_offline_download_tools.return_value = [
        {"name": "qBittorrent"},
        {"name": "aria2"},
    ]

    assert await _validate(client, "QBittorrent") is True
