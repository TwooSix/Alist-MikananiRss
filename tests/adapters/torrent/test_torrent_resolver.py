"""Gating tests for torrent title resolution and malformed input handling."""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from openlist_ani.adapters.torrent import resolver


def _bencode(value):
    if isinstance(value, int):
        return f"i{value}e".encode()
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        return (
            b"d"
            + b"".join(
                _bencode(key) + _bencode(item) for key, item in sorted(value.items())
            )
            + b"e"
        )
    raise TypeError(type(value))


def test_resolve_result_preserves_legacy_positional_arguments():
    files = [resolver.TorrentFile(name="Show.mkv", size=123)]

    result = resolver.ResolveResult(
        True,
        "Resolved",
        "Show",
        "metadata",
        1,
        files,
    )

    assert result.file_count == 1
    assert result.files == files
    assert result.error_code is None


@pytest.mark.asyncio
async def test_invalid_magnet_is_rejected():
    result = await resolver.resolve_magnet("not a magnet")

    assert result.success is False
    assert result.title is None


@pytest.mark.asyncio
async def test_magnet_display_name_is_kept_while_file_metadata_is_inspected(
    monkeypatch,
):
    monkeypatch.setattr(
        resolver,
        "_fetch_metadata_blocking",
        lambda *_args, **_kwargs: (
            "Different metadata title",
            [
                resolver.TorrentFile(name="Episode 01.mkv", size=100),
                resolver.TorrentFile(name="Episode 02.mkv", size=101),
            ],
        ),
    )
    magnet = (
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        "&dn=My%20Show%20-%2001%20%5B1080p%5D"
    )

    result = await resolver.resolve_magnet(magnet)

    assert result.success is True
    assert result.title == "My Show - 01 [1080p]"
    assert result.source == "dn"
    assert result.file_count == 2
    assert [item.name for item in result.files] == [
        "Episode 01.mkv",
        "Episode 02.mkv",
    ]


@pytest.mark.asyncio
async def test_magnet_display_name_survives_metadata_timeout_with_incomplete_code(
    monkeypatch,
):
    monkeypatch.setattr(
        resolver, "_fetch_metadata_blocking", lambda *_args, **_kwargs: (None, [])
    )
    magnet = (
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        "&dn=My%20Show%20-%2001%20%5B1080p%5D"
    )

    result = await resolver.resolve_magnet(magnet, metadata_timeout=2)

    assert result.success is True
    assert result.title == "My Show - 01 [1080p]"
    assert result.source == "dn"
    assert result.error_code == "metadata_timeout"
    assert result.file_count is None
    assert "collection inspection is incomplete" in result.message


@pytest.mark.asyncio
async def test_missing_file_list_is_reported_as_incomplete_inspection(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "_fetch_metadata_blocking",
        lambda *_args, **_kwargs: ("My Show", []),
    )
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"

    result = await resolver.resolve_magnet(magnet, metadata_timeout=2)

    assert result.success is True
    assert result.title == "My Show"
    assert result.error_code == "file_list_unavailable"
    assert "collection inspection is incomplete" in result.message


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
    assert result.error_code == "metadata_timeout"
    assert "timed out after 2s" in result.message


@pytest.mark.asyncio
async def test_unavailable_libtorrent_is_not_reported_as_timeout(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise resolver.LibtorrentUnavailableError("native import failed")

    monkeypatch.setattr(resolver, "_fetch_metadata_blocking", unavailable)
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"

    result = await resolver.resolve_magnet(magnet, metadata_timeout=2)

    assert result.success is False
    assert result.error_code == "libtorrent_unavailable"
    assert "No tracker, DHT, or peer lookup was attempted" in result.message
    assert "timed out" not in result.message


@pytest.mark.asyncio
async def test_dn_title_survives_unavailable_libtorrent_as_incomplete_inspection(
    monkeypatch,
):
    def unavailable(*_args, **_kwargs):
        raise resolver.LibtorrentUnavailableError("native import failed")

    monkeypatch.setattr(resolver, "_fetch_metadata_blocking", unavailable)
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=My%20Show"

    result = await resolver.resolve_magnet(magnet, metadata_timeout=2)

    assert result.success is True
    assert result.title == "My Show"
    assert result.error_code == "libtorrent_unavailable"
    assert "collection inspection is incomplete" in result.message
    assert "timed out" not in result.message


def test_libtorrent_runtime_imports_and_parses_valid_torrent():
    version = resolver.libtorrent_runtime_version()
    numeric_version = tuple(int(part) for part in version.split(".")[:3])
    assert numeric_version >= (2, 0, 13)

    libtorrent = resolver._load_libtorrent()
    blob = _bencode(
        {
            b"info": {
                b"length": 123,
                b"name": b"Show - 01.mkv",
                b"piece length": 16384,
                b"pieces": b"a" * 20,
            }
        }
    )

    torrent_info = libtorrent.torrent_info(blob)

    assert torrent_info.name() == "Show - 01.mkv"
    assert torrent_info.num_files() == 1
    assert torrent_info.total_size() == 123
    assert resolver._libtorrent_files(torrent_info) == [
        resolver.TorrentFile(name="Show - 01.mkv", size=123)
    ]

    session = libtorrent.session(
        {
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
        }
    )
    params = libtorrent.parse_magnet_uri(
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    )
    assert session is not None
    assert params is not None


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


def test_torrent_blob_is_converted_using_exact_info_hash():
    info = {
        b"length": 123,
        b"name": b"Show - 01.mkv",
        b"piece length": 16384,
        b"pieces": b"a" * 20,
    }
    blob = _bencode(
        {
            b"announce": b"https://tracker.example/announce",
            b"info": info,
        }
    )

    magnet = resolver._torrent_blob_to_magnet_python(blob)

    expected_hash = hashlib.sha1(_bencode(info)).hexdigest()  # noqa: S324
    assert f"xt=urn:btih:{expected_hash}" in magnet
    assert "dn=Show%20-%2001.mkv" in magnet
    assert "tr=https:%2F%2Ftracker.example%2Fannounce" in magnet


def test_libtorrent_conversion_preserves_display_name():
    info = {
        b"length": 123,
        b"name": "动画 - 01.mkv".encode(),
        b"piece length": 16384,
        b"pieces": b"a" * 20,
    }

    magnet = resolver._torrent_blob_to_magnet(_bencode({b"info": info}))

    assert "dn=%e5%8a%a8%e7%94%bb%20-%2001.mkv" in magnet.lower()


def test_v2_and_hybrid_torrent_hashes_follow_magnet_specification():
    file_tree = {
        b"Show.mkv": {
            b"": {
                b"length": 123,
                b"pieces root": b"b" * 32,
            }
        }
    }
    v2_info = {
        b"file tree": file_tree,
        b"meta version": 2,
        b"name": b"Show.mkv",
        b"piece length": 16384,
    }
    hybrid_info = {
        **v2_info,
        b"length": 123,
        b"pieces": b"a" * 20,
    }

    v2_magnet = resolver._torrent_blob_to_magnet_python(_bencode({b"info": v2_info}))
    hybrid_magnet = resolver._torrent_blob_to_magnet_python(
        _bencode({b"info": hybrid_info})
    )

    v2_hash = hashlib.sha256(_bencode(v2_info)).hexdigest()
    hybrid_v1_hash = hashlib.sha1(_bencode(hybrid_info)).hexdigest()  # noqa: S324
    hybrid_v2_hash = hashlib.sha256(_bencode(hybrid_info)).hexdigest()
    assert f"xt=urn:btmh:1220{v2_hash}" in v2_magnet
    assert f"xt=urn:btih:{hybrid_v1_hash}" in hybrid_magnet
    assert f"xt=urn:btmh:1220{hybrid_v2_hash}" in hybrid_magnet


def test_web_seeds_are_preserved_in_generated_magnet():
    info = {
        b"length": 123,
        b"name": b"Show.mkv",
        b"piece length": 16384,
        b"pieces": b"a" * 20,
    }
    blob = _bencode(
        {
            b"info": info,
            b"url-list": [b"https://seed.example/Show.mkv"],
        }
    )

    magnet = resolver._torrent_blob_to_magnet_python(blob)

    assert "ws=https:%2F%2Fseed.example%2FShow.mkv" in magnet


def test_duplicate_bencode_keys_are_rejected_before_hashing():
    info = _bencode(
        {
            b"length": 123,
            b"name": b"Show.mkv",
            b"piece length": 16384,
            b"pieces": b"a" * 20,
        }
    )
    blob = b"d4:info" + info + b"4:info" + info + b"e"

    with pytest.raises(ValueError, match="strictly sorted and unique"):
        resolver._torrent_blob_to_magnet_python(blob)


def test_incomplete_v1_torrent_is_rejected_before_hashing():
    info = {
        b"length": 123,
        b"name": b"Show.mkv",
        b"piece length": 16384,
    }

    blob = _bencode({b"info": info})
    with pytest.raises(ValueError, match="pieces length"):
        resolver._torrent_blob_to_magnet_python(blob)


async def test_torrent_url_is_downloaded_and_converted(monkeypatch):
    info = {
        b"length": 123,
        b"name": b"Show.mkv",
        b"piece length": 16384,
        b"pieces": b"a" * 20,
    }
    blob = _bencode({b"info": info})

    async def fake_download(url):
        assert url == "https://example.invalid/show.torrent"
        return blob, None

    monkeypatch.setattr(resolver, "_download_torrent_bytes", fake_download)

    magnet = await resolver.convert_torrent_url_to_magnet(
        "https://example.invalid/show.torrent"
    )

    assert magnet.startswith("magnet:?xt=urn:btih:")


async def test_invalid_downloaded_torrent_cannot_be_converted(monkeypatch):
    async def fake_download(_url):
        return b"not-bencoded", None

    monkeypatch.setattr(resolver, "_download_torrent_bytes", fake_download)

    with pytest.raises(ValueError, match="downloaded torrent file is invalid"):
        await resolver.convert_torrent_url_to_magnet(
            "https://example.invalid/show.torrent"
        )


def test_bounded_fallback_rejects_excessive_nesting():
    blob = b"d4:info" + b"l" * 34 + b"e" * 34 + b"e"

    with pytest.raises(ValueError, match="nesting limit"):
        resolver._parse_torrent_blob_python(blob)
