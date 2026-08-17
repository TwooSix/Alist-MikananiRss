"""RSS adapter for api.ani.rip feeds."""

from __future__ import annotations

from urllib.parse import urlparse

import aiohttp

from openlist_ani.application.ports import FeedFetchResult
from openlist_ani.domain import ReleaseCandidate, ReleaseMetadata

from .common import fetch_feed


class AniApiFeedAdapter:
    name = "aniapi"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def supports(self, url: str) -> bool:
        return (urlparse(url).hostname or "").endswith("ani.rip")

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult:
        def parse(entry) -> ReleaseCandidate | None:
            title = getattr(entry, "title", None)
            download_url = getattr(entry, "link", None)
            if not title or not download_url:
                return None
            return ReleaseCandidate.create(
                source_name=self.name,
                source_url=url,
                title=title,
                download_url=download_url,
                source_metadata=ReleaseMetadata(fansub="ANi"),
            )

        return await fetch_feed(
            self._session,
            url,
            parse,
            etag=etag,
            last_modified=last_modified,
        )
