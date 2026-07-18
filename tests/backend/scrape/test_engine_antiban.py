import asyncio

from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.crawl.scheduler import Scheduler
from stockroom.scrape.engine import ScrapeEngine
from stockroom.scrape.model import FetchError, Page


class _StubHttp:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = 0

    async def get(self, url, referer="", timeout=15.0):
        self.calls += 1
        return self._outcome


def _page(url="https://ex.com/p.pdf"):
    return Page(url=url, final_url=url, status=200, content=b"%PDF-x", text="x",
                content_type="application/pdf", render_tier="http")


def test_blocked_download_records_block_and_negative_caches(tmp_path):
    cache = ResponseCache(tmp_path)
    sched = Scheduler(max_concurrency=4)
    http = _StubHttp(FetchError(url="https://ex.com/p.pdf", reason="blocked",
                                kind="blocked", status=403))
    engine = ScrapeEngine(cache=cache, http=http, scheduler=sched)

    out = asyncio.run(engine.download("https://ex.com/p.pdf"))
    assert isinstance(out, FetchError)
    assert sched.host_of("https://ex.com/p.pdf") == "ex.com"
    assert sched._governor("ex.com").consec_blocks >= 1        # block recorded
    assert cache.is_negative("https://ex.com/p.pdf") is True    # negative cached

    calls_after_first = http.calls
    out2 = asyncio.run(engine.download("https://ex.com/p.pdf"))
    assert isinstance(out2, FetchError)
    assert http.calls == calls_after_first                      # no second network hit


def test_successful_download_records_success_and_no_negative(tmp_path):
    cache = ResponseCache(tmp_path)
    sched = Scheduler(max_concurrency=4)
    engine = ScrapeEngine(cache=cache, http=_StubHttp(_page()), scheduler=sched)

    out = asyncio.run(engine.download("https://ex.com/p.pdf"))
    assert isinstance(out, Page)
    assert cache.is_negative("https://ex.com/p.pdf") is False


def test_scheduler_none_is_backward_compatible(tmp_path):
    # with no scheduler the engine behaves exactly as S1: a plain fetch, no governing.
    http = _StubHttp(_page())
    engine = ScrapeEngine(cache=ResponseCache(tmp_path), http=http)
    out = asyncio.run(engine.download("https://ex.com/p.pdf"))
    assert isinstance(out, Page) and http.calls == 1


def test_retry_after_is_honored_from_a_blocked_outcome(tmp_path):
    sched = Scheduler(max_concurrency=4)
    err = FetchError(url="https://ex.com/p.pdf", reason="429", kind="blocked",
                     status=429, retry_after=90.0)
    engine = ScrapeEngine(cache=ResponseCache(tmp_path),
                          http=_StubHttp(err), scheduler=sched)
    asyncio.run(engine.download("https://ex.com/p.pdf"))
    gov = sched._governor("ex.com")
    # cooldown is ~90s out from the block moment; allow a hair of elapsed real time.
    assert gov.cooldown_until - gov._clock() >= 89.0           # server Retry-After applied
