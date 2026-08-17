"""Independent, failure-isolated RSS scheduling."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from openlist_ani.application.ports import (
    FeedResolver,
    FeedStateRepository,
    JobRepository,
)
from openlist_ani.logger import logger


@dataclass(frozen=True)
class _FeedScanResult:
    observed: int = 0
    queued: int = 0
    failed: bool = False


class FeedScheduler:
    def __init__(
        self,
        *,
        registry: FeedResolver,
        jobs: JobRepository,
        feed_state: FeedStateRepository,
        get_urls: Callable[[], list[str]],
        interval_seconds: float,
        concurrency: int = 4,
        jobs_available: asyncio.Event | None = None,
    ) -> None:
        self._registry = registry
        self._jobs = jobs
        self._feed_state = feed_state
        self._get_urls = get_urls
        self._interval_seconds = interval_seconds
        feed_concurrency = max(1, concurrency)
        self._semaphore = asyncio.Semaphore(feed_concurrency)
        self._batch_size = feed_concurrency * 4
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._jobs_available = jobs_available or asyncio.Event()
        self._synced_urls: tuple[str, ...] | None = None

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:  # NOSONAR - awaitable lifecycle contract
        self._stop.set()
        self._wake.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                urls = list(dict.fromkeys(self._get_urls()))
                normalized_urls = tuple(urls)
                if normalized_urls != self._synced_urls:
                    await self._feed_state.sync_urls(urls)
                    self._synced_urls = normalized_urls
                due = await self._feed_state.list_due(self._batch_size)
                if due:
                    logger.info(f"RSS scan started: {len(due)} source(s)")
                    results = await asyncio.gather(
                        *(self._fetch_one(url) for url in due)
                    )
                    observed = sum(result.observed for result in results)
                    queued = sum(result.queued for result in results)
                    failed = sum(result.failed for result in results)
                    logger.info(
                        "RSS scan completed: "
                        f"sources={len(due)}, observed={observed}, queued={queued}, "
                        f"failed={failed}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(f"Feed scheduler recovered from error: {error}")
            await self._wait_for_wake()

    async def _fetch_one(self, url: str) -> _FeedScanResult:
        async with self._semaphore:
            try:
                adapter = self._registry.feed_for(url)
                etag, last_modified = await self._feed_state.cache_headers(url)
                result = await adapter.fetch(
                    url,
                    etag=etag,
                    last_modified=last_modified,
                )
                inserted = 0
                for candidate in result.candidates:
                    if await self._jobs.add_candidate(candidate) is not None:
                        inserted += 1
                await self._feed_state.mark_feed_success(
                    url,
                    self._interval_seconds,
                    result.etag,
                    result.last_modified,
                )
                if inserted:
                    self._jobs_available.set()
                logger.info(
                    f"RSS scan completed: source={adapter.name}, "
                    f"observed={len(result.candidates)}, queued={inserted}, "
                    f"not_modified={result.not_modified}"
                )
                return _FeedScanResult(
                    observed=len(result.candidates),
                    queued=inserted,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._feed_state.mark_feed_failure(url, str(error))
                logger.warning(f"RSS source failed; source={url}; error={error}")
                return _FeedScanResult(failed=True)

    async def _wait_for_wake(self) -> None:
        self._wake.clear()
        try:
            async with asyncio.timeout(5.0):
                await self._wake.wait()
        except TimeoutError:
            pass
