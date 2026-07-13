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
