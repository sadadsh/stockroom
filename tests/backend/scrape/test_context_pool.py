import asyncio

from stockroom.scrape.fetch.browser import ContextPool


class _FakeCtx:
    def __init__(self, n):
        self.n = n
        self.closed = False


def test_reuses_an_idle_context():
    async def run():
        created = []

        async def create():
            c = _FakeCtx(len(created))
            created.append(c)
            return c

        async def close(c):
            c.closed = True

        pool = ContextPool(size=2, max_uses=10)
        e1 = await pool.acquire(create)
        c1 = e1[0]
        await pool.release(e1, close)
        e2 = await pool.acquire(create)
        assert e2[0] is c1              # warm reuse, not a fresh context
        assert len(created) == 1
        await pool.release(e2, close)

    asyncio.run(run())


def test_recycles_after_max_uses():
    async def run():
        async def create():
            return _FakeCtx(0)

        closed = []

        async def close(c):
            closed.append(c)

        pool = ContextPool(size=1, max_uses=2)
        e = await pool.acquire(create)
        await pool.release(e, close)   # uses -> 1, kept
        e = await pool.acquire(create)  # same context
        await pool.release(e, close)   # uses -> 2 >= max, recycled (closed)
        assert len(closed) == 1

    asyncio.run(run())


def test_recycle_flag_closes_immediately():
    async def run():
        async def create():
            return _FakeCtx(0)

        closed = []

        async def close(c):
            closed.append(c)

        pool = ContextPool(size=1)
        e = await pool.acquire(create)
        await pool.release(e, close, recycle=True)   # e.g. a challenge burned the context
        assert len(closed) == 1

    asyncio.run(run())


def test_size_bounds_concurrent_contexts():
    async def run():
        created = []

        async def create():
            c = _FakeCtx(len(created))
            created.append(c)
            return c

        async def close(c):
            pass

        pool = ContextPool(size=1)
        e1 = await pool.acquire(create)
        acq2 = asyncio.create_task(pool.acquire(create))
        await asyncio.sleep(0)
        assert not acq2.done()          # only one slot; the 2nd waits
        await pool.release(e1, close)
        e2 = await asyncio.wait_for(acq2, timeout=1)
        assert e2[0] is e1[0]           # reused the released context
        await pool.release(e2, close)

    asyncio.run(run())
