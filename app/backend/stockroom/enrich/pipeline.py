"""The enrichment orchestrator.

Builds the default priority-registry (LCSC/generic scrape through the WebView2
seam -> datasheet -> optional Mouser), rate-limits and caches each MPN, and fills
an M3 StagingCandidate per-field WITHOUT ever silently overwriting a filled field
(spec section 6.1). A total miss leaves the candidate untouched and never blocks
the complete-to-add gate; the missed fields are simply left for manual fill
(source-agnostic completeness, the load-bearing rule)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from stockroom.enrich.apply import conflict_entries, spec_updates
from stockroom.enrich.cache import TtlCache
from stockroom.enrich.datasheet import extract_datasheet_specs, fetch_datasheet
from stockroom.enrich.distributor_url import (
    distributor_mpn_from_url,
    distributor_part_number_from_url,
    vendor_from_url,
)
from stockroom.enrich.errors import EnrichError
from stockroom.enrich.extract import extract_all
from stockroom.enrich.fetch import HttpFetcher, HttpRenderedDomFetcher, RenderedDomFetcher
from stockroom.enrich.progress import Stage, emit, monotonic, stage_callback
from stockroom.enrich.ratelimit import SlidingWindowLimiter
from stockroom.enrich.registry import DEFAULT_WANT, SourceRegistry, record_vendor_offer
from stockroom.enrich.schema import SOURCED_FIELDS, EnrichmentResult, Sourced
from stockroom.enrich.sites import SITE_EXTRACTORS
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Provenance, Purchase
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value
from stockroom.scrape.validate import validate_product

# Canonical field -> StagingCandidate attribute it fills. Only these simple text
# fields flow straight onto the M3 candidate; price/URL become a Purchase.
_CANDIDATE_FIELDS = {
    "mpn": "mpn",
    "manufacturer": "manufacturer",
    "description": "description",
}


def purchase_from_product_url(url: str, *, price_breaks=None, stock=None) -> Purchase:
    """A `Purchase` naming the DISTRIBUTOR the link points at, carrying its own part number.

    This used to be built inline as `Purchase(vendor="scrape", ...)`, with no part number at all.
    MEASURED on the owner's real library 2026-07-27: 85 of 158 records were filed that way, so
    every surface that groups or filters by vendor reported LCSC as zero while holding a perfectly
    good LCSC product url, its price ladder and its live stock. The owner asked *"why are all
    these missing their digikey and lcsc sourcing"* -- they were not missing, they were misfiled.

    `vendor` is the name a person uses ("LCSC"), never the mechanism that found it ("scrape").
    `part_number` is parsed from the url when it is a product page and left EMPTY when it is a
    search page: 20 of those records only ever resolved to a search, and a guessed part number is
    a wrong part.
    """
    return Purchase(
        vendor=vendor_from_url(url),
        part_number=distributor_part_number_from_url(url),
        url=url,
        price_breaks=list(price_breaks or []),
        stock=stock,
    )


def _copy_specs(candidate, result, overwrite: set[str]) -> None:
    """Carry everything the pull yielded onto the candidate: every enriched spec, the resolved
    package, the canonical procurement fields that have no other home, where each value came
    from, and every value a source offered and lost with.

    This is the hop the audited data used to die at - the candidate could hold specs and nothing
    else, so provenance and disagreements were computed and then dropped on the floor. Per-field
    throughout: an existing value is kept unless its group is opted into overwrite.
    product_url is a purchase-link mechanism, not a spec row.
    """
    take = "specs" in overwrite

    def put(key: str, value, sourced) -> None:
        key = normalize_spec_key(key)
        if not key:
            return
        if take or key not in candidate.specs:
            candidate.specs[key] = normalize_spec_value(value)
            if sourced is not None:
                candidate.enrichment[key] = {
                    "source": sourced.source, "confidence": sourced.confidence,
                }

    # `put` canonicalizes each label to the record's key-space BEFORE its dedup check, so an
    # extractor that emits a duplicated-label key updates the existing clean key instead of
    # adding a twin the persistence layer would then collapse.
    for label, value, sourced in spec_updates(result):
        put(label, value, sourced)
    for key, entries in conflict_entries(result).items():
        candidate.alternates.setdefault(key, [
            {"value": s.value, "source": s.source, "confidence": s.confidence} for s in entries
        ])


def fill_category(result: EnrichmentResult) -> None:
    """Derive a real component category for a scraped result that has none (A4: a pasted
    non-passive link left the category "Other"/blank). The distributor's own "Product Category"
    spec is the strongest signal ("Thick Film Resistors - SMD" -> Resistors), backed by the
    description; the shared keyword classifier maps it. An unrecognized category is left
    untouched (never a wrong guess), so the user still picks it in review."""
    if result.category and result.category != "Other":
        return

    # The distributor "Product Category" is the authoritative signal; classify from it ALONE
    # first, and only fall back to the description when it yields nothing. Blending them let a
    # description that merely NAMES another component ("resistor divider" on an IC) mis-steer the
    # category, so the two are tried in priority order, never joined.
    #
    # Within each tier, EVERY source's answer is considered, not just the one that won the slot
    # (owner, 2026-07-26: "find the BEST classification across sources rather than taking one and
    # giving up"). Only one distributor category fits in `specs`, and the displaced ones sit in
    # the conflict map - so which vendor happened to answer first decided whether a part could be
    # classified at all. DigiKey's "Circuit Protection" names no component kind while LCSC's "ESD
    # Protection Diodes / TVS Diodes" does, and the real library had the unclassifiable one in the
    # slot. The tiers stay ordered, so this widens the search without blending it.
    guess = _best_category(_classification_signals(result))
    if guess:
        result.category = guess


def _best_category(texts) -> str:
    """The first text that classifies to something real, or "" when none does.

    Shared by the ADD path (`fill_category`, on an EnrichmentResult) and the REBUILD path
    (`refile_category`, on a PartRecord) so the two lanes cannot disagree about what a part is.
    """
    from stockroom.ingest.naming import propose_category

    for text in texts:
        guess = propose_category(text)
        if guess != "Other":
            return guess
    return ""


def refile_category(record) -> str:
    """The category an UNCLASSIFIED record should be filed under, or "" to leave it alone.

    The record-shaped twin of `fill_category`. A part added before `9bcb033` kept "Other"
    forever: the add path learned to classify from the distributors' Product Category, and
    nothing re-derived it for a record already on disk.

    Same guard, and it is the important half: a record already filed somewhere real is NEVER
    touched. A vendor taxonomy is a suggestion for an unfiled part, never an override of a
    filing a person chose.
    """
    if record.category and record.category != "Other":
        return ""
    return _best_category(_record_classification_signals(record))


def _record_classification_signals(record):
    """Every text worth classifying a stored record from, most authoritative first: its
    distributor Product Category and every answer that lost that slot, then its description and
    the same. Mirrors `_classification_signals`, reading the record's `alternates` where the
    result reads its conflict maps - they hold the same losers."""
    seen: set[str] = set()

    def tier(primary, alternates):
        out = []
        for value in [primary, *[a.value for a in alternates]]:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out

    alternates = getattr(record, "alternates", {}) or {}
    yield from tier(record.specs.get("Product Category"),
                    alternates.get("Product Category", []))
    yield from tier(record.description, alternates.get("description", []))


def _classification_signals(result: EnrichmentResult):
    """Every text worth classifying from, most authoritative first: all sources' distributor
    Product Category, then all sources' description. Within a tier the value that won the slot
    leads, then the displaced answers in the order they were recorded. De-duplicated, because the
    conflict map records the winner alongside the loser."""
    seen: set[str] = set()

    def tier(primary, alternates):
        out = []
        for sourced in [primary, *alternates]:
            if sourced is None:
                continue
            text = str(sourced.value).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out

    yield from tier(result.specs.get("Product Category"),
                    result.spec_conflicts.get("Product Category", []))
    yield from tier(result.description, result.field_conflicts.get("description", []))


def _is_substantive(result: EnrichmentResult) -> bool:
    """True when a scrape pulled REAL part data, not just a lone description, so the result is
    worth caching AND its description is trustworthy. A blocked/challenge shell yields ONLY an
    OpenGraph/title description (plus maybe the product_url marker); EVERY other field checked here
    is set only from STRUCTURED product data (JSON-LD / next_data / microdata / a distributor
    spec table) that a challenge shell cannot produce, so any one of them marks a genuine page -
    including a manufacturer landing page that carries brand + name but no MPN yet."""
    if (result.mpn is not None or result.manufacturer is not None or result.package is not None
            or result.datasheet_url is not None or result.stock is not None
            or result.lifecycle is not None or result.lead_time is not None
            or result.price_breaks or result.dist_pns):
        return True
    return any(key != "product_url" for key in result.specs)


def _drop_thin_description(result: EnrichmentResult) -> None:
    """Honest degradation, vendor-agnostic backstop: a block/challenge/thin page yields ONLY a
    description - the anti-bot interstitial text ("Just a moment...", "Access to this page has
    been denied.") or an OpenGraph blurb off a challenge shell - and no real product data.
    Surfacing that as the part's description fabricates data, so a non-substantive result has its
    lone description dropped. The marker-level detector (camoufox `_looks_challenge`) is the first
    line; this catches ANY shell that slips past a specific marker, for any anti-bot vendor."""
    if result.description is not None and not _is_substantive(result):
        result.description = None


@dataclass
class ResolvedQuery:
    """What a user-supplied part number turned out to be. `resolved` distinguishes "a
    distributor confirmed this stock number" from "nothing was looked up, so the query is
    being used as-is" - two very different states that a bare string would flatten."""

    mpn: str
    query: str = ""
    vendor: str = ""
    product_url: str = ""
    resolved: bool = False


# A Mouser stock number is a 2-4 digit line prefix, a hyphen, then the manufacturer part
# ("595-TPD6E05U06RVZR", "81-GRM155R71C104KA88"). A DigiKey part number ends in one of its
# packaging suffixes. Deliberately narrow: a manufacturer part that merely CONTAINS a hyphen
# ("1N5819HW-7-F", "MCP4728-E/UN") must NOT be mistaken for a stock number, or a perfectly
# good MPN would be sent on a pointless lookup and reported unresolved.
_MOUSER_SKU_RE = re.compile(r"^\d{2,4}-[A-Za-z0-9][A-Za-z0-9./+_-]*$")
_DIGIKEY_PN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./+_-]*-(?:ND|CT-ND|TR-ND|DKR-ND)$")


def _looks_like_stock_number(query: str, vendor: str) -> bool:
    if vendor == "digikey":
        return bool(_DIGIKEY_PN_RE.match(query))
    # A DigiKey number can also carry a numeric prefix ("296-11601-1-ND"), so the DigiKey
    # shape is checked FIRST and wins; otherwise Mouser would claim it and miss.
    return bool(_MOUSER_SKU_RE.match(query)) and not _DIGIKEY_PN_RE.match(query)


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
    # A real place to buy from, so its ladder / stock / product page are kept under this
    # vendor key by the registry walk (see registry.record_vendor_offer). Lowercase: it is
    # a key, not a label.
    vendor_key = "lcsc"
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
        _drop_thin_description(result)  # never leak a challenge/thin shell's text as a description
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
        # A THIRD cache, keyed by the distributor stock number, holding only what that number
        # resolved to. Mouser's Search API is capped at 1000 calls/day and a register import
        # spends up to two per part, so without this a preview followed by the real import pays
        # the resolve half twice - ~660 calls for one 166-part list.
        self.resolve_cache = TtlCache(Path(cache_dir), prefix="resolve")
        self.fetcher = fetcher or HttpRenderedDomFetcher()
        self.limiter = limiter or SlidingWindowLimiter(limit=10, window=60.0)
        # The Mouser API has its OWN documented cap (~30/60), separate from the gentler
        # scraper budget, so it gets a dedicated limiter (lifted from KiCost's api_mouser).
        self.mouser_limiter = mouser_limiter or SlidingWindowLimiter(limit=30, window=60.0)
        self.mouser = mouser
        # Stored (not only handed to the registry) so the paste-a-link path can query the official
        # APIs directly, before the render, for a recognized Mouser/DigiKey product link.
        self.digikey = digikey
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
            hit = _result_from_cache(cached, category)
            # Classify the cache hit too. An install carries entries written BEFORE the MPN path
            # classified at all, whose stored category is "Other" beside a perfectly good Product
            # Category, and a cached answer must not serve that stale verdict for the whole TTL.
            fill_category(hit)
            return hit
        # One monotonic wrapper for the whole registry walk, so a later source's low local
        # pct (the datasheet leg after the scrape leg) never rewinds the bar.
        sink = monotonic(progress)
        result = self.registry.enrich(mpn, category,
                                      want=set(want) if want else set(DEFAULT_WANT),
                                      progress=sink)
        # The MPN path classifies exactly like the paste-a-link path. Without this the caller's
        # default ("Other", from the Add-A-Part form) survived every distributor answer, so a part
        # whose sources all said "ESD Protection Diodes / TVS Diodes" still landed in SR-Other and
        # emitted Category=Other into the Altium DbLib (owner, 2026-07-26, on the real library).
        # Before the cache write, so the classification is what gets stored.
        fill_category(result)
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
        _drop_thin_description(result)  # never leak a challenge/thin shell's text as a description

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

    def _distributor_adapters(self, vendor: str):
        """The enabled official-API adapters, the pasted link's OWN vendor FIRST so its fields
        (price/stock/the purchase link) win the per-field merge, then the other to fill the gaps a
        single distributor leaves (a Mouser link's missing datasheet comes from DigiKey)."""
        pairs = [
            (name, adapter)
            for name, adapter in (("mouser", self.mouser), ("digikey", self.digikey))
            if adapter is not None and getattr(adapter, "enabled", False)
        ]
        pairs.sort(key=lambda p: 0 if p[0] == vendor else 1)
        return pairs

    def _resolve_via_distributor_apis(self, vendor: str, token: str,
                                      progress=None) -> EnrichmentResult:
        """Resolve a distributor part token through the official Search APIs, no render. Queries
        the link's own vendor first, then the other, merging per-field. An empty result means
        neither API carried the part (or none is configured), so the caller renders the page."""
        display = {"mouser": "Mouser", "digikey": "DigiKey"}
        result = EnrichmentResult()
        for name, adapter in self._distributor_adapters(vendor):
            # Both APIs share the KiCost-derived Mouser limiter (paced against the ~30/min cap),
            # so a burst of adds never trips a distributor's rate limit.
            if self.mouser_limiter is not None:
                self.mouser_limiter.acquire()
            emit(progress, Stage.FETCHING, f"querying {display.get(name, name)}")
            try:
                partial = adapter.lookup(token)
            except Exception:  # noqa: BLE001 - an adapter must never break the paste path
                continue
            # Keep THIS vendor's own buy link, price ladder and live stock, so both survive even
            # though the merged result keeps a single primary of each. The pasted vendor's link is
            # set to the pasted url below. Same helper the registry walk uses, so the paste path
            # and the MPN path can never record per-vendor sourcing differently.
            record_vendor_offer(result, name, partial)
            result.merge_missing(partial)
        return result

    def extract_from_url(self, url: str, progress=None) -> EnrichmentResult:
        """Fill EVERYTHING a distributor product link exposes, from a URL alone (no candidate, no
        file): identity, price breaks, stock, datasheet, package, and the full parametric spec set.

        A recognized Mouser/DigiKey link resolves through the official Search API FIRST (fast and
        WAF-free), because rendering those Akamai-guarded pages is slow and usually blocked (the
        "Nothing was pulled" failure). Any other link, an unconfigured key, or an API miss falls
        through to the rendered-DOM fetcher (the stealth browser). Never raises: a blocked or dead
        page returns an empty result, honestly (spec 2.2)."""
        url = (url or "").strip()
        if not url:
            return EnrichmentResult()
        # A6: the same link returns the same result. A cache hit skips the (nondeterministic)
        # network fetch entirely, so repeat lookups are stable.
        cached = self.url_cache.get(url)
        if cached is not None:
            return _result_from_cache(cached, cached.get("category", ""))
        sink = monotonic(progress)
        # API-FIRST: a Mouser/DigiKey product link resolves through the official Search API instead
        # of rendering the Akamai-guarded page. Only a recognized distributor link with an enabled
        # key AND a substantive answer takes this path; everything else renders below, unchanged.
        parsed = distributor_mpn_from_url(url)
        if parsed is not None:
            vendor, token = parsed
            api = self._resolve_via_distributor_apis(vendor, token, sink)
            if _is_substantive(api):
                # the pasted link is the user's purchase link: it wins the product_url slot over
                # the API's own ProductDetailUrl (a Mouser paste stays that Mouser link).
                api.product_url = Sourced(url, vendor, "high")
                api.specs["product_url"] = Sourced(url, vendor, "high")
                # the pasted vendor's buy link is the EXACT link the user pasted (its qs token and
                # all), not the API's canonical rewrite; the other vendor keeps its API link.
                api.dist_urls[vendor] = url
                fill_category(api)
                self.url_cache.put(url, _result_to_cache(api))
                return api
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
        # AFTER fill_category, so a real thin page's category is still derived from its
        # description before a non-substantive result's lone (challenge/SEO) description is dropped.
        # product_url is excluded from _is_substantive, so adding it above never masks a thin shell.
        _drop_thin_description(result)
        # Cache ONLY a substantive pull, so a one-off thin or Akamai-blocked fetch (which yields
        # just a description) never becomes the cached answer and a retry can still get the page.
        if _is_substantive(result):
            self.url_cache.put(url, _result_to_cache(result))
        return result

    def resolve_to_mpn(self, query: str) -> ResolvedQuery:
        """Turn a DISTRIBUTOR STOCK NUMBER into the manufacturer part number before anything
        else runs.

        A sourcing document names parts the way its distributor does - the owner's Component
        Register carries a Mouser stock number for 164 of its 169 orderable line items - and
        every other leg of the registry (the passive fast path, LCSC, the scrape, the datasheet
        follow) can only match a MANUFACTURER part. Measured on the real APIs: enriching
        `595-TPD6E05U06RVZR` directly yielded 37 specs, no datasheet and an LCSC *search* URL as
        its purchase link (incomplete); resolving it to `TPD6E05U06RVZR` first yielded 91 specs,
        a fetched datasheet PDF and a real product page - a complete part.

        A query that is not a stock number costs NO call: it is already an MPN.
        """
        q = (query or "").strip()
        if not q:
            return ResolvedQuery(mpn="", query=q)
        cached = self.resolve_cache.get(q)
        if cached is not None:
            return ResolvedQuery(
                mpn=str(cached.get("mpn", "")), query=q,
                vendor=str(cached.get("vendor", "")),
                product_url=str(cached.get("product_url", "")),
                resolved=True,
            )
        for vendor, adapter in (("mouser", self.mouser), ("digikey", self.digikey)):
            if not _looks_like_stock_number(q, vendor):
                continue
            if adapter is None or not getattr(adapter, "enabled", False):
                continue
            self.mouser_limiter.acquire()
            result = adapter.lookup(q)
            if result.mpn is None or not str(result.mpn.value).strip():
                continue
            resolved = ResolvedQuery(
                mpn=str(result.mpn.value).strip(),
                query=q,
                vendor=vendor,
                product_url=str(result.product_url.value) if result.product_url else "",
                resolved=True,
            )
            # Cache the ANSWER only, never a miss: a miss is usually a transient network or
            # rate-limit failure, and remembering it would make one bad minute stick for the
            # whole TTL. Disk-backed, not in-memory, because the pipeline is rebuilt per request
            # so a memo would cache nothing across the preview-then-import pair this is for.
            self.resolve_cache.put(q, {
                "mpn": resolved.mpn, "vendor": vendor, "product_url": resolved.product_url,
            })
            return resolved
        # Not resolvable (or not a stock number at all): the query stands as the MPN, and
        # `resolved` says which of those two it was, so a caller can report the difference
        # instead of guessing why a part came back thin.
        return ResolvedQuery(mpn=q, query=q)

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

        # The category the distributors' own taxonomy implies. `fill_category` derives it onto
        # the RESULT, the enrich route serialises it, and the frontend applies it - so the Add
        # form has always filed parts correctly while this seam silently did not. Any headless
        # caller therefore filed every part under "Other". "Other" is the form's default, i.e.
        # unfiled; a real category is a decision someone made and is never overwritten.
        if result.category and result.category != "Other":
            if not candidate.category or candidate.category == "Other" or "category" in overwrite:
                candidate.category = result.category

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
            candidate.purchase = [purchase_from_product_url(
                str(product_url.value),
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
        from stockroom.enrich.datasheet import looks_like_pdf
        from stockroom.enrich.schema import normalize_mpn

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
    vendor_key = "mouser"

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
    vendor_key = "digikey"

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
        # EVERY single-valued canonical field, enumerated from the schema itself rather than
        # retyped here. A hand-written list has now silently dropped new fields TWICE - the M7d
        # procurement fields (fixed in 4255471) and then the v2 import fields
        # (country_of_origin / tariff_rate), each surviving one fresh lookup and vanishing on
        # every cache hit after it. Iterating SOURCED_FIELDS makes that class of bug
        # impossible: a field added to the schema is cached by construction.
        **{name: s(getattr(r, name)) for name in SOURCED_FIELDS},
        "dist_pns": dict(r.dist_pns),
        "dist_urls": dict(r.dist_urls),
        "dist_price_breaks": {
            k: [{"qty": p.qty, "price": p.price, "currency": p.currency} for p in v]
            for k, v in r.dist_price_breaks.items()
        },
        "dist_stock": dict(r.dist_stock),
        "price_breaks": [{"qty": b.qty, "price": b.price, "currency": b.currency} for b in r.price_breaks],
        "specs": {k: {"value": v.value, "source": v.source, "confidence": v.confidence} for k, v in r.specs.items()},
        # every kept disagreement (a cache hit must not silently resolve a conflict), for the
        # spec bag AND for the single-valued fields
        "spec_conflicts": {
            k: [{"value": v.value, "source": v.source, "confidence": v.confidence} for v in vs]
            for k, vs in r.spec_conflicts.items()
        },
        "field_conflicts": {
            k: [{"value": v.value, "source": v.source, "confidence": v.confidence} for v in vs]
            for k, vs in r.field_conflicts.items()
        },
    }


def _result_from_cache(d: dict, category: str) -> EnrichmentResult:
    from stockroom.enrich.schema import PriceBreak

    def s(v):
        return None if v is None else Sourced(v["value"], v["source"], v["confidence"])
    r = EnrichmentResult(category=d.get("category", category))
    # Read back exactly the set _result_to_cache writes, from the same single source of truth,
    # so the two halves can never drift apart (see the note there).
    for name in SOURCED_FIELDS:
        setattr(r, name, s(d.get(name)))
    r.dist_pns = dict(d.get("dist_pns", {}))
    r.dist_urls = dict(d.get("dist_urls", {}))
    r.dist_price_breaks = {
        k: [PriceBreak(qty=int(b["qty"]), price=float(b["price"]), currency=b.get("currency", "USD"))
            for b in v]
        for k, v in d.get("dist_price_breaks", {}).items()
    }
    r.dist_stock = dict(d.get("dist_stock", {}))
    r.price_breaks = [PriceBreak(**b) for b in d.get("price_breaks", [])]
    r.specs = {k: Sourced(v["value"], v["source"], v["confidence"]) for k, v in d.get("specs", {}).items()}
    r.spec_conflicts = {
        k: [Sourced(v["value"], v["source"], v["confidence"]) for v in vs]
        for k, vs in d.get("spec_conflicts", {}).items()
    }
    r.field_conflicts = {
        k: [Sourced(v["value"], v["source"], v["confidence"]) for v in vs]
        for k, vs in d.get("field_conflicts", {}).items()
    }
    return r
