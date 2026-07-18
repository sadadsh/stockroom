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


def _page(url="https://x/p"):
    return Page(url=url, final_url=url, status=200, content=b"hi", text="hi",
                content_type="text/html")


def test_cache_hit_skips_http(tmp_path):
    cache = ResponseCache(tmp_path)
    cache.put(_page())
    http = _StubHttp(_page())
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert out.from_cache is True
    assert http.calls == 0


def test_miss_fetches_and_caches(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(_page())
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert isinstance(out, Page)
    assert http.calls == 1
    # now cached: a second fetch does not hit http again
    out2 = asyncio.run(engine.fetch("https://x/p"))
    assert out2.from_cache is True
    assert http.calls == 1


def test_error_is_returned_and_not_cached(tmp_path):
    cache = ResponseCache(tmp_path)
    http = _StubHttp(FetchError(url="https://x/p", reason="blocked", kind="blocked", status=403))
    engine = ScrapeEngine(cache=cache, http=http)
    out = asyncio.run(engine.fetch("https://x/p"))
    assert isinstance(out, FetchError)
    assert cache.get("https://x/p") is None  # errors never cached
