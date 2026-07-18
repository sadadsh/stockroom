"""S5: enrichment's rendered-DOM fetcher is now the portable stealthed engine
(ScrapeEngine.render over the ScrapeRuntime bridge), replacing the HTTP-only default so
JS-rendered distributor pages resolve on every OS. Tested with a stub engine (no browser)."""

from stockroom.enrich.fetch import FetchResult, RenderedDomFetcher
from stockroom.enrich.scrape_adapter import EngineRenderedDomFetcher, default_rendered_dom_fetcher
from stockroom.scrape.model import FetchError, Page
from stockroom.scrape.runtime import ScrapeRuntime


class _RenderEngine:
    def __init__(self, page_or_error):
        self._out = page_or_error
        self.rendered = []

    async def render(self, url, timeout=20.0):
        self.rendered.append(url)
        return self._out


def _page(url, html):
    return Page(url=url, final_url=url, status=200, content=html.encode(),
                text=html, content_type="text/html", render_tier="browser")


def test_engine_fetcher_returns_rendered_html_as_fetchresult():
    eng = _RenderEngine(_page("https://ex.com/p", "<html><body>hi</body></html>"))
    f = EngineRenderedDomFetcher(runtime=ScrapeRuntime(engine_factory=lambda: eng))
    try:
        res = f.rendered_html("https://ex.com/p")
        assert isinstance(res, FetchResult)
        assert res.text == "<html><body>hi</body></html>"
        assert res.status == 200 and res.final_url == "https://ex.com/p"
        assert eng.rendered == ["https://ex.com/p"]     # drove the browser render tier
    finally:
        f.close()


def test_engine_fetcher_returns_empty_on_a_block_never_raises():
    eng = _RenderEngine(FetchError(url="https://ex.com/p", reason="blocked", kind="blocked", status=403))
    f = EngineRenderedDomFetcher(runtime=ScrapeRuntime(engine_factory=lambda: eng))
    try:
        res = f.rendered_html("https://ex.com/p")
        assert res.text == "" and res.final_url == "https://ex.com/p"   # honest empty, no raise
    finally:
        f.close()


def test_engine_fetcher_satisfies_the_rendered_dom_protocol():
    assert isinstance(EngineRenderedDomFetcher(runtime=None), RenderedDomFetcher)


def test_rendered_html_is_bounded_and_returns_empty_on_a_slow_render():
    # [S5 review 1] a render that overruns (e.g. an anti-ban cooldown) must NOT pin the
    # calling thread indefinitely: run() gets a wall-clock ceiling, so rendered_html returns
    # an honest empty FetchResult instead of blocking forever.
    import asyncio

    class _HangEngine:
        async def render(self, url, timeout=20.0):
            await asyncio.sleep(30)

    f = EngineRenderedDomFetcher(runtime=ScrapeRuntime(engine_factory=lambda: _HangEngine()),
                                 run_timeout_buffer=0.1)
    try:
        res = f.rendered_html("https://ex.com/p", timeout=0.05)
        assert res.text == "" and res.final_url == "https://ex.com/p"   # bounded, no hang
    finally:
        f.close()


def test_stop_during_an_inflight_render_does_not_hang_the_caller():
    # [S5 review 2] stopping the runtime while a render is in flight must unblock the caller
    # (CancelledError), not orphan the task and hang fut.result() forever.
    import asyncio
    import threading
    import time

    class _HangEngine:
        async def render(self, url, timeout=20.0):
            await asyncio.sleep(30)

    rt = ScrapeRuntime(engine_factory=lambda: _HangEngine())
    rt.start()
    outcome = {}

    def _caller():
        try:
            rt.run(lambda e: e.render("https://ex.com/p"))
        except BaseException as exc:  # noqa: BLE001
            outcome["exc"] = type(exc).__name__

    t = threading.Thread(target=_caller)
    t.start()
    time.sleep(0.3)          # let the caller block inside the in-flight render
    rt.stop()
    t.join(timeout=5)
    assert not t.is_alive()  # the caller did NOT hang
    assert "exc" in outcome  # it got an exception instead of blocking forever


def test_default_factory_builds_an_engine_fetcher(tmp_path):
    f = default_rendered_dom_fetcher(tmp_path)
    assert isinstance(f, EngineRenderedDomFetcher)


class _StubFetcher:
    def __init__(self, html):
        self._html = html

    def rendered_html(self, url, timeout=20.0):
        return FetchResult(url=url, status=200, text=self._html, content=self._html.encode(),
                           content_type="text/html", final_url=url)


def test_enrich_render_path_drops_bad_data_via_the_validate_gate(tmp_path):
    # S5 no-bad-data: a rendered page carrying a malformed MPN and a negative stock must NOT
    # surface them; a valid field on the same page is kept.
    from stockroom.enrich.pipeline import EnrichmentPipeline

    html = ('<script type="application/ld+json">'
            '{"@type":"Product","mpn":"bad<>mpn","brand":{"name":"TI"},'
            '"offers":{"price":"0.50","inventoryLevel":-5}}</script>')
    p = EnrichmentPipeline(tmp_path, fetcher=_StubFetcher(html))
    r = p.extract_from_url("https://x/p")
    assert r.mpn is None                       # malformed MPN dropped
    assert r.stock is None                     # negative stock dropped
    assert r.manufacturer.value == "TI"        # valid field kept


def test_pipeline_extracts_from_a_rendered_product_page(tmp_path):
    # end-to-end through the pipeline: the engine renders a JS page, enrichment extracts it.
    from stockroom.enrich.pipeline import EnrichmentPipeline

    html = ('<html><body><script type="application/ld+json">'
            '{"@type":"Product","mpn":"LM317T","brand":{"name":"TI"}}</script>'
            '</body></html>')
    eng = _RenderEngine(_page("https://www.mouser.com/p", html))
    fetcher = EngineRenderedDomFetcher(runtime=ScrapeRuntime(engine_factory=lambda: eng))
    try:
        pipeline = EnrichmentPipeline(tmp_path, fetcher=fetcher)
        result = pipeline.extract_from_url("https://www.mouser.com/p")
        assert result.mpn.value == "LM317T"
        assert result.manufacturer.value == "TI"
    finally:
        fetcher.close()
