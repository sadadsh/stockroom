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
