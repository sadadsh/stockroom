import asyncio

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.engine import ScrapeEngine
from stockroom.scrape.model import FetchError, Page


class _StubHttp:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = 0

    async def get(self, url, referer="", timeout=15.0):
        self.calls += 1
        return self._outcome


class _StubBrowser:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = 0

    async def fetch(self, url, timeout=20.0):
        self.calls += 1
        return self._outcome


def _http_page(url="https://x/p"):
    return Page(url=url, final_url=url, status=200, content=b"H", text="H",
                content_type="text/html", render_tier="http")


def _browser_page(url="https://x/p"):
    return Page(url=url, final_url=url, status=200, content=b"B", text="B",
                content_type="text/html", render_tier="browser")


# --- S1 behavior (no browser configured): fetch is HTTP-only, cache-first ---

def test_cache_hit_skips_http(tmp_path):
    cache = ResponseCache(tmp_path)
    cache.put(_http_page())
    http = _StubHttp(_http_page())
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert out.from_cache is True
    assert http.calls == 0


def test_miss_fetches_and_caches(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(_http_page())
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert isinstance(out, Page)
    assert http.calls == 1
    out2 = asyncio.run(engine.fetch("https://x/p"))
    assert out2.from_cache is True
    assert http.calls == 1


def test_error_is_returned_and_not_cached(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(FetchError(url="https://x/p", reason="blocked", kind="blocked", status=403))
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert isinstance(out, FetchError)
    assert cache.get("https://x/p") is None


# --- S2 routing: pages render, binaries/APIs download ---

def test_page_routes_to_browser(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(_http_page())
    browser = _StubBrowser(_browser_page("https://x/page"))
    engine = ScrapeEngine(cache=cache, http=http, browser=browser)
    out = asyncio.run(engine.fetch("https://x/page"))
    assert isinstance(out, Page)
    assert out.render_tier == "browser"
    assert browser.calls == 1
    assert http.calls == 0


def test_pdf_routes_to_download(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(_http_page("https://x/ds.pdf"))
    browser = _StubBrowser(_browser_page())
    engine = ScrapeEngine(cache=cache, http=http, browser=browser)
    out = asyncio.run(engine.fetch("https://x/ds.pdf"))
    assert isinstance(out, Page)
    assert out.render_tier == "http"
    assert http.calls == 1
    assert browser.calls == 0


def test_render_caches_and_second_call_is_cache_hit(tmp_path):
    cache = ResponseCache(tmp_path)
    browser = _StubBrowser(_browser_page("https://x/page"))
    engine = ScrapeEngine(cache=cache, browser=browser)
    out = asyncio.run(engine.render("https://x/page"))
    assert out.render_tier == "browser"
    assert browser.calls == 1
    out2 = asyncio.run(engine.render("https://x/page"))
    assert out2.from_cache is True
    assert browser.calls == 1


def test_render_without_browser_is_a_typed_error(tmp_path):
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), http=_StubHttp(_http_page()))
    out = asyncio.run(engine.render("https://x/page"))
    assert isinstance(out, FetchError)
    assert out.kind == "transport"


# --- S3: scrape() = fetch then extract a validated ScrapeResult ---

def test_scrape_returns_scrape_result_on_page(tmp_path):
    from stockroom.scrape.model import ScrapeResult
    html = ('<html><body><article><h1>LM317</h1><p>' + ('w ' * 80) + '</p></article>'
            '<script type="application/ld+json">{"@type":"Product","mpn":"LM317"}</script>'
            '</body></html>')
    browser = _StubBrowser(Page(url="https://x/page", final_url="https://x/page",
                                status=200, content=html.encode(), text=html,
                                content_type="text/html", render_tier="browser"))
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=browser)
    out = asyncio.run(engine.scrape("https://x/page"))
    assert isinstance(out, ScrapeResult)
    assert out.product.mpn.value == "LM317"
    assert "# LM317" in out.markdown


def test_scrape_passes_through_fetch_error(tmp_path):
    engine = ScrapeEngine(cache=ResponseCache(tmp_path),
                          http=_StubHttp(FetchError(url="https://x/p", reason="blocked",
                                                    kind="blocked", status=403)))
    out = asyncio.run(engine.scrape("https://x/p.pdf"))
    assert isinstance(out, FetchError)
