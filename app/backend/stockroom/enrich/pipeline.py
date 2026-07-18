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
from stockroom.scrape.validate import validate_product
from stockroom.enrich.fetch import HttpFetcher, HttpRenderedDomFetcher, RenderedDomFetcher
from stockroom.enrich.progress import Stage, emit, monotonic, stage_callback
from stockroom.enrich.ratelimit import SlidingWindowLimiter
from stockroom.enrich.registry import DEFAULT_WANT, SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Provenance, Purchase
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value

# Canonical field -> StagingCandidate attribute it fills. Only these simple text
# fields flow straight onto the M3 candidate; price/URL become a Purchase.
_CANDIDATE_FIELDS = {
    "mpn": "mpn",
    "manufacturer": "manufacturer",
    "description": "description",
}


def _copy_specs(candidate, result, overwrite: set[str]) -> None:
    """Carry every enriched spec (and the resolved package) onto the candidate's spec
    bag, so the FULL field set a distributor page yielded reaches the committed record,
    not just the three identity fields (the owner's capture-everything requirement).
    Per-field: an existing spec is kept unless 'specs' is opted into overwrite.
    product_url is a purchase-link mechanism, not a spec row."""
    take = "specs" in overwrite
    if result.package is not None and (take or "Package" not in candidate.specs):
        candidate.specs["Package"] = str(result.package.value)
    for label, sourced in result.specs.items():
        if label == "product_url":
            continue
        # Canonicalize the label to the record's key-space BEFORE the dedup check, so an
        # extractor that emits a duplicated-label key updates the existing clean key
        # instead of adding a twin the persistence layer would then collapse.
        key = normalize_spec_key(label)
        if not key:
            continue
        if take or key not in candidate.specs:
            candidate.specs[key] = normalize_spec_value(str(sourced.value))


def fill_category(result: EnrichmentResult) -> None:
    """Derive a real component category for a scraped result that has none (A4: a pasted
    non-passive link left the category "Other"/blank). The distributor's own "Product Category"
    spec is the strongest signal ("Thick Film Resistors - SMD" -> Resistors), backed by the
    description; the shared keyword classifier maps it. An unrecognized category is left
    untouched (never a wrong guess), so the user still picks it in review."""
    if result.category and result.category != "Other":
        return
    from stockroom.ingest.naming import propose_category

    # The distributor "Product Category" is the authoritative signal; classify from it ALONE
    # first, and only fall back to the description when it yields nothing. Blending them let a
    # description that merely NAMES another component ("resistor divider" on an IC) mis-steer the
    # category, so the two are tried in priority order, never joined.
    pc = result.specs.get("Product Category")
    guess = "Other"
    if pc is not None and str(pc.value).strip():
        guess = propose_category(str(pc.value))
    if guess == "Other" and result.description is not None:
        guess = propose_category(str(result.description.value))
    if guess != "Other":
        result.category = guess


def _is_substantive(result: EnrichmentResult) -> bool:
    """True when a scrape actually pulled part data (identity / package / price / a real spec),
    so the result is worth caching. A result carrying only the product_url marker, or just an
    OpenGraph description off a blocked/challenge page, is NOT substantive and is never cached as
    the answer, so the next lookup re-fetches instead of returning the thin miss forever."""
    if result.mpn is not None or result.package is not None or result.price_breaks:
        return True
    return any(key != "product_url" for key in result.specs)


def _default_url_for(mpn: str, category: str) -> str:
    """A best-effort product URL for a bare MPN, used only by the generic ScrapeSource
    fallback. LCSC catalogue resolution now lives in LcscSource (jlcsearch -> the real
    product page), so this only needs to handle the two cases the scrape can still use:
    a pasted LCSC C-id goes straight to its product-detail page (which carries the
    __NEXT_DATA__ the extractor reads); anything else falls back to the LCSC search."""
    ident = (mpn or "").strip()
    from stockroom.ingest.lcsc import is_lcsc_id

    if is_lcsc_id(ident):
        return f"https://www.lcsc.com/product-detail/{ident.upper()}.html"
    return f"https://www.lcsc.com/search?q={quote(ident)}"


class LcscSource:
    """Source #1: the LCSC catalogue, no API key. Resolves an MPN to its LCSC part
    number via the free jlcsearch endpoint (package, price breaks, live stock), then
    reads the LCSC product page's __NEXT_DATA__ for the FULL field set the JS-blind
    scrape misses: manufacturer, description, a direct datasheet PDF, and every spec /
    compliance / tariff / ordering field the page exposes. Structured and no-JS, so it
    fills what the dead search-URL scrape never could. Contributes an empty result on a
    catalogue miss or any network failure, so the registry walk is never blocked."""

    name = "lcsc"
    _PRODUCT_URL = "https://www.lcsc.com/product-detail/{lcsc}.html"

    def __init__(self, http_fetcher, jlcsearch=None, limiter=None):
        self._http = http_fetcher
        from stockroom.enrich.jlcsearch import JlcSearchClient

        self._jlc = jlcsearch or JlcSearchClient(http_fetcher)
        self._limiter = limiter

    def enrich(self, mpn: str, category: str, remaining: set[str],
               progress=None) -> EnrichmentResult:
        from stockroom.enrich.extract import _looks_like_datasheet_url
        from stockroom.enrich.sites.lcsc import parse_lcsc_product

        r = EnrichmentResult(category=category)
        emit(progress, Stage.FETCHING, "querying LCSC")
        try:
            hit = self._jlc.search(mpn)
        except EnrichError:
            return r  # a jlcsearch failure never blocks the walk
        if hit is None:
            return r  # not in the LCSC catalogue

        # jlcsearch leg: identity we already have without the second fetch.
        if hit.lcsc:
            r.dist_pns["lcsc"] = hit.lcsc
        if hit.package:
            r.package = Sourced(hit.package, "lcsc", "medium")
        if hit.stock is not None:
            r.stock = Sourced(hit.stock, "lcsc", "medium")
        if hit.price_breaks:
            r.price_breaks = list(hit.price_breaks)
        if hit.mpn:
            r.mpn = Sourced(hit.mpn, "lcsc", "medium")
        if not hit.lcsc:
            return r

        product_url = self._PRODUCT_URL.format(lcsc=hit.lcsc)
        r.product_url = Sourced(product_url, "lcsc", "medium")
        # the product_url spec is what the pipeline turns into a Purchase (carrying the
        # price breaks) - this is the link that makes Build & Cost work.
        r.specs.setdefault("product_url", Sourced(product_url, "lcsc", "medium"))

        # product-page leg: the full field set from __NEXT_DATA__.
        if self._limiter is not None:
            self._limiter.acquire()
        # The product-page GET is a FETCH; EXTRACTING is only emitted once the page is in hand and
        # about to be parsed, so a failed/slow fetch is never mislabeled as extraction (and never
        # pins the bar to 80 for a page that never loaded).
        emit(progress, Stage.FETCHING, "fetching the LCSC page")
        try:
            page = self._http.get(product_url)
            emit(progress, Stage.EXTRACTING, "reading the LCSC page")
            product = parse_lcsc_product(page.text)
        except EnrichError:
            return r  # the jlcsearch identity still stands; the page just did not load
        if product is None:
            return r

        if product.mpn:
            r.mpn = Sourced(product.mpn, "lcsc", "medium")
        if product.manufacturer:
            r.manufacturer = Sourced(product.manufacturer, "lcsc", "medium")
        if product.description:
            r.description = Sourced(product.description, "lcsc", "medium")
        if product.package and r.package is None:
            r.package = Sourced(product.package, "lcsc", "medium")
        if product.datasheet_url and _looks_like_datasheet_url(product.datasheet_url):
            r.datasheet_url = Sourced(product.datasheet_url, "lcsc", "medium")
        lifecycle = product.specs.get("Lifecycle")
        if lifecycle:
            from stockroom.enrich.schema import normalize_lifecycle

            norm = normalize_lifecycle(lifecycle)
            r.lifecycle = Sourced(norm, "lcsc", "medium")
            # normalize the spec-bag copy too (LCSC's raw "normal" -> "Active"), so the detail
            # view + BOM see the canonical status, and setdefault below never re-adds the raw one
            r.specs["Lifecycle"] = Sourced(norm, "lcsc", "medium")
        for label, value in product.specs.items():
            r.specs.setdefault(label, Sourced(value, "lcsc", "medium"))
        return r


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

    def enrich(self, mpn: str, category: str, remaining: set[str],
               progress=None) -> EnrichmentResult:
        url = self._url_for(mpn, category)
        self._limiter.acquire()
        emit(progress, Stage.FETCHING, "rendering distributor page")
        # on_stage is only passed when there is a sink, so a fetcher that predates the
        # progress seam (test stubs, the HTTP default) keeps its original call shape.
        on_stage = stage_callback(progress)
        kw = {"on_stage": on_stage} if on_stage is not None else {}
        page = self._fetcher.rendered_html(url, **kw)
        # No-bad-data gate (spec section 7): drop any malformed field the scrape surfaced
        # (bad MPN charset, negative stock, non-URL datasheet/product link, non-monotonic
        # price ladder) before it ever reaches a record.
        emit(progress, Stage.EXTRACTING, "reading the page")
        parsed = extract_all(page.text, page.final_url or url, self._site_extractors)
        emit(progress, Stage.VALIDATING, "checking values")
        result = validate_product(parsed)
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
               resolved: EnrichmentResult | None = None,
               progress=None) -> EnrichmentResult:
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
        emit(progress, Stage.FETCHING, "reading the datasheet")
        try:
            pdf_path = fetch_datasheet(url, dst, fetcher=self._fetcher)
        except EnrichError:
            return empty  # a dead/HTML datasheet link never blocks the walk
        emit(progress, Stage.EXTRACTING, "extracting datasheet specs")
        try:
            return extract_datasheet_specs(pdf_path, known_mpn=mpn)
        except EnrichError:
            return empty


class EnrichmentPipeline:
    def __init__(self, cache_dir, fetcher: RenderedDomFetcher | None = None,
                 mouser=None, limiter=None, url_for=None, http_fetcher=None,
                 mouser_limiter=None, jlcsearch=None, digikey=None):
        self.cache = TtlCache(Path(cache_dir))
        # A separate URL-keyed cache for the paste-a-link path (A6 determinism): the same link
        # returns the same result, and only a SUBSTANTIVE result is stored, so a one-off thin or
        # Akamai-blocked fetch never becomes the cached answer.
        self.url_cache = TtlCache(Path(cache_dir), prefix="url")
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
            LcscSource(self.http_fetcher, jlcsearch=jlcsearch, limiter=self.limiter),
            ScrapeSource(self.fetcher, self.limiter, url_for=url_for),
            DatasheetSource(fetcher=self.http_fetcher, cache_dir=self._datasheet_dir),
        ]
        if mouser is not None and getattr(mouser, "enabled", False):
            sources.append(_MouserSource(mouser, self.mouser_limiter))
        if digikey is not None and getattr(digikey, "enabled", False):
            sources.append(_DigiKeySource(digikey, self.mouser_limiter))
        self.registry = SourceRegistry(sources)

    def enrich(self, mpn: str, category: str, want=None, progress=None) -> EnrichmentResult:
        cached = self.cache.get(mpn)
        if cached is not None:
            # An instant cache hit does no network work; the job returns straight to a
            # `done`, so no fetching/rendering stage is claimed for it.
            return _result_from_cache(cached, category)
        # One monotonic wrapper for the whole registry walk, so a later source's low local
        # pct (the datasheet leg after the scrape leg) never rewinds the bar.
        sink = monotonic(progress)
        result = self.registry.enrich(mpn, category,
                                      want=set(want) if want else set(DEFAULT_WANT),
                                      progress=sink)
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
        result = validate_product(extract_all(page.text, page.final_url or url, SITE_EXTRACTORS))

        for field_name, attr in _CANDIDATE_FIELDS.items():
            sourced = getattr(result, field_name)
            if sourced is None:
                continue
            if not getattr(candidate, attr, "") or attr in overwrite:
                setattr(candidate, attr, str(sourced.value))
        _copy_specs(candidate, result, overwrite)

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

    def extract_from_url(self, url: str, progress=None) -> EnrichmentResult:
        """Fetch a distributor product page and extract EVERYTHING it exposes, from a
        URL alone (no candidate, no file): identity, price breaks, stock, datasheet,
        package, and the full parametric spec table. The fetch goes through the
        rendered-DOM fetcher (the real WebView2 browser on Windows), so Akamai /
        Cloudflare JS challenges that 403 a plain HTTP client are passed. Never raises:
        a blocked or dead page returns an empty result, honestly (spec 2.2)."""
        url = (url or "").strip()
        if not url:
            return EnrichmentResult()
        # A6: the same link returns the same result. A cache hit skips the (nondeterministic)
        # network fetch entirely, so repeat lookups are stable.
        cached = self.url_cache.get(url)
        if cached is not None:
            return _result_from_cache(cached, cached.get("category", ""))
        sink = monotonic(progress)
        emit(sink, Stage.FETCHING, "loading the page")
        # on_stage raises the render phase (the browser settle) from inside the fetcher;
        # only passed when there is a sink, so a legacy fetcher keeps its old signature.
        on_stage = stage_callback(sink)
        kw = {"on_stage": on_stage} if on_stage is not None else {}
        try:
            self.limiter.acquire()
            page = self.fetcher.rendered_html(url, **kw)
        except (EnrichError, OSError):
            return EnrichmentResult()
        emit(sink, Stage.EXTRACTING, "reading fields")
        parsed = extract_all(page.text, page.final_url or url, SITE_EXTRACTORS)
        emit(sink, Stage.VALIDATING, "checking values")
        result = validate_product(parsed)
        if page.final_url or url:
            result.specs.setdefault(
                "product_url", Sourced(page.final_url or url, "scrape", "medium")
            )
        fill_category(result)
        # Cache ONLY a substantive pull, so a one-off thin or Akamai-blocked fetch (which yields
        # just a description) never becomes the cached answer and a retry can still get the page.
        if _is_substantive(result):
            self.url_cache.put(url, _result_to_cache(result))
        return result

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
        _copy_specs(candidate, result, overwrite)

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

    def enrich(self, mpn, category, remaining, progress=None):
        # Pace the Mouser API path (the exact ban scenario the KiCost limiter exists to
        # prevent). Without this a bulk enrich of many uncached parts fires unthrottled and
        # can trip Mouser's rate cap; the mouser.py docstring's "paced" claim depends on it.
        if self._limiter is not None:
            self._limiter.acquire()
        # The Mouser API round-trip is real network work; emit FETCHING so the bar reflects the
        # in-flight lookup instead of freezing at the prior source's pct (every other networked
        # source emits its stages, so this closes the one remaining silent leg).
        emit(progress, Stage.FETCHING, "querying Mouser")
        return self._adapter.lookup(mpn)


class _DigiKeySource:
    name = "digikey"

    def __init__(self, adapter, limiter=None):
        self._adapter = adapter
        self._limiter = limiter

    def enrich(self, mpn, category, remaining, progress=None):
        # Shares the Mouser limiter (both are paced distributor APIs guarded against the
        # same kind of throttling/ban), so a bulk enrich with both live never doubles the
        # effective request rate against either budget.
        if self._limiter is not None:
            self._limiter.acquire()
        emit(progress, Stage.FETCHING, "querying DigiKey")
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
