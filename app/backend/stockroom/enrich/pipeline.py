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
from stockroom.enrich.datasheet import extract_datasheet_specs, fetch_datasheet
from stockroom.enrich.errors import EnrichError
from stockroom.enrich.extract import extract_all
from stockroom.enrich.fetch import HttpFetcher, HttpRenderedDomFetcher, RenderedDomFetcher
from stockroom.enrich.ratelimit import SlidingWindowLimiter
from stockroom.enrich.registry import DEFAULT_WANT, SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Provenance, Purchase

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


class PassiveFastPathSource:
    """Source #0: the offline passive fast path. A resistor/capacitor/inductor MPN
    decodes deterministically (no network, no API) into its value/tolerance/package/
    power and resolves the KiCad stock symbol/footprint/3D it should use, so a passive
    enriches fully with zero network (the owner's "drop the MPN and you are done"
    path). Contributes nothing for a non-passive MPN, so the registry walk continues."""

    name = "passive"

    def __init__(self, footprints_root=None):
        self._footprints_root = footprints_root

    def enrich(self, mpn: str, category: str, remaining: set[str]) -> EnrichmentResult:
        from stockroom.enrich.passive import parse_passive_mpn, resolve_passive_assets

        r = EnrichmentResult(category=category)
        spec = parse_passive_mpn(mpn)
        if spec is None:
            return r  # not a decodable passive; the walk continues untouched
        if spec.mpn:
            r.mpn = Sourced(spec.mpn, "passive", "high")
        if spec.manufacturer:
            r.manufacturer = Sourced(spec.manufacturer, "passive", "high")
        if spec.package:
            r.package = Sourced(spec.package, "passive", "high")
        desc = spec.summary()
        if desc:
            r.description = Sourced(desc, "passive", "medium")
        for key, val in spec.to_specs().items():
            r.specs.setdefault(key, Sourced(val, "passive", "high"))
        if spec.package:
            assets = resolve_passive_assets(spec.kind, spec.package, self._footprints_root)
            if assets is not None:
                r.specs.setdefault("Symbol", Sourced(assets.symbol, "passive", "high"))
                r.specs.setdefault("Footprint", Sourced(assets.footprint, "passive", "high"))
                r.specs.setdefault("3D Model", Sourced(assets.model_3d, "passive", "high"))
        return r


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
    """The ban-proof PRIMARY source (spec section 6.1 item 3). It runs AFTER the
    scrape in the registry: if a prior source surfaced a `datasheet_url`, it follows
    it, validates a real PDF (Content-Type + %PDF- magic), and extracts specs
    (package, manufacturer, pinout) at high confidence, so the datasheet's values are
    merged for any field still empty. With no datasheet_url it contributes nothing
    and never blocks the walk."""

    name = "datasheet"

    def __init__(self, fetcher=None, cache_dir=None):
        self._fetcher = fetcher
        # PDFs are fetched into this dir so a stored path can back the passport's
        # datasheet requirement; a temp dir is used when the pipeline gives none.
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None

    def enrich(self, mpn: str, category: str, remaining: set[str],
               resolved: EnrichmentResult | None = None) -> EnrichmentResult:
        empty = EnrichmentResult(category=category)
        if resolved is None or resolved.datasheet_url is None:
            return empty
        url = str(resolved.datasheet_url.value)
        # Only worth fetching+parsing the PDF if a datasheet-derived field is still
        # wanted; specs/pinout/package/manufacturer are what the datasheet adds.
        if remaining and not (remaining & {"package", "manufacturer", "specs", "mpn"}):
            return empty
        import tempfile

        base = self._cache_dir or Path(tempfile.gettempdir()) / "stockroom-datasheets"
        base.mkdir(parents=True, exist_ok=True)
        from stockroom.enrich.schema import normalize_mpn

        dst = base / f"{normalize_mpn(mpn or 'part')}.pdf"
        try:
            pdf_path = fetch_datasheet(url, dst, fetcher=self._fetcher)
        except EnrichError:
            return empty  # a dead/HTML datasheet link never blocks the walk
        try:
            return extract_datasheet_specs(pdf_path, known_mpn=mpn)
        except EnrichError:
            return empty


class EnrichmentPipeline:
    def __init__(self, cache_dir, fetcher: RenderedDomFetcher | None = None,
                 mouser=None, limiter=None, url_for=None, http_fetcher=None,
                 mouser_limiter=None):
        self.cache = TtlCache(Path(cache_dir))
        self.fetcher = fetcher or HttpRenderedDomFetcher()
        self.limiter = limiter or SlidingWindowLimiter(limit=10, window=60.0)
        # The Mouser API has its OWN documented cap (~30/60), separate from the gentler
        # scraper budget, so it gets a dedicated limiter (lifted from KiCost's api_mouser).
        self.mouser_limiter = mouser_limiter or SlidingWindowLimiter(limit=30, window=60.0)
        self.mouser = mouser
        # The datasheet PDF is a direct HTTP GET (not a rendered DOM), so it uses an
        # HttpFetcher; injectable so tests never touch the network.
        self.http_fetcher = http_fetcher or HttpFetcher()
        self._datasheet_dir = Path(cache_dir) / "datasheets"
        # Default registry: passive fast path (offline, deterministic, no network) ->
        # scrape (surfaces a datasheet_url) -> datasheet (follows it, the ban-proof
        # primary source) -> optional Mouser. Each fills only what is still missing
        # (spec section 6.1); the passive path runs first so a passive never needs the
        # network and its exact stock assets win.
        sources = [
            PassiveFastPathSource(),
            ScrapeSource(self.fetcher, self.limiter, url_for=url_for),
            DatasheetSource(fetcher=self.http_fetcher, cache_dir=self._datasheet_dir),
        ]
        if mouser is not None and getattr(mouser, "enabled", False):
            sources.append(_MouserSource(mouser, self.mouser_limiter))
        self.registry = SourceRegistry(sources)

    def enrich(self, mpn: str, category: str, want=None) -> EnrichmentResult:
        cached = self.cache.get(mpn)
        if cached is not None:
            return _result_from_cache(cached, category)
        result = self.registry.enrich(mpn, category, want=set(want) if want else set(DEFAULT_WANT))
        self.cache.put(mpn, _result_to_cache(result))
        return result

    def enrich_from_product_url(self, candidate: StagingCandidate, url: str,
                                overwrite: set[str] | None = None) -> StagingCandidate:
        """Fill a candidate's blank identity straight from a distributor product page
        the user pasted (a purchase link). The pasted link is a direct primary source,
        so we fetch THAT exact page (never an MPN search) and read mpn/manufacturer/
        description/datasheet/price from its schema.org Product data. Per-field (never
        clobbers an existing value unless opted in) and never raises: a dead link or an
        unparseable page contributes nothing (enrichment never blocks)."""
        overwrite = overwrite or set()
        url = (url or "").strip()
        if not url:
            return candidate
        try:
            self.limiter.acquire()
            page = self.fetcher.rendered_html(url)
        except (EnrichError, OSError):
            return candidate  # a dead purchase link never blocks the fill
        result = extract_all(page.text, page.final_url or url, SITE_EXTRACTORS)

        for field_name, attr in _CANDIDATE_FIELDS.items():
            sourced = getattr(result, field_name)
            if sourced is None:
                continue
            if not getattr(candidate, attr, "") or attr in overwrite:
                setattr(candidate, attr, str(sourced.value))

        # Attach the scraped price/stock to the purchase entry the user pasted, keeping
        # its vendor and url intact (a pasted Mouser link stays a Mouser link).
        existing = next((p for p in candidate.purchase if p.url == url), None)
        if existing is not None:
            if result.price_breaks and (not existing.price_breaks or "purchase" in overwrite):
                existing.price_breaks = [
                    {"qty": b.qty, "price": b.price} for b in result.price_breaks
                ]
            stock = result.stock.value if result.stock else None
            if stock is not None and (existing.stock is None or "purchase" in overwrite):
                existing.stock = stock

        # Thread the datasheet onto provenance and fetch+store the PDF (the passport's
        # datasheet requirement checks a stored path), mirroring enrich_candidate.
        if result.datasheet_url is not None:
            if candidate.provenance is None:
                candidate.provenance = Provenance(source="manual")
            if not candidate.provenance.source_url or "datasheet" in overwrite:
                candidate.provenance.source_url = str(result.datasheet_url.value)
            if candidate.datasheet_path is None or "datasheet" in overwrite:
                self.fetch_and_store_datasheet(candidate, str(result.datasheet_url.value))
        return candidate

    def enrich_candidate(self, candidate: StagingCandidate,
                         overwrite: set[str] | None = None) -> StagingCandidate:
        overwrite = overwrite or set()
        # A pasted purchase link is a direct primary source: scrape THAT page first so
        # a candidate with only a distributor link still fills everything (owner ask).
        if candidate.purchase and candidate.purchase[0].url:
            self.enrich_from_product_url(candidate, candidate.purchase[0].url, overwrite)
        mpn = candidate.mpn or candidate.entry_name or candidate.display_name
        if not mpn:
            # Nothing to search on (no MPN even after the product-page scrape); the
            # blank fields stay blank rather than firing a junk empty-query search.
            return candidate
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

        # actually FETCH+store the PDF so the passport's datasheet requirement can be
        # met (the gate checks a stored datasheet_path, not just a URL). Per-field:
        # only if the candidate has no datasheet yet (or datasheet is opted in). A
        # failed/HTML datasheet link never blocks: datasheet_path is simply left unset.
        if result.datasheet_url is not None and (
            candidate.datasheet_path is None or "datasheet" in overwrite
        ):
            self.fetch_and_store_datasheet(candidate, str(result.datasheet_url.value))
        return candidate

    def datasheet_fill(self, candidate: StagingCandidate) -> StagingCandidate:
        """Fill blank identity fields straight from the candidate's own stored
        datasheet PDF (the user-provided primary source), before any scraping.
        Never overwrites a value and never raises: an unreadable PDF contributes
        nothing (enrichment never blocks)."""
        if candidate.datasheet_path is None:
            return candidate
        from stockroom.enrich import datasheet as _datasheet

        try:
            result = _datasheet.extract_datasheet_specs(
                candidate.datasheet_path, known_mpn=candidate.mpn
            )
        except (EnrichError, OSError):
            return candidate
        for field_name, attr in _CANDIDATE_FIELDS.items():
            sourced = getattr(result, field_name, None)
            if sourced is None:
                continue
            if not getattr(candidate, attr, ""):
                setattr(candidate, attr, str(sourced.value))
        return candidate

    def fetch_and_store_datasheet(
        self, candidate: StagingCandidate, url: str, force: bool = False
    ) -> Path | None:
        """Follow a datasheet URL, validate a real PDF, store it under the pipeline's
        datasheet dir, and set candidate.datasheet_path. Returns the path, or None if
        the link was dead or not a PDF (never raises: enrichment never blocks).
        force=True refetches even when a cached PDF exists: an EXPLICITLY pasted URL
        must win over a stale earlier download."""
        from stockroom.enrich.schema import normalize_mpn

        from stockroom.enrich.datasheet import looks_like_pdf

        self._datasheet_dir.mkdir(parents=True, exist_ok=True)
        key = normalize_mpn(candidate.mpn or candidate.entry_name or candidate.display_name or "part")
        dst = self._datasheet_dir / f"{key}.pdf"
        # The registry's DatasheetSource may already have fetched this exact PDF (same
        # deterministic path) to extract specs; reuse it instead of a second download.
        if not force and dst.exists() and looks_like_pdf(dst.read_bytes()[:5]):
            candidate.datasheet_path = dst
            return dst
        try:
            path = fetch_datasheet(url, dst, fetcher=self.http_fetcher)
        except EnrichError:
            return None
        candidate.datasheet_path = path
        return path


class _MouserSource:
    name = "mouser"

    def __init__(self, adapter, limiter=None):
        self._adapter = adapter
        self._limiter = limiter

    def enrich(self, mpn, category, remaining):
        # Pace the Mouser API path (the exact ban scenario the KiCost limiter exists to
        # prevent). Without this a bulk enrich of many uncached parts fires unthrottled and
        # can trip Mouser's rate cap; the mouser.py docstring's "paced" claim depends on it.
        if self._limiter is not None:
            self._limiter.acquire()
        return self._adapter.lookup(mpn)


def _result_to_cache(r: EnrichmentResult) -> dict:
    def s(v):
        return None if v is None else {"value": v.value, "source": v.source, "confidence": v.confidence}
    return {
        "schema_version": r.schema_version,
        "category": r.category,
        "mpn": s(r.mpn), "manufacturer": s(r.manufacturer), "description": s(r.description),
        "datasheet_url": s(r.datasheet_url), "stock": s(r.stock), "package": s(r.package),
        # M7d procurement fields: persist them so a cache hit keeps a part's lifecycle, lead
        # time, product page and distributor P/Ns (otherwise a re-build silently drops the
        # sourcing risk + lead the first fresh lookup found).
        "lifecycle": s(r.lifecycle), "lead_time": s(r.lead_time), "product_url": s(r.product_url),
        "dist_pns": dict(r.dist_pns),
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
    r.lifecycle, r.lead_time, r.product_url = s(d.get("lifecycle")), s(d.get("lead_time")), s(d.get("product_url"))
    r.dist_pns = dict(d.get("dist_pns", {}))
    r.price_breaks = [PriceBreak(**b) for b in d.get("price_breaks", [])]
    r.specs = {k: Sourced(v["value"], v["source"], v["confidence"]) for k, v in d.get("specs", {}).items()}
    return r
