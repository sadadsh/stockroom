"""The enrichment orchestrator.

Builds the default priority-registry (LCSC/generic scrape through the WebView2
seam -> datasheet -> optional Mouser), rate-limits and caches each MPN, and fills
an M3 StagingCandidate per-field WITHOUT ever silently overwriting a filled field
(spec section 6.1). A total miss leaves the candidate untouched and never blocks
the complete-to-add gate; the missed fields are simply left for manual fill
(source-agnostic completeness, the load-bearing rule)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from stockroom.enrich.cache import TtlCache
from stockroom.enrich.extract import extract_all
from stockroom.enrich.fetch import HttpRenderedDomFetcher, RenderedDomFetcher
from stockroom.enrich.ratelimit import SlidingWindowLimiter
from stockroom.enrich.registry import DEFAULT_WANT, SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Purchase

# Canonical field -> StagingCandidate attribute it fills. Only these simple text
# fields flow straight onto the M3 candidate; price/URL become a Purchase.
_CANDIDATE_FIELDS = {
    "mpn": "mpn",
    "manufacturer": "manufacturer",
    "description": "description",
}


def _default_url_for(mpn: str, category: str) -> str:
    """A best-effort product-search URL for a bare MPN. Real per-site URL
    resolution is a site extractor concern; this is the generic fallback."""
    return f"https://www.lcsc.com/search?q={quote(mpn)}"


class ScrapeSource:
    name = "scrape"

    def __init__(self, fetcher: RenderedDomFetcher, limiter, url_for=None,
                 site_extractors=SITE_EXTRACTORS):
        self._fetcher = fetcher
        self._limiter = limiter
        self._url_for = url_for or _default_url_for
        self._site_extractors = site_extractors

    def enrich(self, mpn: str, category: str, remaining: set[str]) -> EnrichmentResult:
        url = self._url_for(mpn, category)
        self._limiter.acquire()
        page = self._fetcher.rendered_html(url)
        result = extract_all(page.text, page.final_url or url, self._site_extractors)
        # record the product URL so the pipeline can build a Purchase link
        if page.final_url or url:
            result.specs.setdefault(
                "product_url", Sourced(page.final_url or url, "scrape", "medium")
            )
        return result


class DatasheetSource:
    name = "datasheet"

    def __init__(self, fetcher=None):
        self._fetcher = fetcher

    def enrich(self, mpn: str, category: str, remaining: set[str]) -> EnrichmentResult:
        # The pipeline threads a resolved datasheet_url via remaining context is
        # not used here; this source contributes nothing on a bare MPN and is a
        # placeholder for the pipeline's explicit fetch_and_extract path below.
        return EnrichmentResult(category=category)


class EnrichmentPipeline:
    def __init__(self, cache_dir, fetcher: RenderedDomFetcher | None = None,
                 mouser=None, limiter=None, url_for=None):
        self.cache = TtlCache(Path(cache_dir))
        self.fetcher = fetcher or HttpRenderedDomFetcher()
        self.limiter = limiter or SlidingWindowLimiter(limit=10, window=60.0)
        self.mouser = mouser
        sources = [ScrapeSource(self.fetcher, self.limiter, url_for=url_for)]
        if mouser is not None and getattr(mouser, "enabled", False):
            sources.append(_MouserSource(mouser))
        self.registry = SourceRegistry(sources)

    def enrich(self, mpn: str, category: str, want=None) -> EnrichmentResult:
        cached = self.cache.get(mpn)
        if cached is not None:
            return _result_from_cache(cached, category)
        result = self.registry.enrich(mpn, category, want=set(want) if want else set(DEFAULT_WANT))
        self.cache.put(mpn, _result_to_cache(result))
        return result

    def enrich_candidate(self, candidate: StagingCandidate,
                         overwrite: set[str] | None = None) -> StagingCandidate:
        overwrite = overwrite or set()
        mpn = candidate.mpn or candidate.entry_name or candidate.display_name
        result = self.enrich(mpn, candidate.category)

        for field_name, attr in _CANDIDATE_FIELDS.items():
            sourced = getattr(result, field_name)
            if sourced is None:
                continue
            current = getattr(candidate, attr, "")
            if not current or attr in overwrite:
                setattr(candidate, attr, str(sourced.value))

        # a purchase link from the product URL + price breaks (fills the passport's
        # sourcing field; still per-field: only if the candidate has no purchase yet)
        product_url = result.specs.get("product_url")
        if product_url is not None and (not candidate.purchase or "purchase" in overwrite):
            candidate.purchase = [Purchase(
                vendor="scrape",
                url=str(product_url.value),
                price_breaks=[{"qty": b.qty, "price": b.price} for b in result.price_breaks],
                stock=(result.stock.value if result.stock else None),
            )]

        # thread a datasheet URL onto provenance so M3's to_staged_part wires the
        # Datasheet meta (source_url), without overwriting an existing one
        if result.datasheet_url is not None and candidate.provenance is not None:
            if not candidate.provenance.source_url or "datasheet" in overwrite:
                candidate.provenance.source_url = str(result.datasheet_url.value)
        return candidate


class _MouserSource:
    name = "mouser"

    def __init__(self, adapter):
        self._adapter = adapter

    def enrich(self, mpn, category, remaining):
        return self._adapter.lookup(mpn)


def _result_to_cache(r: EnrichmentResult) -> dict:
    def s(v):
        return None if v is None else {"value": v.value, "source": v.source, "confidence": v.confidence}
    return {
        "schema_version": r.schema_version,
        "category": r.category,
        "mpn": s(r.mpn), "manufacturer": s(r.manufacturer), "description": s(r.description),
        "datasheet_url": s(r.datasheet_url), "stock": s(r.stock), "package": s(r.package),
        "price_breaks": [{"qty": b.qty, "price": b.price, "currency": b.currency} for b in r.price_breaks],
        "specs": {k: {"value": v.value, "source": v.source, "confidence": v.confidence} for k, v in r.specs.items()},
    }


def _result_from_cache(d: dict, category: str) -> EnrichmentResult:
    from stockroom.enrich.schema import PriceBreak

    def s(v):
        return None if v is None else Sourced(v["value"], v["source"], v["confidence"])
    r = EnrichmentResult(category=d.get("category", category))
    r.mpn, r.manufacturer, r.description = s(d.get("mpn")), s(d.get("manufacturer")), s(d.get("description"))
    r.datasheet_url, r.stock, r.package = s(d.get("datasheet_url")), s(d.get("stock")), s(d.get("package"))
    r.price_breaks = [PriceBreak(**b) for b in d.get("price_breaks", [])]
    r.specs = {k: Sourced(v["value"], v["source"], v["confidence"]) for k, v in d.get("specs", {}).items()}
    return r
