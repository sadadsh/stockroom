"""Regression locks for the 17 confirmed findings of the S4 adversarial review
(anti-ban scheduler, crawler, frontier, runtime bridge, HTTP Retry-After)."""

import asyncio

import pytest

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.crawl.frontier import Frontier, Scope, canonical_url
from stockroom.scrape.crawl.governor import BREAKER_CAP, BREAKER_THRESHOLD, HostGovernor
from stockroom.scrape.crawl.scheduler import Scheduler
from stockroom.scrape.engine import ScrapeEngine
from stockroom.scrape.model import Page
from stockroom.scrape.runtime import ScrapeRuntime


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --- governor -----------------------------------------------------------------

def test_no_full_token_burst_after_a_cooldown():  # [4]
    g = HostGovernor(clock=_Clock())
    for _ in range(BREAKER_THRESHOLD):
        g.on_block()
    assert g.tokens <= 1.0                       # resume at a trickle, not a full bucket


def test_success_does_not_cancel_an_active_cooldown():  # [5]
    clk = _Clock()
    g = HostGovernor(clock=clk)
    for _ in range(BREAKER_THRESHOLD):
        g.on_block()
    cd = g.cooldown_until
    assert cd > clk.t
    g.on_success()
    assert g.cooldown_until == cd                # a stale success can't clear a live breaker
    assert g.next_available() > clk.t


def test_breaker_backoff_never_overflows():  # [11]
    clk = _Clock()
    g = HostGovernor(clock=clk)
    for _ in range(1100):                         # 2.0**1024 raises OverflowError without a clamp
        g.on_block()
    assert g.cooldown_until <= clk.t + BREAKER_CAP + 1.0


# --- scheduler ----------------------------------------------------------------

def test_acquire_does_not_leak_a_slot_on_cancellation():  # [1] + [6]
    async def run():
        async def _park(_delay):
            await asyncio.Event().wait()          # never returns; the task parks here

        s = Scheduler(max_concurrency=1, clock=_Clock(), sleep=_park)
        for _ in range(BREAKER_THRESHOLD):
            s.record_block("ex.com")              # trip a cooldown (fixed clock -> in future)
        t = asyncio.create_task(s.acquire("ex.com"))
        await asyncio.sleep(0.02)                 # let it reach the cooldown wait
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        # the single global slot must NOT be leaked: a healthy host acquires immediately
        await asyncio.wait_for(s.acquire("healthy.com"), timeout=1)
        s.release("healthy.com")

    asyncio.run(run())


# --- frontier -----------------------------------------------------------------

def test_canonical_url_survives_a_malformed_port():  # [2]
    assert isinstance(canonical_url("http://example.com:99999/path"), str)
    assert isinstance(canonical_url("http://example.com:abc/path"), str)


def test_scope_path_prefix_requires_a_boundary():  # [12]
    sc = Scope(host="ex.com", path_prefix="/docs")
    assert sc.allows("https://ex.com/docs/intro", 0) is True
    assert sc.allows("https://ex.com/docs", 0) is True
    assert sc.allows("https://ex.com/docs-evil/x", 0) is False   # sibling, not in subtree


def test_content_dedup_frees_a_page_budget_slot():  # [13]
    f = Frontier(Scope(host="ex.com", max_pages=2))
    assert f.add("https://ex.com/1", 0) is True
    assert f.add("https://ex.com/2", 0) is True
    assert f.add("https://ex.com/3", 0) is False    # budget spent
    f.release_slot()                                # a duplicate-content page freed its slot
    assert f.add("https://ex.com/3", 0) is True


def test_canonical_url_normalizes_path_dots_and_slashes():  # [14]
    assert canonical_url("https://ex.com/a/../b//c") == "https://ex.com/b/c"


def test_canonical_url_unifies_idn_host_to_punycode():  # [15]
    c = canonical_url("https://exämple.com/p")
    assert "xn--" in c


# --- http Retry-After ---------------------------------------------------------

def test_http_parses_retry_after_on_a_block():  # [10]
    from stockroom.scrape.fetch.http import HttpClient

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "45"}
        text = ""
        content = b""
        url = "https://ex.com/x"

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    client = HttpClient(session_factory=_Session, retries=0)
    out = asyncio.run(client.get("https://ex.com/x"))
    assert out.kind == "blocked" and out.retry_after == 45.0


# --- runtime ------------------------------------------------------------------

def test_run_timeout_cancels_the_underlying_coroutine():  # [9]
    import threading
    import time

    class _Slow:
        def __init__(self):
            self.cancelled = threading.Event()

        async def slow(self):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    eng = _Slow()
    rt = ScrapeRuntime(engine_factory=lambda: eng)
    rt.start()
    try:
        import concurrent.futures
        with pytest.raises(concurrent.futures.TimeoutError):
            rt.run(lambda e: e.slow(), timeout=0.2)
        assert eng.cancelled.wait(timeout=2) is True    # the coroutine was actually cancelled
    finally:
        rt.stop()


def test_start_then_run_is_safe_with_a_slow_factory():  # [17]
    async def slow_factory():
        await asyncio.sleep(0.2)
        from tests.backend.scrape.test_runtime import _StubEngine
        return _StubEngine()

    rt = ScrapeRuntime(engine_factory=slow_factory)
    rt.start()
    try:
        assert rt.run(lambda e: e.ping()) == 42          # engine fully built, never None
    finally:
        rt.stop()


# --- engine crawl robustness --------------------------------------------------

class _GraphBrowser:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    async def fetch(self, url, timeout=20.0):
        self.calls.append(url)
        html = self._pages.get(url, "<html><body>none</body></html>")
        return Page(url=url, final_url=url, status=200, content=html.encode(),
                    text=html, content_type="text/html", render_tier="browser")


def test_crawl_survives_a_bad_port_link_without_hanging(tmp_path):  # [3] + [2]
    pages = {
        "https://ex.com/": ('<html><body><h1>Home</h1>'
                            '<a href="http://ex.com:abc/x">bad</a>'
                            '<a href="/good">good</a></body></html>'),
        "https://ex.com/good": '<html><body><h1>Good</h1>' + ("word " * 50) + '</body></html>',
    }
    br = _GraphBrowser(pages)
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=br)

    async def run():
        return await asyncio.wait_for(
            engine.crawl("https://ex.com/", Scope(max_pages=5, max_depth=3)), timeout=8)

    results = asyncio.run(run())
    urls = {r.page.url for r in results}
    assert "https://ex.com/" in urls and "https://ex.com/good" in urls


def test_crawl_survives_a_scrape_that_raises(tmp_path):  # [3]
    class _Boom:
        async def fetch(self, url, timeout=20.0):
            if url.endswith("/boom"):
                raise RuntimeError("kaboom")
            html = ('<html><body><a href="/boom">b</a><a href="/ok">o</a>'
                    + ("word " * 50) + '</body></html>') if url.endswith("/") \
                else '<html><body>' + ("w " * 50) + '</body></html>'
            return Page(url=url, final_url=url, status=200, content=html.encode(),
                        text=html, content_type="text/html", render_tier="browser")

    engine = ScrapeEngine(cache=ResponseCache(tmp_path), browser=_Boom())

    async def run():
        # workers=1: the single worker MUST survive the raising fetch, or the crawl hangs.
        return await asyncio.wait_for(
            engine.crawl("https://ex.com/", Scope(max_pages=5, max_depth=3), workers=1), timeout=8)

    results = asyncio.run(run())                        # must not hang despite the raising fetch
    urls = {r.page.url for r in results}
    assert "https://ex.com/ok" in urls
