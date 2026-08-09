"""Magnet-link resolver: extract torrent titles and file metadata.

Two-stage flow:

1. Parse the ``dn=`` parameter from the magnet URI.  This is instant and
   covers most well-formed magnets.
2. If ``dn`` is empty / equals the info-hash, fetch the torrent metadata
   via libtorrent (DHT + trackers).  Wrapped in :func:`asyncio.to_thread`
   so the async router stays non-blocking.

"""

from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp

from openlist_ani.logger import logger

# Cap a downloaded .torrent file at 10 MiB — real torrents are a few KiB
# to a few hundred KiB; anything larger is almost certainly a wrong URL
# or a malicious response.
_MAX_TORRENT_BYTES = 10 * 1024 * 1024
_TORRENT_DOWNLOAD_TIMEOUT_SECS = 30.0

# ── Models ───────────────────────────────────────────────────────────


@dataclass
class TorrentFile:
    name: str
    size: int = 0


@dataclass
class ResolveResult:
    """Outcome of :func:`resolve_magnet`.

    ``title`` is ``None`` only when both ``dn`` and metadata fetch fail.
    Callers must NOT fabricate one — they should ask the user instead.
    """

    success: bool
    message: str
    title: str | None = None
    source: str | None = None  # "dn" | "metadata" | None
    file_count: int | None = None
    files: list[TorrentFile] = field(default_factory=list)


# ── Magnet ``dn`` extraction ─────────────────────────────────────────

_MAGNET_HASH_RE = re.compile(r"(?i)urn:btih:([a-z0-9]{32,40})")


def _extract_dn(magnet: str) -> str | None:
    """Return the URL-decoded ``dn=`` parameter, or ``None`` if absent."""
    try:
        parsed = urlparse(magnet)
    except ValueError:
        return None
    if parsed.scheme.lower() != "magnet":
        return None

    # ``parse_qs`` understands magnet's query-style `xt=` / `dn=` syntax
    # because urllib treats the fragment after `?` as a query string.
    qs = parse_qs(parsed.query)
    dn_values = qs.get("dn") or []
    if not dn_values:
        return None

    dn = unquote(dn_values[0]).strip()
    if not dn:
        return None

    # Some clients duplicate the info-hash into ``dn``; that isn't a
    # human-readable title.
    if _MAGNET_HASH_RE.fullmatch(dn):
        return None
    if re.fullmatch(r"[A-Fa-f0-9]{32,40}", dn):
        return None

    return dn


def _is_valid_magnet(magnet: str) -> bool:
    if not magnet or not isinstance(magnet, str):
        return False
    if not magnet.lower().startswith("magnet:?"):
        return False
    return _MAGNET_HASH_RE.search(magnet) is not None


# ── libtorrent metadata fetch ────────────────────────────────────────


_DHT_BOOTSTRAP_ROUTERS: tuple[tuple[str, int], ...] = (
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("dht.libtorrent.org", 25401),
)


def _build_session(lt) -> "object":  # noqa: ANN001 - libtorrent is dynamic
    """Create a libtorrent session pre-configured for metadata fetching."""
    settings = {
        "listen_interfaces": "0.0.0.0:0",
        "enable_dht": True,
        "enable_lsd": True,
        "enable_upnp": True,
        "enable_natpmp": True,
        "alert_mask": (
            lt.alert.category_t.error_notification  # type: ignore[attr-defined]
            | lt.alert.category_t.status_notification  # type: ignore[attr-defined]
        ),
    }
    session = lt.session(settings)
    for host, port in _DHT_BOOTSTRAP_ROUTERS:
        try:
            session.add_dht_router(host, port)
        except Exception:
            pass
    try:
        session.start_dht()
    except Exception:
        pass
    return session


def _force_announce(handle) -> None:  # noqa: ANN001 - dynamic
    """Trigger immediate tracker + DHT announce for ``handle``."""
    try:
        handle.force_reannounce()
        handle.force_dht_announce()
    except Exception:
        pass


def _is_metadata_alert(alert) -> bool:  # noqa: ANN001 - dynamic
    """True iff ``alert`` signals BEP-9 metadata arrival."""
    if type(alert).__name__ == "metadata_received_alert":
        return True
    what = getattr(alert, "what", lambda: "")
    try:
        return what() == "metadata_received"
    except Exception:
        return False


def _wait_for_metadata(session, handle, deadline: float) -> bool:  # noqa: ANN001
    """Block until metadata arrives or ``deadline`` (monotonic) elapses.

    Returns True iff the torrent has metadata at the time of return.
    """
    import time

    while time.monotonic() < deadline:
        if handle.status().has_metadata:
            return True
        remaining = max(0.05, deadline - time.monotonic())
        wait_ms = int(min(1000.0, remaining * 1000))
        session.wait_for_alert(wait_ms)
        for alert in session.pop_alerts():
            if _is_metadata_alert(alert):
                return handle.status().has_metadata
    return handle.status().has_metadata


def _torrent_files(ti) -> list[TorrentFile]:  # noqa: ANN001 - dynamic
    """Enumerate the file list of a libtorrent ``torrent_info``."""
    files: list[TorrentFile] = []
    try:
        file_storage = ti.files()
        for i in range(file_storage.num_files()):
            files.append(
                TorrentFile(
                    name=file_storage.file_path(i),
                    size=int(file_storage.file_size(i)),
                )
            )
    except Exception as e:  # pragma: no cover
        logger.warning(f"libtorrent file listing failed: {e}")
    return files


def _fetch_metadata_blocking(
    magnet: str, deadline_secs: float
) -> tuple[str | None, list[TorrentFile]]:
    """Block until libtorrent fetches metadata or ``deadline_secs`` elapses.

    Runs entirely on the calling thread (callers wrap this with
    :func:`asyncio.to_thread`).  Returns ``(name, files)`` on success,
    ``(None, [])`` on timeout / error.

    Implementation notes:
        - DHT bootstrap routers are added explicitly; without them a cold
          session can spend 30-60 s discovering peers before any tracker
          response arrives.
        - LSD / UPnP / NAT-PMP enabled to maximise the chance of finding
          peers behind common router setups.
        - ``upload_mode`` is intentionally NOT set: in some libtorrent
          versions it suppresses the BEP-9 metadata exchange that we
          actually need.  We never enter the piece-download phase because
          the torrent is removed as soon as metadata arrives.
        - We block on ``session.wait_for_alert`` and look for
          ``metadata_received_alert`` instead of polling
          ``has_metadata``; this returns within milliseconds of arrival
          rather than up to one poll-interval late.
    """
    try:
        import libtorrent as lt  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"libtorrent not available: {e}")
        return None, []

    import time

    with tempfile.TemporaryDirectory(prefix="oani-magnet-") as save_dir:
        session = _build_session(lt)
        params = lt.parse_magnet_uri(magnet)
        params.save_path = save_dir
        # NOTE: do NOT set upload_mode here — see docstring.
        handle = session.add_torrent(params)
        _force_announce(handle)

        deadline = time.monotonic() + max(1.0, float(deadline_secs))
        try:
            if not _wait_for_metadata(session, handle, deadline):
                return None, []
            ti = handle.torrent_file()
            if ti is None:
                return None, []
            return ti.name() or None, _torrent_files(ti)
        finally:
            try:
                session.remove_torrent(handle)
            except Exception:
                pass


# ── Resolver collaborators ───────────────────────────────────────────


class LibtorrentMetadataClient:
    async def fetch_magnet_metadata(
        self, magnet: str, metadata_timeout: float
    ) -> tuple[str | None, list[TorrentFile]]:
        return await asyncio.to_thread(
            _fetch_metadata_blocking, magnet, metadata_timeout
        )

    async def parse_torrent_blob(
        self, blob: bytes
    ) -> tuple[str | None, list[TorrentFile]]:
        return await asyncio.to_thread(_parse_torrent_blob, blob)


class MagnetResolver:
    def __init__(
        self,
        metadata_client: LibtorrentMetadataClient | None = None,
    ) -> None:
        self._metadata_client = metadata_client or LibtorrentMetadataClient()

    async def resolve(
        self, magnet: str, metadata_timeout: float = 30.0
    ) -> ResolveResult:
        if not _is_valid_magnet(magnet):
            return ResolveResult(
                success=False,
                message="Invalid magnet URI (expected 'magnet:?xt=urn:btih:...').",
            )

        dn_title = _extract_dn(magnet)
        if dn_title:
            return ResolveResult(
                success=True,
                message="Resolved title from magnet 'dn=' parameter.",
                title=dn_title,
                source="dn",
            )

        logger.debug(
            f"Fetching torrent metadata via libtorrent (budget={metadata_timeout}s)..."
        )
        try:
            name, files = await self._metadata_client.fetch_magnet_metadata(
                magnet, metadata_timeout
            )
        except Exception as e:
            logger.warning(f"libtorrent metadata fetch failed: {e}")
            return ResolveResult(
                success=False,
                message=(
                    f"Failed to fetch torrent metadata: {e}. "
                    "Provide a .torrent file or supply the title manually."
                ),
            )

        if not name:
            return ResolveResult(
                success=False,
                message=(
                    f"Metadata fetch timed out after {metadata_timeout:.0f}s "
                    "and magnet has no usable 'dn=' parameter. Ask the user "
                    "for the release title; do NOT fabricate one."
                ),
            )

        return ResolveResult(
            success=True,
            message="Resolved title from torrent metadata.",
            title=name,
            source="metadata",
            file_count=len(files),
            files=files,
        )


async def resolve_magnet(magnet: str, metadata_timeout: float = 30.0) -> ResolveResult:
    return await MagnetResolver().resolve(magnet, metadata_timeout)


# ── .torrent file resolver ───────────────────────────────────────────


def _looks_like_torrent_url(url: str) -> bool:
    """Cheap syntactic check for a .torrent URL."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    return bool(parsed.netloc)


async def _download_torrent_bytes(url: str) -> tuple[bytes | None, str | None]:
    """Download a .torrent file via HTTPS.

    Returns ``(bytes, None)`` on success, ``(None, error_msg)`` on
    failure.  Bounded by :data:`_MAX_TORRENT_BYTES` and
    :data:`_TORRENT_DOWNLOAD_TIMEOUT_SECS`.
    """
    timeout = aiohttp.ClientTimeout(total=_TORRENT_DOWNLOAD_TIMEOUT_SECS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return None, (f"HTTP {resp.status} while fetching torrent file.")
                # Stream read with size cap.
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > _MAX_TORRENT_BYTES:
                        return None, (
                            f"Torrent file exceeds {_MAX_TORRENT_BYTES} "
                            "bytes; refusing to read."
                        )
                    chunks.append(chunk)
                return b"".join(chunks), None
    except asyncio.TimeoutError:
        return None, (
            f"Timed out after {_TORRENT_DOWNLOAD_TIMEOUT_SECS:.0f}s "
            "while downloading the .torrent file."
        )
    except aiohttp.ClientError as e:
        return None, f"HTTP client error: {e}"


def _parse_torrent_blob(blob: bytes) -> tuple[str | None, list[TorrentFile]]:
    """Parse a bounded .torrent blob, preferring libtorrent when available.

    Runs on the calling thread; callers should wrap with
    :func:`asyncio.to_thread` when invoked from async code.
    """
    try:
        import libtorrent as lt  # type: ignore[import-not-found]

        ti = lt.torrent_info(blob)
        return ti.name() or None, _torrent_files(ti)
    except Exception as error:  # pragma: no cover - environment dependent
        logger.warning(
            f"libtorrent torrent parsing unavailable; using bounded bencode "
            f"fallback: {error}"
        )
        try:
            return _parse_torrent_blob_python(blob)
        except (TypeError, ValueError) as fallback_error:
            logger.warning(f"Could not parse .torrent blob: {fallback_error}")
            return None, []


_MAX_BENCODE_DEPTH = 32
_MAX_BENCODE_ITEMS = 100_000


class _BencodeDecoder:
    def __init__(self, blob: bytes) -> None:
        if not blob or len(blob) > _MAX_TORRENT_BYTES:
            raise ValueError("torrent payload is empty or exceeds the size limit")
        self._blob = blob
        self._index = 0
        self._items = 0
        self.info_span: tuple[int, int] | None = None

    def decode(self):
        value = self._value(0)
        if self._index != len(self._blob):
            raise ValueError("trailing data after bencode value")
        return value

    def _value(self, depth: int):
        if depth > _MAX_BENCODE_DEPTH:
            raise ValueError("bencode nesting limit exceeded")
        self._items += 1
        if self._items > _MAX_BENCODE_ITEMS:
            raise ValueError("bencode item limit exceeded")
        if self._index >= len(self._blob):
            raise ValueError("unexpected end of bencode data")
        token = self._blob[self._index]
        if token == ord("i"):
            return self._integer()
        if token == ord("l"):
            return self._list(depth)
        if token == ord("d"):
            return self._dict(depth)
        if ord("0") <= token <= ord("9"):
            return self._bytes()
        raise ValueError(f"invalid bencode token at offset {self._index}")

    def _integer(self) -> int:
        self._index += 1
        end = self._blob.find(b"e", self._index)
        if end < 0:
            raise ValueError("unterminated bencode integer")
        raw = self._blob[self._index : end]
        if not raw or raw in {b"-0"} or (raw.startswith(b"0") and len(raw) > 1):
            raise ValueError("invalid bencode integer")
        try:
            value = int(raw)
        except ValueError as error:
            raise ValueError("invalid bencode integer") from error
        self._index = end + 1
        return value

    def _bytes(self) -> bytes:
        separator = self._blob.find(b":", self._index)
        if separator < 0:
            raise ValueError("invalid bencode byte string")
        raw_length = self._blob[self._index : separator]
        if not raw_length or (raw_length.startswith(b"0") and len(raw_length) > 1):
            raise ValueError("invalid bencode byte string length")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValueError("invalid bencode byte string length") from error
        if length < 0 or length > _MAX_TORRENT_BYTES:
            raise ValueError("bencode byte string length exceeds limit")
        start = separator + 1
        end = start + length
        if end > len(self._blob):
            raise ValueError("truncated bencode byte string")
        self._index = end
        return self._blob[start:end]

    def _list(self, depth: int) -> list:
        self._index += 1
        values = []
        while self._peek() != ord("e"):
            values.append(self._value(depth + 1))
        self._index += 1
        return values

    def _dict(self, depth: int) -> dict[bytes, object]:
        self._index += 1
        values: dict[bytes, object] = {}
        previous: bytes | None = None
        while self._peek() != ord("e"):
            key = self._bytes()
            if previous is not None and key <= previous:
                raise ValueError(
                    "bencode dictionary keys are not strictly sorted and unique"
                )
            previous = key
            value_start = self._index
            values[key] = self._value(depth + 1)
            if depth == 0 and key == b"info":
                self.info_span = (value_start, self._index)
        self._index += 1
        return values

    def _peek(self) -> int:
        if self._index >= len(self._blob):
            raise ValueError("unterminated bencode collection")
        return self._blob[self._index]


_TORRENT_NAME_UTF8_KEY = b"name.utf-8"
_TORRENT_NAME_KEY = b"name"


def _parse_torrent_blob_python(blob: bytes) -> tuple[str | None, list[TorrentFile]]:
    root = _BencodeDecoder(blob).decode()
    if not isinstance(root, dict):
        raise ValueError("torrent root must be a dictionary")
    info = root.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("torrent has no info dictionary")
    title = _torrent_name(info)
    if not title:
        raise ValueError("torrent has no usable name")
    return title, _torrent_files(info, title)


def _torrent_name(info: dict[bytes, object]) -> str:
    return _text(info.get(_TORRENT_NAME_UTF8_KEY) or info.get(_TORRENT_NAME_KEY))


def _torrent_files(info: dict[bytes, object], title: str) -> list[TorrentFile]:
    raw_files = info.get(b"files")
    if not isinstance(raw_files, list):
        size = info.get(b"length")
        if not isinstance(size, int) or size < 0:
            raise ValueError("single-file torrent has no valid length")
        return [TorrentFile(name=title, size=size)]
    return [_torrent_file(raw_file) for raw_file in raw_files]


def _torrent_file(raw_file: object) -> TorrentFile:
    if not isinstance(raw_file, dict):
        raise ValueError("torrent file entry must be a dictionary")
    parts = raw_file.get(b"path.utf-8") or raw_file.get(b"path")
    if not isinstance(parts, list):
        raise ValueError("torrent file entry has no path")
    path = "/".join(filter(None, (_text(part) for part in parts)))
    size = raw_file.get(b"length")
    if not path or not isinstance(size, int) or size < 0:
        raise ValueError("torrent file entry is invalid")
    return TorrentFile(name=path, size=size)


def _text(value: object) -> str:
    if not isinstance(value, bytes):
        return ""
    return value.decode("utf-8", errors="replace").strip()


def _torrent_trackers(root: dict[bytes, object]) -> list[str]:
    trackers: list[str] = []

    def add(value: object) -> None:
        tracker = _text(value)
        if tracker and tracker not in trackers:
            trackers.append(tracker)

    announce_list = root.get(b"announce-list")
    if isinstance(announce_list, list):
        for tier in announce_list:
            if isinstance(tier, list):
                for item in tier:
                    add(item)
            else:
                add(tier)
    add(root.get(b"announce"))
    return trackers


def _torrent_web_seeds(root: dict[bytes, object]) -> list[str]:
    raw_web_seeds = root.get(b"url-list")
    values = raw_web_seeds if isinstance(raw_web_seeds, list) else [raw_web_seeds]
    web_seeds: list[str] = []
    for value in values:
        url = _text(value)
        if url and url not in web_seeds:
            web_seeds.append(url)
    return web_seeds


def _validate_torrent_info(info: dict[bytes, object]) -> tuple[bool, bool]:
    meta_version = info.get(b"meta version")
    if meta_version is not None and meta_version != 2:
        raise ValueError(f"unsupported torrent meta version: {meta_version}")
    is_v2 = meta_version == 2

    if not _torrent_name(info):
        raise ValueError("torrent has no usable name")
    piece_length = info.get(b"piece length")
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise ValueError("torrent has no valid piece length")

    if is_v2:
        _validate_v2_info(info, piece_length)

    if b"pieces" in info and not isinstance(info[b"pieces"], bytes):
        raise ValueError("torrent pieces field must be a byte string")
    has_v1 = not is_v2 or isinstance(info.get(b"pieces"), bytes)
    if has_v1:
        _validate_v1_info(info)
    return is_v2, has_v1


def _validate_v2_info(info: dict[bytes, object], piece_length: int) -> None:
    if piece_length < 16 * 1024 or piece_length & (piece_length - 1):
        raise ValueError(
            "v2 torrent piece length must be a power of two and at least 16 KiB"
        )
    if not isinstance(info.get(b"file tree"), dict):
        raise ValueError("v2 torrent has no file tree")


def _validate_v1_info(info: dict[bytes, object]) -> None:
    pieces = info.get(b"pieces")
    if not isinstance(pieces, bytes) or len(pieces) % 20:
        raise ValueError("v1 torrent pieces length must be a multiple of 20")
    single_file = isinstance(info.get(b"length"), int)
    multiple_files = isinstance(info.get(b"files"), list)
    if single_file == multiple_files:
        raise ValueError("v1 torrent must contain exactly one of length or files")
    if single_file and int(info[b"length"]) < 0:
        raise ValueError("v1 torrent length cannot be negative")
    if multiple_files and not info[b"files"]:
        raise ValueError("v1 torrent files list cannot be empty")


def _torrent_blob_to_magnet_python(blob: bytes) -> str:
    """Build a magnet URI from the exact bencoded ``info`` dictionary."""
    decoder = _BencodeDecoder(blob)
    root = decoder.decode()
    if not isinstance(root, dict):
        raise ValueError("torrent root must be a dictionary")
    info = root.get(b"info")
    if not isinstance(info, dict) or decoder.info_span is None:
        raise ValueError("torrent has no info dictionary")

    start, end = decoder.info_span
    encoded_info = blob[start:end]
    is_v2, has_v1 = _validate_torrent_info(info)
    exact_topics: list[str] = []
    if has_v1:
        exact_topics.append(
            # BEP 3 defines the v1 info-hash as SHA-1 over the exact raw info
            # dictionary. It is a content identifier, not a security primitive.
            f"urn:btih:{hashlib.sha1(encoded_info).hexdigest()}"  # NOSONAR
        )
    if is_v2:
        exact_topics.append(f"urn:btmh:1220{hashlib.sha256(encoded_info).hexdigest()}")
    if not exact_topics:
        raise ValueError("torrent info dictionary has no supported hash format")

    parameters: list[tuple[str, str]] = [("xt", item) for item in exact_topics]
    title = _torrent_name(info)
    if title:
        parameters.append(("dn", title))
    parameters.extend(("tr", tracker) for tracker in _torrent_trackers(root))
    parameters.extend(("ws", web_seed) for web_seed in _torrent_web_seeds(root))
    query = "&".join(f"{key}={quote(value, safe=':')}" for key, value in parameters)
    return f"magnet:?{query}"


def _torrent_blob_to_magnet(blob: bytes) -> str:
    """Generate a magnet with libtorrent, falling back when it is unavailable."""
    try:
        import libtorrent as lt  # type: ignore[import-not-found]
    except ImportError:
        return _torrent_blob_to_magnet_python(blob)

    try:
        if load_torrent_buffer := getattr(lt, "load_torrent_buffer", None):
            torrent = load_torrent_buffer(blob)
        else:  # libtorrent 2.0 Python wheels may expose only torrent_info
            torrent = lt.torrent_info(blob)
        magnet = lt.make_magnet_uri(torrent)
    except Exception as error:
        raise ValueError(f"libtorrent rejected the torrent file: {error}") from error
    if not magnet or not magnet.lower().startswith("magnet:?"):
        raise ValueError("libtorrent could not generate a magnet URI")
    return magnet


async def convert_torrent_url_to_magnet(url: str) -> str:
    """Download an HTTP(S) torrent file and convert it to a magnet URI."""
    if not _looks_like_torrent_url(url):
        raise ValueError("expected an HTTP(S) torrent URL")
    blob, error = await _download_torrent_bytes(url)
    if blob is None:
        raise ValueError(error or "could not download torrent file")
    try:
        return await asyncio.to_thread(_torrent_blob_to_magnet, blob)
    except (TypeError, ValueError) as parse_error:
        raise ValueError(
            f"downloaded torrent file is invalid: {parse_error}"
        ) from parse_error


class TorrentFileResolver:
    def __init__(
        self,
        metadata_client: LibtorrentMetadataClient | None = None,
    ) -> None:
        self._metadata_client = metadata_client or LibtorrentMetadataClient()

    async def resolve(self, url: str) -> ResolveResult:
        if not _looks_like_torrent_url(url):
            return ResolveResult(
                success=False,
                message=("Invalid torrent URL (expected 'http(s)://.../*.torrent')."),
            )

        blob, err = await _download_torrent_bytes(url)
        if blob is None:
            return ResolveResult(
                success=False,
                message=(
                    f"Failed to download .torrent: {err}. "
                    "Supply the title manually or pick a working URL."
                ),
            )

        name, files = await self._metadata_client.parse_torrent_blob(blob)
        if not name:
            return ResolveResult(
                success=False,
                message=(
                    "Downloaded the .torrent file but could not parse a "
                    "name from it. Ask the user for the release title; "
                    "do NOT fabricate one."
                ),
            )

        return ResolveResult(
            success=True,
            message="Resolved title from .torrent file metadata.",
            title=name,
            source="torrent_file",
            file_count=len(files),
            files=files,
        )


async def resolve_torrent(url: str) -> ResolveResult:
    return await TorrentFileResolver().resolve(url)
