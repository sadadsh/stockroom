"""The scrape engine entry point (spec sections 3, 4). S1 wires the cache and the
HTTP tier: fetch() returns a cache hit if fresh, else GETs through the stealth
HTTP client, caches a good 2xx Page, and returns a typed outcome. It never
raises. The browser render tier and page-vs-binary routing arrive in S2; the
extract/scrape and crawl entry points in S3/S4."""

from __future__ import annotations

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.fetch.http import HttpClient
from stockroom.scrape.model import FetchOutcome, Page


class ScrapeEngine:
    def __init__(self, cache: ResponseCache | None = None, http: HttpClient | None = None):
        self._cache = cache
        self._http = http or HttpClient()

    async def fetch(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchOutcome:
        if self._cache is not None:
            hit = self._cache.get(url)
            if hit is not None:
                return hit
        outcome = await self._http.get(url, referer=referer, timeout=timeout)
        if (
            isinstance(outcome, Page)
            and outcome.ok
            and not outcome.from_cache
            and self._cache is not None
        ):
            try:
                self._cache.put(outcome)
            except OSError:
                pass  # a cache-write failure must not turn a good fetch into an error
        return outcome
