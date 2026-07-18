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


def test_default_factory_builds_an_engine_fetcher(tmp_path):
    f = default_rendered_dom_fetcher(tmp_path)
    assert isinstance(f, EngineRenderedDomFetcher)


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
