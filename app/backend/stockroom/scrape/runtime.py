"""ScrapeRuntime: the persistent-event-loop bridge (spec section 3; S4 handoff). A single
asyncio loop runs on a daemon thread and OWNS the engine's long-lived resources — above all
the Playwright Chromium, which is bound to the loop that created it and cannot be started on
one loop and driven from another. Sync callers (the M6 enrichment pipeline in S5) submit
coroutines to that loop via run_coroutine_threadsafe and block for the result, so the whole
synchronous enrichment cascade can drive the async, stealthed, always-on browser. Nothing
here leaks the loop or the thread, and `run` re-raises the coroutine's exception to the
caller so failures are honest."""

from __future__ import annotations

import asyncio
import inspect
import threading
from concurrent.futures import Future
from typing import Any, Callable


class ScrapeRuntime:
    def __init__(self, engine_factory: Callable[[], Any] | None = None,
                 start_timeout: float = 30.0):
        self._engine_factory = engine_factory
        self._start_timeout = start_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._engine: Any = None
        self._ready = threading.Event()
        self._start_error: BaseException | None = None

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> "ScrapeRuntime":
        if self._thread is not None:
            return self
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._start_error = None
        self._thread = threading.Thread(target=self._run_loop, name="scrape-runtime",
                                        daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self._start_timeout):
            raise RuntimeError("scrape runtime failed to start within the timeout")
        if self._start_error is not None:
            err = self._start_error
            self._join()
            raise err
        return self

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._engine = self._loop.run_until_complete(self._build_engine())
        except BaseException as exc:  # noqa: BLE001 - surface a build failure to start()
            self._start_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._teardown())
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
            self._loop.close()

    async def _build_engine(self) -> Any:
        if self._engine_factory is None:
            return None
        result = self._engine_factory()
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _teardown(self) -> None:
        eng = self._engine
        aclose = getattr(eng, "aclose", None)
        if callable(aclose):
            res = aclose()
            if inspect.isawaitable(res):
                await res

    def stop(self) -> None:
        if self._thread is None:
            return
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        self._join()

    def _join(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._start_timeout)
        self._thread = None
        self._loop = None
        self._engine = None

    # -- submission ----------------------------------------------------------------

    @property
    def engine(self) -> Any:
        return self._engine

    def submit(self, coro_fn: Callable[[Any], Any]) -> "Future":
        """Schedule coro_fn(engine) on the runtime loop, returning a concurrent Future."""
        if self._loop is None:
            raise RuntimeError("scrape runtime is not started")
        return asyncio.run_coroutine_threadsafe(coro_fn(self._engine), self._loop)

    def run(self, coro_fn: Callable[[Any], Any], timeout: float | None = None) -> Any:
        """Run coro_fn(engine) on the runtime loop and block for its result, re-raising any
        exception in the calling thread. This is the sync entry point S5 uses."""
        return self.submit(coro_fn).result(timeout)
