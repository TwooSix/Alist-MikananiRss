"""Generic RSS adapter and shared bounded feed parsing helpers."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp
import feedparser

from openlist_ani.application.ports import FeedFetchResult
from openlist_ani.domain import ReleaseCandidate
from openlist_ani.logger import logger

EntryParser = Callable[
    [object], ReleaseCandidate | None | Awaitable[ReleaseCandidate | None]
]


async def fetch_feed(
    session: aiohttp.ClientSession,
    url: str,
    parser: EntryParser,
    *,
    etag: str | None,
    last_modified: str | None,
    concurrency: int | None = None,
) -> FeedFetchResult:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    async with session.get(url, headers=headers) as response:
        if response.status == 304:
            return FeedFetchResult(
                candidates=[],
                etag=etag,
                last_modified=last_modified,
                not_modified=True,
            )
        response.raise_for_status()
        document = feedparser.parse(await response.text())
        candidates = await _parse_entries(
            list(document.entries[:2000]), parser, concurrency
        )
        return FeedFetchResult(
            candidates=candidates,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )


async def _parse_entries(
    entries: list[object], parser: EntryParser, concurrency: int | None
) -> list[ReleaseCandidate]:
    semaphore = asyncio.Semaphore(concurrency) if concurrency else None
    candidates: list[ReleaseCandidate] = []
    for offset in range(0, len(entries), 200):
        results = await asyncio.gather(
            *(
                _parse_entry(item, parser, semaphore)
                for item in entries[offset : offset + 200]
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Failed to parse RSS entry: {result}")
            elif result is not None:
                candidates.append(result)
    return candidates


async def _parse_entry(
    entry: object,
    parser: EntryParser,
    semaphore: asyncio.Semaphore | None,
) -> ReleaseCandidate | None:
    if semaphore is None:
        return await _resolve_entry(parser(entry))
    async with semaphore:
        return await _resolve_entry(parser(entry))


async def _resolve_entry(
    result: ReleaseCandidate | None | Awaitable[ReleaseCandidate | None],
) -> ReleaseCandidate | None:
    return await result if inspect.isawaitable(result) else result


def torrent_url(entry) -> str | None:
    for enclosure in entry.get("enclosures", []):
        href = enclosure.get("href", "")
        if (
            href.startswith("magnet:")
            or urlparse(href).path.endswith(".torrent")
            or enclosure.get("type") == "application/x-bittorrent"
        ):
            return href
    link = getattr(entry, "link", "")
    if link and (
        link.startswith("magnet:") or urlparse(link).path.endswith(".torrent")
    ):
        return link
    return None


class CommonFeedAdapter:
    name = "common"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def supports(self, url: str) -> bool:
        return bool(urlparse(url).scheme in {"http", "https"})

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult:
        def parse(entry) -> ReleaseCandidate | None:
            title = getattr(entry, "title", None)
            download_url = torrent_url(entry)
            if not title or not download_url:
                return None
            return ReleaseCandidate.create(
                source_name=self.name,
                source_url=url,
                title=title,
                download_url=download_url,
            )

        return await fetch_feed(
            self._session,
            url,
            parse,
            etag=etag,
            last_modified=last_modified,
        )
