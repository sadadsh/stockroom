"""HostGovernor: the pure, deterministic anti-ban policy for one host (spec sections 5,
6; owner: "we never get blocked too"). A token bucket paces requests; the rate starts at
FULL speed (no ramp, owner directive), TIGHTENS multiplicatively on a block (429 /
challenge / 403) and LOOSENS additively on sustained success. After a run of consecutive
blocks a circuit breaker cools the host down BEFORE the WAF escalates, honoring a server
Retry-After when it is longer. All state is computed against an injected clock with no
sleeping, so the policy is unit-tested deterministically; the async Scheduler wraps it."""

from __future__ import annotations

import time
from typing import Callable

# Full speed by default (no slow start). Requests/second.
MAX_RATE = 8.0
# The self-preserving floor a heavily-pushed-back host is throttled to (never 0: a
# cooled-down host is paused by the breaker, not starved to a dead rate).
MIN_RATE = 0.5
# Burst capacity of the token bucket.
BUCKET = 8.0
# On a block: rate *= TIGHTEN. On a success: rate += LOOSEN (capped at MAX_RATE).
TIGHTEN = 0.5
LOOSEN = 1.0
# Consecutive blocks that trip the circuit breaker, and its exponential backoff bounds.
BREAKER_THRESHOLD = 3
BREAKER_BASE = 30.0
BREAKER_CAP = 600.0


class HostGovernor:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.rate = MAX_RATE
        self.tokens = BUCKET
        self._last_refill = clock()
        self.consec_blocks = 0
        self.cooldown_until = 0.0

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        self.tokens = min(BUCKET, self.tokens + elapsed * self.rate)
        self._last_refill = now

    def next_available(self) -> float:
        """The earliest clock time a request to this host is allowed: the cooldown while
        the breaker is tripped, else now if a token is ready, else when the next token
        refills. Pure (does not consume)."""
        now = self._clock()
        if now < self.cooldown_until:
            return self.cooldown_until
        self._refill(now)
        if self.tokens >= 1.0:
            return now
        needed = 1.0 - self.tokens
        return now + (needed / self.rate if self.rate > 0 else BREAKER_CAP)

    def consume(self) -> None:
        now = self._clock()
        self._refill(now)
        self.tokens = max(0.0, self.tokens - 1.0)

    def on_success(self) -> None:
        self.rate = min(MAX_RATE, self.rate + LOOSEN)
        self.consec_blocks = 0
        self.cooldown_until = 0.0

    def on_block(self, retry_after: float | None = None) -> None:
        now = self._clock()
        self.rate = max(MIN_RATE, self.rate * TIGHTEN)
        self.consec_blocks += 1
        cooldown = 0.0
        if self.consec_blocks >= BREAKER_THRESHOLD:
            over = self.consec_blocks - BREAKER_THRESHOLD
            cooldown = min(BREAKER_CAP, BREAKER_BASE * (2.0 ** over))
        if retry_after is not None and retry_after > 0:
            cooldown = max(cooldown, retry_after)
        if cooldown > 0:
            self.cooldown_until = now + cooldown
