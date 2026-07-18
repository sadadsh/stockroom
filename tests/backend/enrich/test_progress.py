"""S6: honest per-stage progress. The pipeline emits the real
`fetching -> rendering -> extracting -> validating` sequence through a progress
callback, so a background job can stream the live stage to the UI (spec section 8).
Progress is never theatrical: a stage fires only when that work actually begins,
the render stage comes from the fetcher/engine (the one phase the pipeline cannot
observe from outside), and the reported pct never rewinds across a multi-source walk."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.pipeline import EnrichmentPipeline, ScrapeSource
from stockroom.enrich.progress import Stage, emit, monotonic, stage_callback

FIX = Path(__file__).parent / "fixtures"


class _NoWaitLimiter:
    def acquire(self):
        pass


class _NullJlc:
    def search(self, mpn):
        return None


class _RenderingFetcher:
    """A RenderedDomFetcher that, like the real Camoufox tier, signals the render
    phase through on_stage before returning the settled DOM."""

    def __init__(self, html):
        self._html = html
        self.on_stage_calls: list[str] = []

    def rendered_html(self, url, timeout=20.0, on_stage=None):
        from stockroom.enrich.fetch import FetchResult

        if on_stage is not None:
            on_stage(Stage.RENDERING)
            self.on_stage_calls.append(Stage.RENDERING)
        return FetchResult(url, 200, self._html, self._html.encode(), "text/html", url)


def _stages(events: list[dict]) -> list[str]:
    return [e["stage"] for e in events]


# --- the progress helpers -----------------------------------------------------


def test_emit_is_a_noop_without_a_sink():
    # No sink -> nothing raised, nothing emitted (the default sync path).
    emit(None, Stage.FETCHING)
    assert stage_callback(None) is None
    assert monotonic(None) is None


def test_emit_carries_stage_pct_and_message():
    seen: list[dict] = []
    emit(seen.append, Stage.RENDERING, "settling the page")
    assert seen == [{"stage": "rendering", "pct": 45, "message": "settling the page"}]


def test_monotonic_never_rewinds_the_bar():
    seen: list[dict] = []
    sink = monotonic(seen.append)
    sink({"stage": "extracting", "pct": 80})
    sink({"stage": "fetching", "pct": 15})  # a later source re-emitting a low local pct
    pcts = [e["pct"] for e in seen]
    assert pcts == [80, 80]  # the bar held; it did not go backward
    assert _stages(seen) == ["extracting", "fetching"]  # but the label still updated


# --- the URL path -------------------------------------------------------------


def test_extract_from_url_emits_the_full_stage_sequence(tmp_path):
    html = (FIX / "mouser_product.html").read_text(encoding="utf-8")
    fetcher = _RenderingFetcher(html)
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "c", fetcher=fetcher, limiter=_NoWaitLimiter(),
        jlcsearch=_NullJlc(),
    )
    events: list[dict] = []
    r = pipe.extract_from_url(
        "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V",
        progress=events.append,
    )
    # the render signal came from the fetcher, not invented by the pipeline
    assert fetcher.on_stage_calls == [Stage.RENDERING]
    assert _stages(events) == ["fetching", "rendering", "extracting", "validating"]
    assert [e["pct"] for e in events] == sorted(e["pct"] for e in events)  # monotonic
    assert r.mpn.value == "ERJ-P03F1101V"  # the real extraction still happened


def test_extract_from_url_without_progress_is_unchanged(tmp_path):
    # The default sync callers pass no sink; the old call shape (no on_stage kwarg) must
    # still work against a fetcher that never learned about progress.
    html = (FIX / "mouser_product.html").read_text(encoding="utf-8")

    class _OldFetcher:
        def rendered_html(self, url, timeout=20.0):
            from stockroom.enrich.fetch import FetchResult

            return FetchResult(url, 200, html, html.encode(), "text/html", url)

    pipe = EnrichmentPipeline(cache_dir=tmp_path / "c", fetcher=_OldFetcher(),
                              limiter=_NoWaitLimiter(), jlcsearch=_NullJlc())
    r = pipe.extract_from_url("https://www.mouser.com/x")
    assert r.mpn.value == "ERJ-P03F1101V"


# --- the MPN path (registry walk) ---------------------------------------------


def test_scrape_source_emits_stages_when_given_a_sink(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    fetcher = _RenderingFetcher(html)
    src = ScrapeSource(
        fetcher=fetcher, limiter=_NoWaitLimiter(),
        url_for=lambda mpn, cat: "https://www.lcsc.com/product-detail/C1.html",
    )
    events: list[dict] = []
    src.enrich("TPS62130RGTR", "ICs", remaining={"mpn"}, progress=events.append)
    assert _stages(events) == ["fetching", "rendering", "extracting", "validating"]


def test_enrich_mpn_streams_stages_through_the_walk(tmp_path):
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    fetcher = _RenderingFetcher(html)
    pipe = EnrichmentPipeline(
        cache_dir=tmp_path / "c", fetcher=fetcher, limiter=_NoWaitLimiter(),
        jlcsearch=_NullJlc(),  # LCSC misses, so the scrape tier does the visible work
    )
    events: list[dict] = []
    pipe.enrich("TPS62130RGTR", "ICs", progress=events.append)
    stages = _stages(events)
    assert "rendering" in stages and "validating" in stages
    assert [e["pct"] for e in events] == sorted(e["pct"] for e in events)  # monotonic


# --- review fixes: honest stage labels for the LCSC + Mouser legs -------------


class _HitJlc:
    """A jlcsearch client that returns a real catalogue hit, so LcscSource walks its
    product-page leg (where the fetch/extract labelling matters)."""

    def __init__(self, product_http):
        from stockroom.enrich.jlcsearch import JlcHit

        self._hit = JlcHit(mpn="TPS62130RGTR", lcsc="C1234", package="QFN", stock=10)
        self._product_http = product_http

    def search(self, mpn):
        return self._hit


class _ProductHttp:
    def __init__(self, html=None, boom=False):
        self._html = html
        self._boom = boom

    def get(self, url, referer="", timeout=15.0):
        from stockroom.enrich.errors import EnrichError
        from stockroom.enrich.fetch import FetchResult

        if self._boom:
            raise EnrichError("product page 403")
        return FetchResult(url, 200, self._html, self._html.encode(), "text/html", url)


def _lcsc_source(http):
    from stockroom.enrich.pipeline import LcscSource

    return LcscSource(http, jlcsearch=_HitJlc(http), limiter=_NoWaitLimiter())


def test_lcsc_product_leg_labels_the_fetch_before_the_extract():
    # The confirmed review bug: the product-page GET was labelled EXTRACTING (pct 80) BEFORE the
    # network fetch, mislabeling a fetch and pinning the bar high. FETCHING must precede EXTRACTING.
    html = (FIX / "lcsc_product.html").read_text(encoding="utf-8")
    events: list[dict] = []
    _lcsc_source(_ProductHttp(html=html)).enrich("TPS62130RGTR", "ICs", remaining={"mpn"},
                                                 progress=events.append)
    stages = _stages(events)
    assert "extracting" in stages
    assert stages.index("fetching") < stages.index("extracting")  # fetch labelled before extract
    # no extracting is emitted before its fetch has been labelled
    for i, s in enumerate(stages):
        if s == "extracting":
            assert "fetching" in stages[:i]


def test_lcsc_failed_product_page_never_emits_extracting():
    # A product page that 403s/times out extracted nothing, so EXTRACTING must NOT fire (it did,
    # premature at pct 80, before the fix).
    events: list[dict] = []
    _lcsc_source(_ProductHttp(boom=True)).enrich("TPS62130RGTR", "ICs", remaining={"mpn"},
                                                 progress=events.append)
    assert "extracting" not in _stages(events)  # nothing was extracted, so no such stage
    assert "fetching" in _stages(events)  # but the fetch attempt was honestly shown


def test_mouser_source_emits_fetching_for_its_api_lookup():
    from stockroom.enrich.pipeline import _MouserSource

    class _Adapter:
        def lookup(self, mpn):
            from stockroom.enrich.schema import EnrichmentResult

            return EnrichmentResult(category="ICs")

    events: list[dict] = []
    _MouserSource(_Adapter()).enrich("STM32F030", "ICs", set(), progress=events.append)
    assert _stages(events) == ["fetching"]  # the real API round-trip is shown, not silent
