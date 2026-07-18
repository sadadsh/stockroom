"""The scrape engine entry point (spec sections 3, 4). Best method per target,
chosen upfront, no ramp: a web page renders in the full-stealth browser
(render_tier="browser"), a binary or data endpoint (PDF, JSON API, asset)
downloads by stealth HTTP. Both are cache-first, so repeats never touch the
network. Every path returns a typed Page or FetchError; nothing raises.

Extraction/markdown (S3) and the crawler + context pool (S4) build on these
seams. The browser tier is injected (BrowserFetcher); with none configured the
engine is HTTP-only, which is exactly the S1 behavior."""

from __future__ import annotations

from urllib.parse import urlsplit

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.fetch.http import HttpClient
from stockroom.scrape.model import FetchError, FetchOutcome, Page

# Path suffixes that are downloads, not pages: a browser is the wrong tool for
# these (slower, worse data), so they always take the direct HTTP tier.
_DOWNLOAD_SUFFIXES = (".pdf", ".zip", ".step", ".stp", ".wrl", ".json", ".csv", ".xml")


def _is_downloadable(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(_DOWNLOAD_SUFFIXES)


class ScrapeEngine:
    def __init__(self, cache: ResponseCache | None = None, http: HttpClient | None = None,
                 browser=None):
        self._cache = cache
        self._http = http or HttpClient()
        self._browser = browser

    def _cached(self, url: str) -> Page | None:
        if self._cache is None:
            return None
        return self._cache.get(url)

    def _store(self, outcome: FetchOutcome) -> None:
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

    async def download(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchOutcome:
        hit = self._cached(url)
        if hit is not None:
            return hit
        outcome = await self._http.get(url, referer=referer, timeout=timeout)
        self._store(outcome)
        return outcome

    async def render(self, url: str, timeout: float = 20.0) -> FetchOutcome:
        if self._browser is None:
            return FetchError(url=url, reason="no browser render tier configured", kind="transport")
        hit = self._cached(url)
        if hit is not None:
            return hit
        outcome = await self._browser.fetch(url, timeout=timeout)
        self._store(outcome)
        return outcome

    async def fetch(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchOutcome:
        # Best method per target: a page renders in the browser, a binary/API downloads
        # by HTTP. With no browser configured the engine is HTTP-only (S1 behavior).
        if self._browser is not None and not _is_downloadable(url):
            return await self.render(url, timeout=timeout)
        return await self.download(url, referer=referer, timeout=timeout)

    async def scrape(self, url: str, referer: str = "", timeout: float = 20.0):
        """Fetch (page -> browser, binary/API -> HTTP) then extract a full ScrapeResult
        (markdown + structured + links + validated product). A fetch failure passes the
        typed FetchError straight through. Never raises (spec section 3.1)."""
        from stockroom.scrape.extract import build_scrape_result
        from stockroom.scrape.model import ScrapeResult

        outcome = await self.fetch(url, referer=referer, timeout=timeout)
        if not isinstance(outcome, Page):
            return outcome
        try:
            return build_scrape_result(outcome)
        except Exception:  # noqa: BLE001 - extraction never sinks a good fetch
            return ScrapeResult(page=outcome)
