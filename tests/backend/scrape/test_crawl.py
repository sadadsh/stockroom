import asyncio

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.crawl.frontier import Scope
from stockroom.scrape.engine import ScrapeEngine
from stockroom.scrape.model import Page


class _GraphBrowser:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    async def fetch(self, url, timeout=20.0):
        self.calls.append(url)
        html = self._pages.get(url, "<html><body>none</body></html>")
        return Page(url=url, final_url=url, status=200, content=html.encode(),
                    text=html, content_type="text/html", render_tier="browser")


def _pages():
    return {
        "https://ex.com/": ('<html><body><h1>Home</h1><a href="/a">a</a>'
                            '<a href="/b">b</a><a href="/a">dup</a>'
                            '<a href="https://other.com/x">off</a></body></html>'),
        "https://ex.com/a": ('<html><body><h1>A page</h1>' + ("word " * 50)
                             + '<a href="/b">b</a><a href="/">home</a></body></html>'),
        "https://ex.com/b": '<html><body><h1>B page</h1>' + ("text " * 50) + '</body></html>',
    }


def test_crawl_returns_scoped_deduped_results(tmp_path):
    br = _GraphBrowser(_pages())
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=br)
    results = asyncio.run(engine.crawl("https://ex.com/", Scope(max_pages=5, max_depth=3)))
    urls = sorted(r.page.url for r in results)
    assert urls == ["https://ex.com/", "https://ex.com/a", "https://ex.com/b"]
    assert "https://other.com/x" not in br.calls        # off-host not followed


def test_crawl_respects_max_pages(tmp_path):
    br = _GraphBrowser(_pages())
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=br)
    results = asyncio.run(engine.crawl("https://ex.com/", Scope(max_pages=2, max_depth=3)))
    assert len(results) <= 2


def test_crawl_follows_same_host_links_when_seed_has_a_port(tmp_path):
    # Regression: the scope host was bound from the seed's netloc (WITH port) but
    # Scope.allows compares the bare hostname (NO port), so a ported seed matched
    # nothing - the seed itself was rejected out-of-scope and the crawl returned [].
    pages = {
        "https://ex.com:8443/": ('<html><body><h1>Home</h1>'
                                 '<a href="https://ex.com:8443/a">a</a></body></html>'),
        "https://ex.com:8443/a": ('<html><body><h1>A page</h1>' + ("word " * 50)
                                  + '</body></html>'),
    }
    br = _GraphBrowser(pages)
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=br)
    results = asyncio.run(engine.crawl("https://ex.com:8443/", Scope(max_pages=5, max_depth=3)))
    urls = sorted(r.page.url for r in results)
    assert urls == ["https://ex.com:8443/", "https://ex.com:8443/a"]


def test_crawl_does_not_mutate_the_caller_scope(tmp_path):
    # Binding the seed host must not scribble on the caller's Scope: a Scope reused
    # across crawls of different hosts would otherwise stay pinned to the first host.
    br = _GraphBrowser(_pages())
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=br)
    scope = Scope(max_pages=5, max_depth=3)
    asyncio.run(engine.crawl("https://ex.com/", scope))
    assert scope.host is None


def test_crawl_of_a_dead_seed_returns_empty(tmp_path):
    # a seed that fails to fetch must not hang or raise; the crawl just yields nothing.
    class _Dead:
        async def fetch(self, url, timeout=20.0):
            from stockroom.scrape.model import FetchError
            return FetchError(url=url, reason="blocked", kind="blocked", status=403)

    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=_Dead())
    results = asyncio.run(engine.crawl("https://ex.com/", Scope(max_pages=5)))
    assert results == []
