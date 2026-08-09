"""Candidate transformations backed by torrent metadata."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from openlist_ani.domain import ReleaseCandidate
from openlist_ani.logger import logger

from .resolver import convert_torrent_url_to_magnet

TorrentToMagnetConverter = Callable[[str], Awaitable[str]]


class TorrentToMagnetCandidateTransformer:
    """Replace an HTTP(S) torrent URL with its magnet URI."""

    name = "torrent_to_magnet"

    def __init__(self, converter: TorrentToMagnetConverter | None = None) -> None:
        self._converter = converter or convert_torrent_url_to_magnet

    async def transform(self, candidate: ReleaseCandidate) -> ReleaseCandidate:
        download_url = candidate.download_url.strip()
        # HTTP is deliberately accepted because torrent publishers often expose
        # metadata on HTTP-only endpoints; the downloaded bytes are size-limited
        # and validated as bencode before their protocol hash is computed.
        if not download_url.lower().startswith(("http://", "https://")):  # NOSONAR
            return candidate

        magnet = await self._converter(download_url)
        if not magnet.lower().startswith("magnet:?"):
            raise ValueError("torrent converter returned an invalid magnet URI")

        logger.info(
            f"Converted eligible candidate torrent URL to magnet: "
            f"title={candidate.title}"
        )
        return replace(candidate, download_url=magnet)
