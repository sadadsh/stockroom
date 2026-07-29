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
(`enrich/ratelimit.py`), rather than a second hand-rolled one.

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

import json
import math
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

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
_DURABLE_LEDGER_LOCK = threading.RLock()


class DurableSlidingWindowLimiter:
    """A provider-wide sliding window that survives jobs, processes, and app restarts.

    Browser-profile ownership already serializes one provider's full session, but a restart releases
    that lock and must not erase recent request starts. This small machine-local ledger stores only
    wall-clock timestamps. Its own OS file lock makes the rate contract independent of which process
    currently owns the browser profile.
    """

    def __init__(
        self,
        path: Path,
        limit: int,
        window: float,
        *,
        clock=time.time,
        sleeper=time.sleep,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if not math.isfinite(window) or window <= 0:
            raise ValueError("window must be a positive finite duration")
        self.path = Path(path)
        self.limit = int(limit)
        self.window = float(window)
        self._clock = clock
        self._sleep = sleeper

    def acquire(self, *, should_cancel=None) -> bool:
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("should_cancel must be callable")
        while True:
            if should_cancel is not None and should_cancel():
                return False
            with _locked_rate_ledger(self.path):
                now = float(self._clock())
                if not math.isfinite(now):
                    raise RuntimeError("provider rate-limit clock is not finite")
                starts = self._read()
                if any(start > now + 1.0 for start in starts):
                    raise RuntimeError(
                        "provider rate-limit clock moved backward; automatic access stopped"
                    )
                starts = [start for start in starts if now - start < self.window]
                if len(starts) < self.limit:
                    starts.append(now)
                    self._write(starts)
                    return True
                wait = self.window - (now - starts[0]) + 0.1
            remaining = max(0.1, wait)
            while remaining > 0:
                if should_cancel is not None and should_cancel():
                    return False
                interval = min(0.25, remaining)
                self._sleep(interval)
                remaining -= interval

    def _read(self) -> list[float]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            raw = payload["starts"]
            if payload.get("schema") != "stockroom-provider-rate/v1" or not isinstance(raw, list):
                raise ValueError
            starts = [float(value) for value in raw]
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"provider rate ledger is unreadable at {self.path}; automatic access stopped"
            ) from exc
        if any(not math.isfinite(value) or value < 0 for value in starts):
            raise RuntimeError(
                f"provider rate ledger is invalid at {self.path}; automatic access stopped"
            )
        return sorted(starts)

    def _write(self, starts: list[float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema": "stockroom-provider-rate/v1",
                        "starts": starts,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(
                f"could not persist provider rate ledger at {self.path}; automatic access stopped"
            ) from exc


@contextmanager
def _locked_rate_ledger(ledger: Path):
    """Cross-process lock for one durable rate ledger."""

    lock_path = ledger.with_suffix(ledger.suffix + ".lock")
    with _DURABLE_LEDGER_LOCK:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + 10.0
        acquired = False
        try:
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:  # pragma: no cover - Windows authoritative; tests remain portable
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError) as exc:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            f"provider rate ledger stayed busy at {ledger}"
                        ) from exc
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - Windows authoritative; tests remain portable
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


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
