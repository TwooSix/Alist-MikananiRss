"""Magnet-link resolution helpers (libtorrent-backed)."""

from .candidate_transformer import TorrentToMagnetCandidateTransformer
from .resolver import (
    convert_torrent_url_to_magnet,
    LibtorrentUnavailableError,
    LibtorrentMetadataClient,
    libtorrent_runtime_version,
    MagnetResolver,
    ResolveResult,
    TorrentFile,
    TorrentFileResolver,
    resolve_magnet,
    resolve_torrent,
)

__all__ = [
    "convert_torrent_url_to_magnet",
    "LibtorrentUnavailableError",
    "LibtorrentMetadataClient",
    "libtorrent_runtime_version",
    "MagnetResolver",
    "ResolveResult",
    "TorrentFile",
    "TorrentFileResolver",
    "TorrentToMagnetCandidateTransformer",
    "resolve_magnet",
    "resolve_torrent",
]
