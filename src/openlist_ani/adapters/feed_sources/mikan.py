"""Mikan RSS adapter with bounded detail-page enrichment."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from openlist_ani.application.ports import FeedFetchResult
from openlist_ani.domain import ReleaseCandidate, ReleaseMetadata

from .common import fetch_feed, torrent_url

_CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_SEASON_TOKEN = re.compile(r"(?:第)?([一二三四五六七八九十0-9]+)\s*(?:季|部分|部)")


class MikanFeedAdapter:
    name = "mikan"
    _DOMAINS = {"mikanani.me", "mikanime.tv"}

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def supports(self, url: str) -> bool:
        domain = urlparse(url).hostname or ""
        return any(
            domain == item or domain.endswith(f".{item}") for item in self._DOMAINS
        )

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult:
        async def parse(entry) -> ReleaseCandidate | None:
            title = getattr(entry, "title", None)
            download_url = torrent_url(entry)
            detail_url = getattr(entry, "link", "")
            if not title or not download_url or not detail_url:
                return None
            metadata = await self._metadata(detail_url)
            return ReleaseCandidate.create(
                source_name=self.name,
                source_url=url,
                title=title,
                download_url=download_url,
                source_metadata=metadata,
            )

        return await fetch_feed(
            self._session,
            url,
            parse,
            etag=etag,
            last_modified=last_modified,
            concurrency=5,
        )

    async def _metadata(self, url: str) -> ReleaseMetadata:
        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    return ReleaseMetadata()
                soup = BeautifulSoup(await response.text(), "lxml")
        except (aiohttp.ClientError, TimeoutError):
            return ReleaseMetadata()
        anime_name = None
        season = None
        if title := soup.select_one("p.bangumi-title > a.w-other-c"):
            anime_name, season = _split_season(title.get_text(strip=True))
        fansub = None
        if info := soup.select_one("p.bangumi-info"):
            if element := info.select_one("a.magnet-link-wrap"):
                fansub = element.get_text(strip=True)
        return ReleaseMetadata(anime_name=anime_name, season=season, fansub=fansub)


def _split_season(value: str) -> tuple[str, int]:
    normalized = re.sub(r"[ \t\u3000]+", " ", value).strip()
    matches = list(_SEASON_TOKEN.finditer(normalized))
    if not matches:
        return normalized, 1
    match = matches[-1]
    return (
        normalized[: match.start()].strip() or normalized,
        _parse_season_number(match.group(1)),
    )


def _parse_season_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + _CN_NUMBERS.get(value[1:], 0)
    if value.endswith("十"):
        return _CN_NUMBERS.get(value[:-1], 1) * 10
    if "十" in value:
        tens, ones = value.split("十", 1)
        return _CN_NUMBERS.get(tens, 0) * 10 + _CN_NUMBERS.get(ones, 0)
    return _CN_NUMBERS.get(value, 1)
