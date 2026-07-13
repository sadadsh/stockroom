"""A polite sliding-window rate limiter so Stockroom never hammers a site into
banning it (spec section 6.1). Lifted from hildogjr/KiCost api_mouser.py (MIT):
keep the timestamps of recent calls, burst up to `limit` inside `window`, then
sleep until the oldest falls out of the window, and pop it. Strictly better than
a blunt sleep-a-full-window counter (research opportunity 4)."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

# The 0.1s nudge past the boundary is KiCost's, so the oldest is definitively out
# of the window after the sleep and we never busy-loop on the boundary.
_NUDGE = 0.1


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self.window = window
        self._clock = clock
        self._sleep = sleeper
        self._stamps: deque[float] = deque()

    def _evict(self, now: float) -> None:
        while self._stamps and (now - self._stamps[0]) >= self.window:
            self._stamps.popleft()

    def acquire(self) -> None:
        now = self._clock()
        self._evict(now)
        if len(self._stamps) >= self.limit:
            oldest = self._stamps[0]
            wait = self.window - (now - oldest) + _NUDGE
            if wait > 0:
                self._sleep(wait)
            now = self._clock()
            self._evict(now)
        self._stamps.append(now)
