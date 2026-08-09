from unittest.mock import AsyncMock

from openlist_ani.adapters.torrent import TorrentToMagnetCandidateTransformer
from openlist_ani.domain import ReleaseCandidate


def _candidate(download_url: str) -> ReleaseCandidate:
    return ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="Example - 01",
        download_url=download_url,
    )


async def test_http_torrent_url_is_replaced_without_changing_source_identity():
    torrent_url = "https://example.test/release.torrent?token=secret"
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    converter = AsyncMock(return_value=magnet)
    transformer = TorrentToMagnetCandidateTransformer(converter)
    candidate = _candidate(torrent_url)

    transformed = await transformer.transform(candidate)

    converter.assert_awaited_once_with(torrent_url)
    assert transformed.download_url == magnet
    assert transformed.source_key == candidate.source_key
    assert candidate.download_url == torrent_url


async def test_existing_magnet_is_left_unchanged():
    magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    converter = AsyncMock()
    transformer = TorrentToMagnetCandidateTransformer(converter)
    candidate = _candidate(magnet)

    transformed = await transformer.transform(candidate)

    assert transformed is candidate
    converter.assert_not_awaited()
