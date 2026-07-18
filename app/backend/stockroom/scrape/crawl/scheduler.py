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
        """Take a global slot, then wait until this host's governor allows a request and
        consume its token. Waiting is done via the injected sleep, so a cooling-down host
        (tripped breaker) blocks here rather than hammering the WAF."""
        await self._sem.acquire()
        gov = self._governor(host)
        # Loop: the rate/cooldown can move while we wait, so re-check after each sleep.
        while True:
            now = self._clock()
            when = gov.next_available()
            if when <= now:
                gov.consume()
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
