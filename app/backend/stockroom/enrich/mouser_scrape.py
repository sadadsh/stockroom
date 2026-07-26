"""Mouser data source for the bulk rescan: the keyless crawler PRIMARY, the Mouser API as the
FALLBACK when the crawler hits an error/block (owner directive 2026-07-19). Mouser is the primary
procurement source; the user provides the distributor link, so the crawler renders the part's
OWN stored Mouser `Purchase.url` (no MPN->URL guessing). When Mouser's WAF (DataDome) blocks the
crawler, the official Mouser Search API rescues that part by MPN — and once the crawler is clearly
blocked for the run, we stop wasting crawl attempts and go API-only for the rest.

`MouserScrapeAdapter` keeps the rescan adapter shape (`.enabled` / `.lookup(mpn) -> EnrichmentResult`
/ `.last_status` / `.vendor`). last_status carries the effective verdict: "ok" when either source
returned data, "rate_limited" only when BOTH the crawler is blocked AND the API failed (so the
rescan circuit breaker trips only when Mouser is truly exhausted), "not_found" on a clean miss."""

from __future__ import annotations

import importlib.util
from typing import Callable

from stockroom.enrich.refresh import _has_data
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.scrape.extract import extract_all
from stockroom.scrape.validate import validate_product


class MouserScrapeAdapter:
    """A rescan procurement adapter: Mouser crawler (a part's stored link) primary, Mouser API fallback."""

    vendor = "Mouser"

    def __init__(
        self,
        fetcher,
        url_for: Callable[[str], str | None],
        limiter=None,
        timeout: float = 20.0,
        api_fallback=None,
    ):
        # `fetcher` is a RenderedDomFetcher (rendered_html(url) -> FetchResult); `url_for` maps an
        # MPN to that part's stored Mouser product URL. `api_fallback` is a MouserAdapter (the
        # official API) used when the crawler errors/blocks, or None.
        self._fetcher = fetcher
        self._url_for = url_for
        self._limiter = limiter
        self._timeout = timeout
        self._api = api_fallback
        # Once the crawler is clearly WAF-blocked this run, skip it and go API-only for the rest -
        # a block is persistent, so re-attempting the (slow) render on every later part is wasted.
        self._scrape_blocked = False
        # out-of-band signal for the rescan circuit breaker; never affects the returned result.
        self.last_status: str = ""

    def _scrape_available(self) -> bool:
        return self._fetcher is not None and importlib.util.find_spec("camoufox") is not None

    @property
    def enabled(self) -> bool:
        # Usable when EITHER the crawler (fetcher + Camoufox) OR the API fallback is available.
        return self._scrape_available() or (
            self._api is not None and getattr(self._api, "enabled", False)
        )

    def _scrape_lookup(self, mpn: str) -> EnrichmentResult:
        """Render the part's stored Mouser link and extract it; sets last_status to
        ok / rate_limited (blocked) / not_found (no link or thin page)."""
        url = self._url_for(mpn) if self._url_for is not None else None
        if not url:
            self.last_status = "not_found"
            return EnrichmentResult()
        if self._limiter is not None:
            self._limiter.acquire()
        page = self._fetcher.rendered_html(url, timeout=self._timeout)
        if not getattr(page, "text", ""):
            self.last_status = "rate_limited"  # a WAF block/dead render collapses to empty text
            return EnrichmentResult()
        final = getattr(page, "final_url", "") or url
        result = validate_product(extract_all(page.text, final, SITE_EXTRACTORS))
        if not _has_data(result):
            self.last_status = "not_found"
            return EnrichmentResult()
        result.specs.setdefault("product_url", Sourced(final, "scrape", "medium"))
        self.last_status = "ok"
        return result

    def lookup(self, mpn: str) -> EnrichmentResult:
        self.last_status = ""
        if not mpn:
            return EnrichmentResult()
        # 1. Crawler PRIMARY (skipped once it is proven blocked for this run).
        if self._scrape_available() and not self._scrape_blocked:
            result = self._scrape_lookup(mpn)
            if self.last_status == "ok":
                return result
            if self.last_status == "rate_limited":
                self._scrape_blocked = True  # persistent WAF block -> API-only for the rest of the run
        # 2. Mouser API FALLBACK: rescues a blocked/errored crawler AND missing-link/thin cases.
        if self._api is not None and getattr(self._api, "enabled", False):
            result = self._api.lookup(mpn)
            self.last_status = getattr(self._api, "last_status", "") or self.last_status
            return result
        # Nothing rescued: last_status carries the crawler's verdict (rate_limited trips the breaker).
        return EnrichmentResult()
