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
