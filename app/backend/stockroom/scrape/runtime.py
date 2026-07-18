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
import warnings
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
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
            self._loop.close()   # close the loop on the failure path so its fds do not leak
            return
        # Signal readiness from INSIDE the loop, just before run_forever, so start() only
        # returns once the loop is actually running (no window where stop() lands early).
        self._loop.call_soon(self._ready.set)
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
        # call_soon_threadsafe queues the stop even if run_forever has not started yet and
        # fires as soon as it does, so a stop() that races startup still stops the loop.
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass  # loop already closed between the guard and here
        self._join()

    def _join(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._start_timeout)
            if thread.is_alive():
                # Do NOT silently discard a still-running thread: keep the handles so a later
                # start() sees _thread is set and refuses to spawn a second parallel loop.
                warnings.warn(
                    "scrape runtime thread did not exit within the timeout; leaving it "
                    "observable rather than orphaning a second loop", RuntimeWarning,
                    stacklevel=2,
                )
                return
        self._thread = None
        self._loop = None
        self._engine = None

    # -- submission ----------------------------------------------------------------

    @property
    def engine(self) -> Any:
        return self._engine

    def submit(self, coro_fn: Callable[[Any], Any]) -> "Future":
        """Schedule coro_fn(engine) on the runtime loop, returning a concurrent Future. Waits
        for the engine to be fully built first, so a caller racing start() can never receive
        coro_fn(None) or hit a not-yet-running loop."""
        if self._loop is None:
            raise RuntimeError("scrape runtime is not started")
        if not self._ready.is_set() and not self._ready.wait(timeout=self._start_timeout):
            raise RuntimeError("scrape runtime did not become ready")
        if self._start_error is not None:
            raise self._start_error
        return asyncio.run_coroutine_threadsafe(coro_fn(self._engine), self._loop)

    def run(self, coro_fn: Callable[[Any], Any], timeout: float | None = None) -> Any:
        """Run coro_fn(engine) on the runtime loop and block for its result, re-raising any
        exception in the calling thread. On a timeout the underlying coroutine is cancelled
        so a timed-out scrape does not keep running on the loop. This is the sync entry point
        S5 uses."""
        fut = self.submit(coro_fn)
        try:
            return fut.result(timeout)
        except FutureTimeoutError:
            fut.cancel()   # request cancellation of the coroutine on the loop
            raise
