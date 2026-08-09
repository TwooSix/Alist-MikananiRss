"""Gating tests for torrent title resolution and malformed input handling."""

from __future__ import annotations

import asyncio

import pytest

from openlist_ani.adapters.torrent import resolver


@pytest.mark.asyncio
async def test_invalid_magnet_is_rejected():
    result = await resolver.resolve_magnet("not a magnet")

    assert result.success is False
    assert result.title is None


@pytest.mark.asyncio
async def test_magnet_display_name_is_used_without_fetching_metadata(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "_fetch_metadata_blocking",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    magnet = (
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        "&dn=My%20Show%20-%2001%20%5B1080p%5D"
    )

    result = await resolver.resolve_magnet(magnet)

    assert result.success is True
    assert result.title == "My Show - 01 [1080p]"
    assert result.source == "dn"


@pytest.mark.asyncio
async def test_metadata_is_used_when_magnet_has_no_display_name(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "_fetch_metadata_blocking",
        lambda *_args, **_kwargs: (
            "Show - 02 [WebRip]",
            [resolver.TorrentFile(name="Show - 02.mkv", size=123)],
        ),
    )
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"

    result = await resolver.resolve_magnet(magnet)

    assert result.success is True
    assert result.title == "Show - 02 [WebRip]"
    assert result.source == "metadata"


@pytest.mark.asyncio
async def test_missing_magnet_metadata_returns_a_failure(monkeypatch):
    monkeypatch.setattr(
        resolver, "_fetch_metadata_blocking", lambda *_args, **_kwargs: (None, [])
    )
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"

    result = await resolver.resolve_magnet(magnet, metadata_timeout=2)

    assert result.success is False
    assert result.message


class FakeTorrentMetadataClient:
    async def parse_torrent_blob(self, blob):
        await asyncio.sleep(0)
        return "Show Complete BDRip", [resolver.TorrentFile(name="Show.mkv")]


@pytest.mark.asyncio
async def test_torrent_file_url_is_resolved(monkeypatch):
    async def fake_download(url):
        await asyncio.sleep(0)
        return b"torrent-bytes", None

    monkeypatch.setattr(resolver, "_download_torrent_bytes", fake_download)
    service = resolver.TorrentFileResolver(metadata_client=FakeTorrentMetadataClient())

    result = await service.resolve("https://example.invalid/show.torrent")

    assert result.success is True
    assert result.title == "Show Complete BDRip"
    assert result.source == "torrent_file"


def test_bounded_fallback_rejects_excessive_nesting():
    blob = b"d4:info" + b"l" * 34 + b"e" * 34 + b"e"

    with pytest.raises(ValueError, match="nesting limit"):
        resolver._parse_torrent_blob_python(blob)
