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


def test_pipeline_follows_scraped_datasheet_url_and_extracts_specs(tmp_path):
    http = _StubHttpFetcher(mode="pdf")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http)
    r = pipe.enrich("TPS62130RGTR", "ICs")
    assert r.datasheet_url.value == "https://ti.com/lit/ds/tps62130.pdf"
    # the DatasheetSource followed the URL, fetched the real PDF, extracted the package
    assert r.package.value == "VQFN-16"
    assert r.package.source == "datasheet"
    assert http.gets == ["https://ti.com/lit/ds/tps62130.pdf"]  # the PDF was fetched


def test_enrich_candidate_fetches_and_stores_the_datasheet_pdf(tmp_path):
    http = _StubHttpFetcher(mode="pdf")
    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_StubFetcher(_LD_WITH_DATASHEET),
                              limiter=_NoWaitLimiter(), http_fetcher=http)
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
