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


def _host_of(url: str) -> str:
    return (urlsplit(url).netloc or "").lower()


class ScrapeEngine:
    def __init__(self, cache: ResponseCache | None = None, http: HttpClient | None = None,
                 browser=None, scheduler=None):
        self._cache = cache
        self._http = http or HttpClient()
        self._browser = browser
        # The anti-ban scheduler (S4): paces each host, records blocks/successes, trips a
        # per-host breaker. Optional; with none the engine is un-governed (S1-S3 behavior).
        self._scheduler = scheduler

    async def aclose(self) -> None:
        """Close the owned browser tier (called by ScrapeRuntime teardown). Never raises."""
        browser = self._browser
        aclose = getattr(browser, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:  # noqa: BLE001 - teardown never raises
                pass

    def _cached(self, url: str) -> Page | None:
        if self._cache is None:
            return None
        return self._cache.get(url)

    def _negative(self, url: str) -> bool:
        return self._cache is not None and self._cache.is_negative(url)

    def _record(self, url: str, host: str, outcome: FetchOutcome) -> None:
        """Feed the outcome back into the anti-ban subsystem: a block tightens the host,
        trips its breaker, and is negative-cached so the next attempt does not re-hit it; a
        success loosens the host."""
        if isinstance(outcome, FetchError) and outcome.kind == "blocked":
            if self._scheduler is not None:
                self._scheduler.record_block(host, getattr(outcome, "retry_after", None))
            if self._cache is not None:
                try:
                    self._cache.put_negative(url)
                except OSError:
                    pass
        elif isinstance(outcome, Page) and outcome.ok and self._scheduler is not None:
            self._scheduler.record_success(host)

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
        if self._negative(url):
            return FetchError(url=url, reason="recently blocked (negative cache)", kind="blocked")
        host = _host_of(url)
        if self._scheduler is not None:
            await self._scheduler.acquire(host)
        try:
            outcome = await self._http.get(url, referer=referer, timeout=timeout)
        finally:
            if self._scheduler is not None:
                self._scheduler.release(host)
        self._record(url, host, outcome)
        self._store(outcome)
        return outcome

    async def render(self, url: str, timeout: float = 20.0) -> FetchOutcome:
        if self._browser is None:
            return FetchError(url=url, reason="no browser render tier configured", kind="transport")
        hit = self._cached(url)
        if hit is not None:
            return hit
        if self._negative(url):
            return FetchError(url=url, reason="recently blocked (negative cache)", kind="blocked")
        host = _host_of(url)
        if self._scheduler is not None:
            await self._scheduler.acquire(host)
        try:
            outcome = await self._browser.fetch(url, timeout=timeout)
        finally:
            if self._scheduler is not None:
                self._scheduler.release(host)
        self._record(url, host, outcome)
        self._store(outcome)
        return outcome

    async def fetch(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchOutcome:
        # Best method per target: a page renders in the browser, a binary/API downloads
        # by HTTP. With no browser configured the engine is HTTP-only (S1 behavior).
        if self._browser is not None and not _is_downloadable(url):
            return await self.render(url, timeout=timeout)
        return await self.download(url, referer=referer, timeout=timeout)

    async def crawl(self, seed: str, scope, workers: int = 8, timeout: float = 20.0) -> list:
        """Concurrently crawl from `seed` within `scope` (spec section 5): workers pull the
        frontier, scrape each page (auto-governed by the anti-ban scheduler), dedup by
        canonical URL + content hash, and enqueue in-scope unseen links. Returns the list of
        ScrapeResults. Never raises: a blocked/dead page is recorded and skipped, not fatal;
        an empty or fully-blocked crawl returns []."""
        import asyncio
        import hashlib
        from dataclasses import replace

        from stockroom.scrape.crawl.frontier import Frontier, scope_host
        from stockroom.scrape.model import ScrapeResult

        # Bind the seed's host onto a COPY so the caller's Scope is never mutated, and derive
        # it with scope_host (bare hostname) so it matches Scope.allows - _host_of returns the
        # netloc (with port), which is right for scheduler keying but wrong for scope.
        if getattr(scope, "same_host", True) and getattr(scope, "host", None) is None:
            scope = replace(scope, host=scope_host(seed))
        frontier = Frontier(scope)
        results: list = []
        pending = 0
        done = asyncio.Event()

        if frontier.add(seed, 0):
            pending = 1
        else:
            return results

        async def _process(url: str, depth: int) -> None:
            nonlocal pending
            try:
                outcome = await self.scrape(url, timeout=timeout)
                if isinstance(outcome, ScrapeResult) and outcome.ok:
                    digest = hashlib.sha256(outcome.page.content).hexdigest()
                    if frontier.seen_content(digest):
                        frontier.release_slot()   # a duplicate body frees its page-budget slot
                    else:
                        results.append(outcome)
                        for link in outcome.links:
                            try:
                                added = frontier.add(link, depth + 1)
                            except Exception:  # noqa: BLE001 - a malformed link is dropped, never fatal
                                added = False
                            if added:
                                pending += 1
            except Exception:  # noqa: BLE001 - a per-URL failure is skipped; the worker survives
                pass
            finally:
                pending -= 1
                if pending <= 0:
                    done.set()

        async def _worker() -> None:
            while True:
                url, depth = await frontier.get()
                await _process(url, depth)

        tasks = [asyncio.create_task(_worker()) for _ in range(max(1, workers))]
        try:
            await done.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return results

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
