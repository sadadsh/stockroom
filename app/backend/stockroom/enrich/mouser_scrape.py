"""Keyless Mouser data source for the bulk rescan (owner directive 2026-07-19: Mouser is the
PRIMARY procurement-data source via the crawler, DigiKey the API fallback; the user provides the
distributor link, so there is NO MPN->URL guessing).

`MouserScrapeAdapter` mirrors the rescan adapter shape of `enrich.mouser.MouserAdapter`
(`.enabled` / `.lookup(mpn) -> EnrichmentResult` / `.last_status` / `.vendor`), but instead of the
Mouser Search API it renders the part's ALREADY-STORED Mouser product link through the stealthed
rendered-DOM fetcher (Camoufox, which clears Mouser's DataDome) and runs the Mouser web extractor.

The link comes from the caller via `url_for(mpn)` (built from each part's Mouser `Purchase.url`),
never from a search: an exact stored product link is reliable, whereas a `/c/?q=` search redirect
is not (an ambiguous MPN lands on a search-results page the extractor cannot parse). A block or a
dead render collapses to empty text at the fetch boundary (FetchResult carries no block flag), so
an empty render is reported as `rate_limited` to trip the rescan circuit breaker; a missing link or
a thin page is an honest `not_found` that does not trip it."""

from __future__ import annotations

import importlib.util
from typing import Callable

from stockroom.enrich.refresh import _has_data
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.scrape.extract import extract_all
from stockroom.scrape.validate import validate_product


class MouserScrapeAdapter:
    """A rescan procurement adapter that scrapes a part's stored Mouser link (no API key)."""

    vendor = "Mouser"

    def __init__(
        self,
        fetcher,
        url_for: Callable[[str], str | None],
        limiter=None,
        timeout: float = 20.0,
    ):
        # `fetcher` is a RenderedDomFetcher (rendered_html(url) -> FetchResult); shared with the
        # enrichment path so the rescan never spins up a second browser. `url_for` maps an MPN to
        # that part's stored Mouser product URL (or None when the part has no Mouser link yet).
        self._fetcher = fetcher
        self._url_for = url_for
        self._limiter = limiter
        self._timeout = timeout
        # out-of-band signal for the rescan circuit breaker; never affects the returned result.
        self.last_status: str = ""

    @property
    def enabled(self) -> bool:
        # Usable only when a rendered-DOM fetcher is wired AND the Camoufox package is importable
        # (its patched-Firefox binary is provisioned out of band); otherwise the rescan skips it.
        return self._fetcher is not None and importlib.util.find_spec("camoufox") is not None

    def lookup(self, mpn: str) -> EnrichmentResult:
        self.last_status = ""
        if not self.enabled or not mpn:
            return EnrichmentResult()
        url = self._url_for(mpn) if self._url_for is not None else None
        if not url:
            # No stored link for this part: an honest miss, not a breaker-tripping failure.
            self.last_status = "not_found"
            return EnrichmentResult()
        if self._limiter is not None:
            self._limiter.acquire()
        page = self._fetcher.rendered_html(url, timeout=self._timeout)
        if not getattr(page, "text", ""):
            # A WAF block or dead render collapses to empty text (FetchResult has no block flag);
            # report it as rate_limited so RescanEngine._lookup pauses Mouser for the rest of the run.
            self.last_status = "rate_limited"
            return EnrichmentResult()
        final = getattr(page, "final_url", "") or url
        result = validate_product(extract_all(page.text, final, SITE_EXTRACTORS))
        if not _has_data(result):
            # A served-but-thin page (challenge shell, wrong page) carried no procurement data.
            self.last_status = "not_found"
            return EnrichmentResult()
        result.specs.setdefault("product_url", Sourced(final, "scrape", "medium"))
        self.last_status = "ok"
        return result
