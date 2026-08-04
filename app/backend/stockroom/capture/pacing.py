"""Pacing, backoff and a circuit breaker for library-wide completion runs.

MEASURED 2026-07-27 against the real catalogue, and this module exists because of the
measurement rather than the other way round: a 67-part run in 52 seconds (~1.3 req/s) was
CloudFront-blocked after roughly 11 successes, and 33 of the 67 parts came back
`HTTP 403 Forbidden` for reasons that had nothing to do with the part. The block cleared on
its own in about 60 seconds, so it is a COOLDOWN, not a ban -- which is what makes retrying
worth doing at all.

Scale it to 10,000 parts and an unpaced engine does not merely run slowly: it invents
thousands of failures, and the report -- the thing the owner reads to answer "is my library
complete" -- becomes fiction. So three things are enforced here.

**Pace.** Every catalogue call goes through the sliding-window limiter the repo already has
(`enrich/ratelimit.py`), rather than a second hand-rolled one. Provider PAGES need no limiter
at all now: a person opens them one at a time.

**Tell a BLOCK apart from a FAILURE.** They demand opposite responses. A blocked part was
never really attempted, so it must be retried later and reported `deferred`. A part genuinely
absent from the catalogue must NOT be retried, or a 10,000-part run pays a retry storm for
every one of them, and it must not be deferred either, or it returns every run forever and the
worklist never drains. `looks_rate_limited` is therefore written to be tight: it matches
throttle signals, not the word "error".

**Break the circuit.** Consecutive blocks mean the catalogue has stopped talking to us.
Continuing for another 9,900 parts produces nothing but noise, so the run stops and says why,
and -- because the worklist is derived from the library on every run -- resuming later is just
running it again.
"""

from __future__ import annotations

import re
import time

# Throttle signals, matched against a source's own error text. Deliberately NARROW: every
# pattern here names a rate/availability condition, never a generic failure. A loose pattern
# would defer parts that can never succeed, and a worklist that never drains is worse than a
# slow one. (`403` alone is not enough -- a 403 can be an auth failure -- so it is anchored to
# the shapes actually observed: an HTTP status, or CloudFront's own blocked-request page.)
_RATE_LIMITED = re.compile(
    r"(?:"
    r"http\s*error\s*(?:403|429|503|509)\b"
    r"|\b(?:429|503|509)\s+(?:too\s+many|service\s+unavailable|bandwidth)"
    r"|\brequest\s+blocked\b"
    r"|\brate[ _-]?limit(?:ed|ing)?\b"
    r"|\btoo\s+many\s+requests\b"
    r"|\bquota\s+exceeded\b"
    r"|\btemporarily\s+unavailable\b"
    r")",
    re.IGNORECASE,
)


def looks_rate_limited(text: str) -> bool:
    """True when this error text is the catalogue refusing to talk to us right now.

    The distinction this draws is load-bearing, so it is a function with its own tests rather
    than an inline `if "403" in err`.
    """
    return bool(text) and bool(_RATE_LIMITED.search(text))


class CircuitBreaker:
    """Trips after `threshold` CONSECUTIVE blocks.

    Consecutive is the whole design. One 403 in the middle of a healthy run is a burst
    boundary, and tripping on it would stop a 10,000-part run that was working perfectly; a
    solid run of them is the catalogue having closed the door. An ordinary per-part failure
    moves neither counter -- 500 parts that simply are not in the catalogue must never look
    like a rate limit.
    """

    def __init__(self, threshold: int = 5):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self.threshold = threshold
        self.consecutive = 0
        self.reason = ""

    @property
    def tripped(self) -> bool:
        return self.consecutive >= self.threshold

    def record_blocked(self, reason: str = "") -> None:
        self.consecutive += 1
        if reason:
            self.reason = reason

    def record_ok(self) -> None:
        self.consecutive = 0

    def record_failure(self) -> None:
        """A real per-part failure. Explicitly NOT a block, and explicitly not a reset either:
        a genuine failure says nothing either way about whether the catalogue is throttling."""


class PacedSource:
    """Wraps an `AssetSource` with a rate limit, retry-on-block, and block reporting.

    A wrapper rather than a change to the source, so pacing is composable and a source stays a
    plain "can you get this part its files" object. The engine cannot tell the difference: the
    key and the capabilities pass straight through.
    """

    def __init__(self, source, *, limiter=None, retries: int = 2, backoff: float = 15.0,
                 sleeper=time.sleep):
        self._source = source
        self._limiter = limiter
        self._retries = max(0, int(retries))
        self._backoff = float(backoff)
        self._sleep = sleeper

    @property
    def key(self) -> str:
        return self._source.key

    def provides(self):
        return self._source.provides()

    def supply(self, record):
        delay = self._backoff
        attempt = 0
        while True:
            if self._limiter is not None:
                self._limiter.acquire()
            outcome = self._source.supply(record)
            if not looks_rate_limited(outcome.error):
                return outcome
            if attempt >= self._retries:
                # Out of retries and still blocked. Say so explicitly: the engine reports this
                # part `deferred`, which is a different fact from "nothing can help this part".
                return outcome.as_blocked()
            self._sleep(delay)
            # Exponential, because a fixed retry against a cooldown just spends the same wall
            # clock in smaller pieces. Measured: the block cleared in ~60s.
            delay *= 2
            attempt += 1
