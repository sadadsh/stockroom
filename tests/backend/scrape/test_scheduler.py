import asyncio

from stockroom.scrape.crawl.governor import BREAKER_BASE, BREAKER_THRESHOLD
from stockroom.scrape.crawl.scheduler import Scheduler


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Sleep:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    async def __call__(self, delay):
        self.calls.append(delay)
        self.clock.t += max(0.0, delay)  # a fake sleep that advances fake time


def test_host_of_extracts_netloc():
    assert Scheduler.host_of("https://www.mouser.com/ProductDetail/x") == "www.mouser.com"
    assert Scheduler.host_of("http://lcsc.com/p") == "lcsc.com"


def test_two_hosts_acquire_independently():
    clk = _Clock()
    s = Scheduler(max_concurrency=4, clock=clk, sleep=_Sleep(clk))

    async def run():
        await s.acquire("a.com")
        await s.acquire("b.com")  # different host, not blocked by a.com
        s.release("a.com")
        s.release("b.com")

    asyncio.run(run())


def test_blocked_host_waits_through_the_cooldown():
    clk = _Clock()
    slp = _Sleep(clk)
    s = Scheduler(max_concurrency=4, clock=clk, sleep=slp)

    async def run():
        host = "ex.com"
        for _ in range(BREAKER_THRESHOLD):
            s.record_block(host)
        t0 = clk.t
        await s.acquire(host)   # must sleep through the tripped breaker cooldown
        assert slp.calls, "expected the scheduler to sleep for the cooldown"
        assert clk.t >= t0 + BREAKER_BASE
        s.release(host)

    asyncio.run(run())


def test_global_concurrency_cap_blocks_the_third():
    clk = _Clock()
    s = Scheduler(max_concurrency=2, clock=clk, sleep=_Sleep(clk))

    async def run():
        await s.acquire("a.com")
        await s.acquire("b.com")               # both global slots taken
        c = asyncio.create_task(s.acquire("c.com"))
        await asyncio.sleep(0)
        assert not c.done()                    # blocked on the global cap
        s.release("a.com")
        await asyncio.wait_for(c, timeout=1)
        assert c.done()
        s.release("b.com")
        s.release("c.com")

    asyncio.run(run())


def test_record_success_clears_an_expired_breaker():
    clk = _Clock()
    slp = _Sleep(clk)
    s = Scheduler(max_concurrency=4, clock=clk, sleep=slp)

    async def run():
        host = "ex.com"
        for _ in range(BREAKER_THRESHOLD):
            s.record_block(host)
        gov = s._governor(host)
        clk.t = gov.cooldown_until + 1.0       # the cooldown has elapsed
        s.record_success(host)
        await s.acquire(host)                  # expired breaker cleared -> no cooldown sleep
        assert slp.calls == [] or all(d == 0 for d in slp.calls)
        s.release(host)

    asyncio.run(run())
