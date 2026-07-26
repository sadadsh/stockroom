"""Scheduler: the async front end of the anti-ban subsystem (spec sections 5, 6). A global
semaphore caps total in-flight work; a per-host HostGovernor paces each domain (full speed
by default, self-tightening on push-back, circuit-broken before a WAF escalates). A caller
acquires a slot per host, fetches, then records success or block from the outcome. The
clock and sleep are injected so the pacing is unit-tested deterministically; nothing here
ever raises to a caller."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from stockroom.scrape.crawl.governor import HostGovernor


class Scheduler:
    def __init__(
        self,
        max_concurrency: int = 8,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._clock = clock
        self._sleep = sleep
        self._governors: dict[str, HostGovernor] = {}

    @staticmethod
    def host_of(url: str) -> str:
        return (urlsplit(url).netloc or "").lower()

    def _governor(self, host: str) -> HostGovernor:
        gov = self._governors.get(host)
        if gov is None:
            gov = HostGovernor(clock=self._clock)
            self._governors[host] = gov
        return gov

    async def acquire(self, host: str) -> None:
        """Wait until this host's governor allows a request, then take a global slot and
        consume a token. The per-host wait (incl. a tripped-breaker cooldown of up to
        BREAKER_CAP) happens WITHOUT holding a global slot, so a single cooling-down host
        cannot tie up all slots and starve healthy hosts (no head-of-line blocking). The
        slot, once taken, is released here on any exception/cancellation so it is never
        leaked; the caller releases it after the fetch on the success path."""
        gov = self._governor(host)
        while True:
            # 1. Wait for host readiness with NO global slot held.
            await self._wait_ready(gov)
            # 2. Take a global slot.
            await self._sem.acquire()
            # 3. Still ready? consume + return (caller releases). Else drop the slot and
            #    re-wait, so the slot is never held across a cooldown. Leak-proof on abort.
            try:
                when = gov.next_available()
                now = self._clock()
                if when <= now:
                    gov.consume()
                    return
            except BaseException:
                self._sem.release()
                raise
            self._sem.release()

    async def _wait_ready(self, gov: HostGovernor) -> None:
        # Read `when` first, then a FRESH `now`: next_available() reads the clock itself, so
        # `now` must be sampled AFTER it or a ready token (when == its own now) would always
        # look "in the future" and spin.
        while True:
            when = gov.next_available()
            now = self._clock()
            if when <= now:
                return
            await self._sleep(when - now)

    def release(self, host: str) -> None:
        self._sem.release()

    def record_success(self, host: str) -> None:
        self._governor(host).on_success()

    def record_block(self, host: str, retry_after: float | None = None) -> None:
        self._governor(host).on_block(retry_after=retry_after)

    def slot(self, host: str) -> "_Slot":
        return _Slot(self, host)


class _Slot:
    """`async with scheduler.slot(host):` — acquire on enter, release on exit."""

    def __init__(self, scheduler: Scheduler, host: str):
        self._scheduler = scheduler
        self._host = host

    async def __aenter__(self) -> "_Slot":
        await self._scheduler.acquire(self._host)
        return self

    async def __aexit__(self, *exc) -> None:
        self._scheduler.release(self._host)
