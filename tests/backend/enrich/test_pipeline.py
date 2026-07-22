from pathlib import Path

from stockroom.enrich.datasheet import extract_datasheet_specs
from stockroom.enrich.pipeline import EnrichmentPipeline, ScrapeSource
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.ingest.staging import StagingCandidate

FIX = Path(__file__).parent / "fixtures"


class _StubFetcher:
    """A RenderedDomFetcher that returns a saved fixture, no network."""
    def __init__(self, html):
        self._html = html
        self.urls = []

    def rendered_html(self, url, timeout=20.0):
        from stockroom.enrich.fetch import FetchResult
        self.urls.append(url)
        return FetchResult(url, 200, self._html, self._html.encode(), "text/html", url)


class _SequenceFetcher:
    """Returns a different page on each successive call, to exercise fetch-to-fetch variance
    (the A6 determinism concern: a link that pulls fully once and thin the next time)."""
    def __init__(self, *pages):
        self._pages = list(pages)
        self.calls = 0

    def rendered_html(self, url, timeout=20.0):
        from stockroom.enrich.fetch import FetchResult
        html = self._pages[min(self.calls, len(self._pages) - 1)]
        self.calls += 1
        return FetchResult(url, 200, html, html.encode(), "text/html", url)


class _NoWaitLimiter:
    def acquire(self):
        pass


class _NullJlc:
    """A jlcsearch client that always misses, so LcscSource is inert in tests that
    exercise the scrape/datasheet path and assert exact fetch counts (an injected
    stub fetcher bypasses the conftest network guard, so LcscSource would otherwise
    add a jlcsearch GET)."""

    def search(self, mpn):
        return None


def _candidate(**kw):
    base = dict(
        vendor="snapeda",
        symbol_lib_path=Path("/tmp/sym.kicad_sym"),
        symbol_name="TESTPART",
        footprint_variants=[Path("/tmp/a.kicad_mod")],
        entry_name="TPS62130RGTR",
        display_name="TPS62130",
        category="ICs",
    )
    base.update(kw)
    return StagingCandidate(**base)


def test_scrape_source_extracts_from_the_rendered_dom(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    src = ScrapeSource(
        fetcher=_StubFetcher(html),
        limiter=_NoWaitLimiter(),
        url_for=lambda mpn, cat: "https://www.lcsc.com/product-detail/C1.html",
    )
    r = src.enrich("TPS62130RGTR", "ICs", remaining={"mpn", "manufacturer"})
    assert r.mpn.value == "TPS62130RGTR"
    assert r.manufacturer.value == "Texas Instruments"


def test_enrich_candidate_fills_only_empty_fields(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "cache",
        fetcher=_StubFetcher(html),
        limiter=_NoWaitLimiter(),
    )
    # candidate already has a manufacturer; enrichment must NOT overwrite it
    c = _candidate(manufacturer="MyCorp", mpn="")
    pipe.enrich_candidate(c)
    assert c.manufacturer == "MyCorp"   # preserved (per-field opt-in off)
    assert c.mpn == "TPS62130RGTR"       # was empty, filled


def test_enrich_candidate_overwrite_is_per_field_opt_in(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(html),
                              limiter=_NoWaitLimiter())
    c = _candidate(manufacturer="MyCorp")
    pipe.enrich_candidate(c, overwrite={"manufacturer"})
    assert c.manufacturer == "Texas Instruments"  # explicitly opted in


def test_enrich_candidate_total_miss_leaves_it_untouched(tmp_path):
    empty_html = "<html><head></head><body></body></html>"
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(empty_html),
                              limiter=_NoWaitLimiter())
    c = _candidate(mpn="KEEP", manufacturer="KEEP")
    pipe.enrich_candidate(c)
    assert c.mpn == "KEEP" and c.manufacturer == "KEEP"  # never blocks, never clobbers


def test_enrich_result_is_cached_and_not_refetched(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    fetcher = _StubFetcher(html)
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=fetcher,
                              limiter=_NoWaitLimiter())
    pipe.enrich("TPS62130RGTR", "ICs")
    n_first = len(fetcher.urls)
    pipe.enrich("TPS62130RGTR", "ICs")  # second call served from cache
    assert len(fetcher.urls) == n_first  # no additional fetch


def test_cache_round_trips_the_procurement_fields():  # M7d: lifecycle/lead/product/dist P/N
    from stockroom.enrich.pipeline import _result_from_cache, _result_to_cache

    r = EnrichmentResult(category="ICs")
    r.mpn = Sourced("TPS62130RGTR", "mouser", "high")
    r.lifecycle = Sourced("NRND", "mouser", "high")
    r.lead_time = Sourced("16 Weeks", "mouser", "high")
    r.product_url = Sourced("http://x/p", "mouser", "high")
    r.dist_pns = {"mouser": "595-TPS62130RGTR"}
    back = _result_from_cache(_result_to_cache(r), "ICs")
    # Without persisting these, a cache hit would silently drop procurement risk + lead.
    assert back.lifecycle.value == "NRND"
    assert back.lead_time.value == "16 Weeks"
    assert back.product_url.value == "http://x/p"
    assert back.dist_pns == {"mouser": "595-TPS62130RGTR"}


_MOUSER_LIKE_HTML = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Product","sku":"667-ERJ-P03F1101V",'
    '"mpn":"ERJ-P03F1101V","brand":{"name":"Panasonic"},"description":"1.1k 0.2W res",'
    '"datasheet":"https://industrial.panasonic.com/ds.pdf",'
    '"offers":{"@type":"Offer","price":"0.10","priceCurrency":"USD",'
    '"availability":"http://schema.org/InStock","inventoryLevel":5000}}'
    "</script></head><body><table>"
    "<tr><td>Resistance</td><td>1.1 kOhm</td></tr>"
    "<tr><td>Tolerance</td><td>1%</td></tr>"
    "<tr><td>Power</td><td>0.2 W</td></tr>"
    "</table></body></html>"
)


def test_pasted_product_url_carries_every_spec_to_the_candidate_and_staged_part(tmp_path):
    # The owner's flow: paste a distributor link -> autofill EVERYTHING. The rich specs
    # a page yields must land on the candidate AND survive into the staged part (they
    # were previously extracted then discarded because the candidate had no spec bag).
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "c", fetcher=_StubFetcher(_MOUSER_LIKE_HTML),
        limiter=_NoWaitLimiter(), http_fetcher=_StubHttpFetcher(mode="pdf"),
        jlcsearch=_NullJlc(),
    )
    from stockroom.model.part import Purchase

    c = _candidate(mpn="", manufacturer="", description="")
    c.purchase = [Purchase(vendor="Mouser",
                           url="https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V")]
    pipe.enrich_from_product_url(c, c.purchase[0].url)

    assert c.mpn == "ERJ-P03F1101V" and c.manufacturer == "Panasonic"
    assert c.specs["Resistance"] == "1.1 kOhm"
    assert c.specs["Tolerance"] == "1%"
    assert c.specs["Power"] == "0.2 W"
    # and the specs survive the hand-off to the committable staged part
    c.symbol_lib_path = FIX / "nope.kicad_sym"  # to_staged_part only needs the paths set
    c.footprint_variants = [FIX / "fp.kicad_mod"]
    staged = c.to_staged_part()
    assert staged.specs["Resistance"] == "1.1 kOhm"


def test_extract_from_url_autofills_everything_from_a_mouser_page(tmp_path):
    # The owner's headline flow: paste a Mouser URL alone -> get EVERYTHING (identity,
    # price, datasheet, package, and the full parametric spec table) with no file.
    html = (FIX / "mouser_product.html").read_text(encoding="utf-8")
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "c", fetcher=_StubFetcher(html),
        limiter=_NoWaitLimiter(), http_fetcher=_StubHttpFetcher(mode="pdf"),
        jlcsearch=_NullJlc(),
    )
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V"
    )
    assert r.mpn.value == "ERJ-P03F1101V"
    assert r.manufacturer.value == "Panasonic"
    assert r.price_breaks and r.price_breaks[0].price > 0
    assert r.datasheet_url is not None
    assert r.package.value == "0603 (1608 Metric)"
    assert r.specs["Resistance"].value == "1.1 kOhms"
    assert r.specs["Tolerance"].value == "±1%"
    assert "product_url" in r.specs


def test_extract_from_url_is_empty_on_a_blocked_page(tmp_path):
    # A 403/challenge page (what a plain HTTP client gets from Mouser) yields nothing,
    # honestly - never a crash, never invented data.
    class _Dead:
        def rendered_html(self, url, timeout=20.0):
            from stockroom.enrich.errors import EnrichError
            raise EnrichError("akamai 403")

    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_Dead(),
                              limiter=_NoWaitLimiter(), jlcsearch=_NullJlc())
    r = pipe.extract_from_url("https://www.mouser.com/x")
    assert r.mpn is None and not r.specs


_THIN = "<html><head><meta property='og:description' content='blocked challenge page'></head></html>"


def test_extract_from_url_is_deterministic_via_the_url_cache(tmp_path):
    # A6: once a link pulls a substantive result it is cached, so a SECOND lookup returns the
    # SAME full result and never re-fetches - even if the page would now serve a thin/blocked body.
    full = (FIX / "mouser_product.html").read_text(encoding="utf-8")
    fetcher = _SequenceFetcher(full, _THIN)
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=fetcher,
                              limiter=_NoWaitLimiter(), http_fetcher=_StubHttpFetcher(mode="pdf"),
                              jlcsearch=_NullJlc())
    url = "https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V"
    r1 = pipe.extract_from_url(url)
    r2 = pipe.extract_from_url(url)
    assert r1.mpn.value == "ERJ-P03F1101V"
    assert r2.mpn is not None and r2.mpn.value == r1.mpn.value  # identical, not the thin page
    assert fetcher.calls == 1  # the second lookup hit the cache; no re-fetch


def test_a_thin_or_blocked_result_is_never_cached(tmp_path):
    # A thin/blocked first fetch must NOT poison the cache: the retry re-fetches and can still
    # get the full page (so a one-off block never becomes the permanent answer).
    full = (FIX / "mouser_product.html").read_text(encoding="utf-8")
    fetcher = _SequenceFetcher(_THIN, full)
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=fetcher,
                              limiter=_NoWaitLimiter(), http_fetcher=_StubHttpFetcher(mode="pdf"),
                              jlcsearch=_NullJlc())
    url = "https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V"
    r1 = pipe.extract_from_url(url)
    r2 = pipe.extract_from_url(url)
    assert r1.mpn is None  # thin -> not substantive
    assert r2.mpn is not None and r2.mpn.value == "ERJ-P03F1101V"  # retry got the full page
    assert fetcher.calls == 2  # thin was not cached, so the retry really re-fetched


def test_datasheet_field_is_preferred_over_a_scrape_field():
    # datasheet gives the MPN at high confidence; a scrape gives a WRONG MPN.
    ds = EnrichmentResult(category="ICs")
    ds.mpn = Sourced("TPS62130RGTR", "datasheet", "high")
    scrape = EnrichmentResult(category="ICs")
    scrape.mpn = Sourced("WRONG-NEAR-MATCH", "scrape", "low")
    # datasheet merged FIRST wins (the registry orders datasheet ahead by trust)
    ds.merge_missing(scrape)
    assert ds.mpn.value == "TPS62130RGTR"
    assert ds.mpn.source == "datasheet"


def test_extract_datasheet_specs_end_to_end_from_fixture():
    r = extract_datasheet_specs(FIX / "sample_datasheet.pdf", known_mpn="TPS62130RGTR")
    assert r.package.value == "VQFN-16"
    assert r.manufacturer.value == "Texas Instruments"


# --- datasheet wiring: the pipeline actually follows a scraped datasheet_url,
# fetches the real PDF, extracts specs, and stores it on the candidate. Regression
# lock: the datasheet source was previously a hollow stub never in the registry. ---

_LD_WITH_DATASHEET = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Product","mpn":"TPS62130RGTR",'
    '"brand":{"name":"Texas Instruments"},"description":"buck",'
    '"datasheet":"https://ti.com/lit/ds/tps62130.pdf"}'
    "</script></head></html>"
)


class _StubHttpFetcher:
    """An HttpFetcher stub for the datasheet GET. Serves the sample PDF, or an HTML
    'unavailable' wrapper, or raises, so the never-block paths are all exercised."""

    def __init__(self, mode="pdf"):
        self._mode = mode
        self.gets = []

    def get(self, url, referer="", timeout=15.0):
        from stockroom.enrich.errors import EnrichError
        from stockroom.enrich.fetch import FetchResult

        self.gets.append(url)
        if self._mode == "raise":
            raise EnrichError("transport dead")
        if self._mode == "html":
            body = b"<html><body>unavailable</body></html>"
            return FetchResult(url, 200, body.decode(), body, "text/html", url)
        data = (FIX / "sample_datasheet.pdf").read_bytes()
        return FetchResult(url, 200, data.decode("latin-1"), data, "application/pdf", url)


class _UrlFetcher:
    """A RenderedDomFetcher that serves different HTML per URL (a substring match),
    so a test can prove WHICH url was actually fetched, not just that some fetch
    happened."""
    def __init__(self, by_url):
        self._by_url = by_url
        self.urls = []

    def rendered_html(self, url, timeout=20.0):
        from stockroom.enrich.fetch import FetchResult
        self.urls.append(url)
        html = next((h for pat, h in self._by_url.items() if pat in url), "<html></html>")
        return FetchResult(url, 200, html, html.encode(), "text/html", url)


_LD_PRODUCT_WITH_PRICE = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Product","mpn":"TPS62130RGTR",'
    '"brand":{"name":"Texas Instruments"},"description":"3A step-down converter",'
    '"offers":{"@type":"Offer","price":"2.50","priceCurrency":"USD"}}'
    "</script></head></html>"
)


def test_enrich_candidate_scrapes_the_pasted_purchase_url(tmp_path):
    """The owner's Autofill flow: a candidate carrying only a purchase link (no MPN)
    fills its identity by fetching THAT product page directly, not an MPN search."""
    from stockroom.model.part import Purchase

    purchase_url = "https://www.mouser.com/ProductDetail/xyz"
    fetcher = _UrlFetcher({"mouser.com/ProductDetail": _LD_PRODUCT_WITH_PRICE})
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "c", fetcher=fetcher, limiter=_NoWaitLimiter(),
    )
    c = _candidate(
        entry_name="", display_name="Widget", mpn="", manufacturer="", description="",
        purchase=[Purchase(vendor="Mouser", url=purchase_url)],
    )
    pipe.enrich_candidate(c)
    # the exact pasted URL was fetched (not an LCSC search built from a blank MPN)
    assert any("mouser.com/ProductDetail/xyz" in u for u in fetcher.urls)
    # identity is filled straight from the scraped product page
    assert c.mpn == "TPS62130RGTR"
    assert c.manufacturer == "Texas Instruments"
    assert c.description == "3A step-down converter"
    # the pasted purchase link is preserved (vendor + url) and gains the scraped price
    assert c.purchase[0].url == purchase_url
    assert c.purchase[0].vendor == "Mouser"
    assert c.purchase[0].price_breaks == [{"qty": 1, "price": 2.5}]


def test_pipeline_follows_scraped_datasheet_url_and_extracts_specs(tmp_path):
    http = _StubHttpFetcher(mode="pdf")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http, jlcsearch=_NullJlc())
    r = pipe.enrich("TPS62130RGTR", "ICs")
    assert r.datasheet_url.value == "https://ti.com/lit/ds/tps62130.pdf"
    # the DatasheetSource followed the URL, fetched the real PDF, extracted the package
    assert r.package.value == "VQFN-16"
    assert r.package.source == "datasheet"
    assert http.gets == ["https://ti.com/lit/ds/tps62130.pdf"]  # the PDF was fetched


def test_enrich_candidate_fetches_and_stores_the_datasheet_pdf(tmp_path):
    http = _StubHttpFetcher(mode="pdf")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http, jlcsearch=_NullJlc())
    c = _candidate(mpn="TPS62130RGTR", datasheet_path=None)
    pipe.enrich_candidate(c)
    # the passport's datasheet requirement is now satisfiable: a real stored PDF
    assert c.datasheet_path is not None
    assert c.datasheet_path.read_bytes().startswith(b"%PDF-")
    # the PDF is fetched once, not re-downloaded by fetch_and_store after the source
    assert len(http.gets) == 1


def test_enrich_candidate_dead_datasheet_never_blocks(tmp_path):
    http = _StubHttpFetcher(mode="html")  # datasheet link serves an HTML wrapper
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http)
    c = _candidate(mpn="TPS62130RGTR", manufacturer="", datasheet_path=None)
    pipe.enrich_candidate(c)
    # an HTML "unavailable" datasheet is refused: no PDF stored, but the rest is filled
    assert c.datasheet_path is None
    assert c.manufacturer == "Texas Instruments"  # scrape fields never blocked


def test_enrich_candidate_raising_datasheet_fetch_never_crashes(tmp_path):
    http = _StubHttpFetcher(mode="raise")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http)
    c = _candidate(mpn="TPS62130RGTR", datasheet_path=None)
    pipe.enrich_candidate(c)  # must not raise
    assert c.datasheet_path is None


def test_datasheet_url_survives_the_cache_round_trip(tmp_path):
    http = _StubHttpFetcher(mode="pdf")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http)
    pipe.enrich("TPS62130RGTR", "ICs")
    r2 = pipe.enrich("TPS62130RGTR", "ICs")  # from cache
    assert r2.datasheet_url.value == "https://ti.com/lit/ds/tps62130.pdf"
    assert r2.package.value == "VQFN-16"  # datasheet-extracted package cached too


def test_mouser_source_paces_the_api_with_its_limiter():
    # The Mouser API path must be rate-limited (the ban scenario the KiCost limiter exists to
    # prevent): a limiter of 2/window must sleep on the 3rd lookup inside the window. Before the
    # fix _MouserSource had no limiter and called the adapter unthrottled.
    from stockroom.enrich.pipeline import _MouserSource
    from stockroom.enrich.ratelimit import SlidingWindowLimiter

    class _Adapter:
        def lookup(self, mpn):
            return None

    t = [0.0]
    slept: list[float] = []

    def _sleep(s):
        slept.append(s)
        t[0] += s

    lim = SlidingWindowLimiter(limit=2, window=60.0, clock=lambda: t[0], sleeper=_sleep)
    src = _MouserSource(_Adapter(), lim)
    for _ in range(3):
        src.enrich("STM32", "ICs", set())
    assert slept, "the 3rd Mouser lookup within the window must sleep (be rate-limited)"


def test_copy_specs_normalizes_label_no_duplicated_twin():
    # F2 review regression: an extractor that still emits the raw duplicated-label key
    # must update the record's existing CLEAN key, never add a twin the persistence
    # layer then silently collapses (dropping a value).
    from stockroom.enrich.pipeline import _copy_specs
    from stockroom.enrich.schema import EnrichmentResult, Sourced
    from stockroom.model.part import PartRecord

    twin = "Factory Pack Quantity: Factory Pack Quantity"
    cand = PartRecord(id="x", display_name="X", category="ICs", specs={"Factory Pack Quantity": "100"})
    result = EnrichmentResult()
    result.specs[twin] = Sourced("999", "mouser_web", "medium")
    # default merge (specs not opted into overwrite): existing clean key kept, no twin
    _copy_specs(cand, result, set())
    assert cand.specs["Factory Pack Quantity"] == "100"
    assert twin not in cand.specs
    # overwrite updates the clean key in place, still no twin
    _copy_specs(cand, result, {"specs"})
    assert cand.specs["Factory Pack Quantity"] == "999"
    assert twin not in cand.specs


def test_pipeline_uses_digikey_adapter_as_a_source(tmp_path):
    from stockroom.enrich.pipeline import EnrichmentPipeline
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class FakeDigiKey:
        enabled = True

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.lifecycle = Sourced("Active", "digikey", "high")
            return r

    pipe = EnrichmentPipeline(tmp_path, digikey=FakeDigiKey())
    # no scrape/LCSC hit for this junk MPN, so the DigiKey source is what fills lifecycle
    result = pipe.enrich("ZZZ-NO-SUCH-PART", "ICs")
    assert result.lifecycle is not None and result.lifecycle.value == "Active"


def test_extract_from_url_never_leaks_a_challenge_shell_as_description(tmp_path):
    # A challenge shell (Cloudflare "Just a moment...") whose only extractable field is an
    # og:description must NOT surface that text as the part description - honest degradation, the
    # vendor-agnostic backstop below the marker-level detector.
    from stockroom.enrich.fetch import FetchResult
    from stockroom.enrich.pipeline import EnrichmentPipeline

    class ChallengeFetcher:
        def rendered_html(self, url, **kw):
            html = ('<html><head><meta property="og:description" '
                    'content="Just a moment..."></head><body></body></html>')
            return FetchResult(url=url, status=200, text=html, content=b"",
                               content_type="text/html", final_url=url)

    pipe = EnrichmentPipeline(tmp_path, fetcher=ChallengeFetcher())
    result = pipe.extract_from_url("https://www.digikey.com/en/products/detail/x/Y/1")
    assert result.description is None   # the challenge text is not fabricated into a description
    assert result.mpn is None           # nothing real was pulled


def test_extract_from_url_keeps_a_real_description_with_manufacturer_but_no_mpn(tmp_path):
    # A real manufacturer/landing page whose JSON-LD carries brand + name but no MPN/specs is
    # substantive - manufacturer is structured-only (a challenge shell can't produce it) - so its
    # real product description must be KEPT, not dropped as if it were a challenge shell (F1).
    from stockroom.enrich.fetch import FetchResult
    from stockroom.enrich.pipeline import EnrichmentPipeline

    class RealPageFetcher:
        def rendered_html(self, url, **kw):
            html = ('<script type="application/ld+json">{"@type":"Product",'
                    '"name":"BQ24074RGTT Battery Charger IC",'
                    '"brand":{"@type":"Brand","name":"Texas Instruments"}}</script>')
            return FetchResult(url=url, status=200, text=html, content=b"",
                               content_type="text/html", final_url=url)

    pipe = EnrichmentPipeline(tmp_path, fetcher=RealPageFetcher())
    result = pipe.extract_from_url("https://www.ti.com/product/BQ24074")
    assert result.manufacturer is not None and result.manufacturer.value == "Texas Instruments"
    assert result.description is not None and "BQ24074RGTT" in result.description.value


# --- API-first paste-a-link path (Mouser/DigiKey are Akamai-guarded; the official APIs answer
# --- the exact part in one call, so a recognized distributor link resolves through them and
# --- never renders the blocked page). ---------------------------------------------------------


class _RaisingFetcher:
    """A render fetcher that MUST NOT be called: the API path resolves without any render."""

    def rendered_html(self, url, timeout=20.0, on_stage=None):
        raise AssertionError("the render path was taken; the official API should have resolved")


def _mouser_full():
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

    r = EnrichmentResult()
    r.mpn = Sourced("TPD6E05U06RVZR", "mouser", "high")
    r.manufacturer = Sourced("Texas Instruments", "mouser", "high")
    r.description = Sourced("ESD Protection Diodes / TVS Diodes 6-CH lo cap", "mouser", "high")
    r.stock = Sourced(12054, "mouser", "high")
    r.price_breaks = [PriceBreak(qty=1, price=0.5)]
    return r


class _FakeMouser:
    enabled = True

    def __init__(self, result):
        self._r = result
        self.seen = []

    def lookup(self, mpn):
        self.seen.append(mpn)
        return self._r


def test_paste_mouser_link_resolves_via_the_official_api_without_rendering(tmp_path):
    # The reported bug: pasting a Mouser link rendered the Akamai-guarded page and returned
    # "Nothing was pulled". With a Mouser key configured it now resolves through the official
    # API - fast, WAF-free - and never touches the browser render.
    mouser = _FakeMouser(_mouser_full())
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_RaisingFetcher(),
                              mouser=mouser, jlcsearch=_NullJlc())
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Texas-Instruments/TPD6E05U06RVZR?qs=x"
    )
    assert r.mpn.value == "TPD6E05U06RVZR"
    assert r.manufacturer.value == "Texas Instruments"
    assert r.stock.value == 12054
    assert r.price_breaks and r.price_breaks[0].price > 0
    assert mouser.seen == ["TPD6E05U06RVZR"]  # the MPN parsed from the URL drove the API
    # the pasted link is preserved as the purchase link
    assert r.specs["product_url"].value.startswith("https://www.mouser.com/")


def test_paste_mouser_link_merges_digikey_datasheet_and_specs(tmp_path):
    # Mouser gives identity/price/stock but no datasheet for this part; DigiKey fills the
    # datasheet + electrical parametrics. Both official APIs, merged, from one pasted link.
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    mouser = _FakeMouser(_mouser_full())  # carries no datasheet_url

    dk = EnrichmentResult()
    dk.datasheet_url = Sourced("https://www.ti.com/lit/gpn/tpd6e05u06.pdf", "digikey", "high")
    dk.specs["Voltage - Clamping (Max) @ Ipp"] = Sourced("14V", "digikey", "high")

    class _FakeDigiKey:
        enabled = True

        def lookup(self, mpn):
            return dk

    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_RaisingFetcher(),
                              mouser=mouser, digikey=_FakeDigiKey(), jlcsearch=_NullJlc())
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Texas-Instruments/TPD6E05U06RVZR"
    )
    assert r.price_breaks  # from Mouser
    assert r.stock.value == 12054  # from Mouser
    assert r.datasheet_url.value.endswith(".pdf")  # filled by DigiKey (Mouser had none)
    assert r.specs["Voltage - Clamping (Max) @ Ipp"].value == "14V"  # DigiKey parametric


def test_paste_digikey_link_resolves_via_api_using_the_path_mpn(tmp_path):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    dk = EnrichmentResult()
    dk.mpn = Sourced("TPD6E05U06RVZR", "digikey", "high")
    dk.datasheet_url = Sourced("https://www.ti.com/lit/gpn/tpd6e05u06.pdf", "digikey", "high")
    seen = []

    class _FakeDigiKey:
        enabled = True

        def lookup(self, mpn):
            seen.append(mpn)
            return dk

    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_RaisingFetcher(),
                              digikey=_FakeDigiKey(), jlcsearch=_NullJlc())
    r = pipe.extract_from_url(
        "https://www.digikey.com/en/products/detail/texas-instruments/TPD6E05U06RVZR/2094564"
    )
    assert r.mpn.value == "TPD6E05U06RVZR"
    assert seen == ["TPD6E05U06RVZR"]  # parsed from the middle path segment


def test_paste_link_captures_both_distributor_buy_links(tmp_path):
    # The owner's ask: since we call BOTH APIs, store BOTH the Mouser and DigiKey buy links (and
    # each vendor's own order number) on the part, not only the pasted link.
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    m = _mouser_full()
    m.product_url = Sourced("https://www.mouser.com/ProductDetail/x", "mouser", "high")
    m.dist_pns["mouser"] = "595-TPD6E05U06RVZR"

    class _FakeDigiKey:
        enabled = True

        def lookup(self, mpn):
            r = EnrichmentResult()
            r.product_url = Sourced(
                "https://www.digikey.com/en/products/detail/ti/TPD6E05U06RVZR/1", "digikey", "high"
            )
            r.dist_pns["digikey"] = "296-39349-2-ND"
            return r

    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_RaisingFetcher(),
                              mouser=_FakeMouser(m), digikey=_FakeDigiKey(), jlcsearch=_NullJlc())
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Texas-Instruments/TPD6E05U06RVZR"
    )
    assert r.dist_urls["mouser"].startswith("https://www.mouser.com/")
    assert r.dist_urls["digikey"].startswith("https://www.digikey.com/")
    assert set(r.dist_pns) == {"mouser", "digikey"}


def test_dist_urls_round_trip_through_the_cache():
    # both buy links must survive caching, so a re-looked-up link keeps both distributors.
    from stockroom.enrich.pipeline import _result_from_cache, _result_to_cache
    from stockroom.enrich.schema import EnrichmentResult

    r = EnrichmentResult()
    r.dist_urls = {"mouser": "https://m/x", "digikey": "https://d/y"}
    back = _result_from_cache(_result_to_cache(r), "")
    assert back.dist_urls == {"mouser": "https://m/x", "digikey": "https://d/y"}


def test_paste_link_falls_back_to_render_when_the_api_misses(tmp_path):
    # If the official API has no data (a miss, or the part is not carried), the paste path still
    # falls back to rendering the page - no regression for a link the API cannot resolve.
    from stockroom.enrich.schema import EnrichmentResult

    class _MissMouser:
        enabled = True

        def lookup(self, mpn):
            return EnrichmentResult()  # empty = a clean miss

    html = (FIX / "mouser_product.html").read_text(encoding="utf-8")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(html),
                              mouser=_MissMouser(), limiter=_NoWaitLimiter(),
                              http_fetcher=_StubHttpFetcher(mode="pdf"), jlcsearch=_NullJlc())
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V"
    )
    assert r.mpn.value == "ERJ-P03F1101V"  # the RENDER filled it after the API missed
