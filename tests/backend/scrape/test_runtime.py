import threading

import pytest

from stockroom.scrape.runtime import ScrapeRuntime


class _StubEngine:
    def __init__(self):
        self.closed = False

    async def ping(self):
        return 42

    async def thread_id(self):
        return threading.get_ident()

    async def boom(self):
        raise ValueError("nope")

    async def aclose(self):
        self.closed = True


def test_run_executes_on_worker_loop_and_returns_value():
    rt = ScrapeRuntime(engine_factory=lambda: _StubEngine())
    rt.start()
    try:
        assert rt.run(lambda e: e.ping()) == 42
        worker_tid = rt.run(lambda e: e.thread_id())
        assert worker_tid != threading.get_ident()   # ran on the background loop thread
    finally:
        rt.stop()


def test_run_reraises_coroutine_exception():
    rt = ScrapeRuntime(engine_factory=lambda: _StubEngine())
    rt.start()
    try:
        with pytest.raises(ValueError):
            rt.run(lambda e: e.boom())
    finally:
        rt.stop()


def test_stop_is_idempotent_and_closes_the_engine():
    stub = _StubEngine()
    rt = ScrapeRuntime(engine_factory=lambda: stub)
    rt.start()
    rt.stop()
    assert stub.closed is True
    rt.stop()  # second stop is a no-op, never raises


def test_async_engine_factory_is_supported():
    async def factory():
        return _StubEngine()

    rt = ScrapeRuntime(engine_factory=factory)
    rt.start()
    try:
        assert rt.run(lambda e: e.ping()) == 42
    finally:
        rt.stop()
