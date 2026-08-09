import asyncio

import pytest

from openlist_ani.application.feed_scheduler import FeedScheduler
from openlist_ani.application.ports import FeedFetchResult
from openlist_ani.domain import ReleaseCandidate


class _FeedState:
    def __init__(self):
        self.successes = []
        self.failures = []

    async def cache_headers(self, _url):
        return '"old"', "yesterday"

    async def mark_feed_success(self, url, interval, etag, modified):
        self.successes.append((url, interval, etag, modified))

    async def mark_feed_failure(self, url, error):
        self.failures.append((url, error))


class _Jobs:
    def __init__(self):
        self.items = []

    async def add_candidate(self, candidate):
        self.items.append(candidate)
        return object()


class _Adapter:
    name = "test"

    def __init__(self, fail=False):
        self.fail = fail
        self.headers = None

    async def fetch(self, url, *, etag=None, last_modified=None):
        self.headers = (etag, last_modified)
        if self.fail:
            raise TimeoutError("isolated timeout")
        return FeedFetchResult(
            [
                ReleaseCandidate.create(
                    source_name=self.name,
                    source_url=url,
                    title="Example 01",
                    download_url="magnet:example",
                )
            ],
            etag='"new"',
            last_modified="today",
        )


class _Registry:
    def __init__(self, adapters):
        self.adapters = adapters

    def feed_for(self, url):
        return self.adapters[url]


@pytest.mark.asyncio
async def test_feed_cache_headers_and_failures_are_isolated_per_subscription():
    ok_url = "https://ok.test/rss"
    bad_url = "https://bad.test/rss"
    ok = _Adapter()
    bad = _Adapter(fail=True)
    jobs = _Jobs()
    state = _FeedState()
    scheduler = FeedScheduler(
        registry=_Registry({ok_url: ok, bad_url: bad}),
        jobs=jobs,
        feed_state=state,
        get_urls=lambda: [ok_url, bad_url],
        interval_seconds=300,
        jobs_available=asyncio.Event(),
    )

    await asyncio.gather(scheduler._fetch_one(ok_url), scheduler._fetch_one(bad_url))

    assert ok.headers == ('"old"', "yesterday")
    assert len(jobs.items) == 1
    assert state.successes == [(ok_url, 300, '"new"', "today")]
    assert state.failures == [(bad_url, "isolated timeout")]
