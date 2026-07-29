"""Pacing, backoff and the circuit breaker -- what makes a 10,000-part run survivable.

MEASURED 2026-07-27 against the real catalogue: an unpaced run of 67 parts in 52 seconds was
CloudFront-blocked after ~11 successes, and 33 of the 67 came back `HTTP 403 Forbidden` for
reasons that had nothing to do with the part. So at 10,000 parts an unpaced engine does not
just run slowly, it manufactures thousands of FALSE failures and poisons its own report.

Three behaviours follow, and each is tested here rather than assumed:

* **Pace** every catalogue call through the sliding-window limiter the repo already has.
* **Distinguish a BLOCK from a failure.** A blocked part is `deferred` -- it was never really
  attempted -- and a report that flattens the two cannot be trusted to say what is left.
* **Break the circuit.** After a run of consecutive blocks, STOP and say why. Continuing to
  hammer a WAF for another 9,900 parts is worse than useless.

Clock and sleeper are injected everywhere, so none of these tests spend real time.
"""

from stockroom.capture.complete import SourceOutcome, complete_library
from stockroom.capture.pacing import (
    CircuitBreaker,
    PacedSource,
    looks_rate_limited,
)
from stockroom.capture.requirements import Requirement
from stockroom.model.part import PartRecord


def _rec(pid="p1") -> PartRecord:
    return PartRecord(id=pid, display_name=pid, category="ICs", mpn=pid.upper())


class Recording:
    """A source whose outcome per call is scripted."""

    key = "lcsc"

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def provides(self):
        return frozenset({Requirement.KICAD_SYMBOL})

    def supply(self, record):
        self.calls += 1
        return self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]


# --- telling a block apart from a real failure ---------------------------------------------


def test_a_cloudfront_403_is_recognised_as_a_block():
    # The exact string the real converter surfaced, 33 times in one run.
    assert looks_rate_limited("easyeda2kicad failed: [ERROR] API request failed: HTTP Error 403: Forbidden")


def test_common_throttle_signals_are_recognised():
    for text in (
        "HTTP Error 429: Too Many Requests",
        "Request blocked.",
        "rate limit exceeded",
        "503 Service Unavailable",
    ):
        assert looks_rate_limited(text), text


def test_a_genuine_per_part_failure_is_not_mistaken_for_a_block():
    """The precision half. Calling a real failure a block would DEFER a part that will never
    succeed, so it comes back every run forever -- a worklist that never drains."""
    for text in (
        "the converter produced nothing for C7666",
        "easyeda2kicad failed: no such component",
        "part 103at_2 has no entry name to place a symbol under",
        "HTTP Error 404: Not Found",
        "",
    ):
        assert not looks_rate_limited(text), text


# --- the circuit breaker --------------------------------------------------------------------


def test_the_breaker_trips_after_consecutive_blocks():
    breaker = CircuitBreaker(threshold=3)
    for _ in range(2):
        breaker.record_blocked()
    assert not breaker.tripped
    breaker.record_blocked()
    assert breaker.tripped


def test_a_success_resets_the_run_of_blocks():
    # One 403 in the middle of a healthy run is noise, not a block. Tripping on it would stop
    # a 10,000-part run that was working fine.
    breaker = CircuitBreaker(threshold=3)
    breaker.record_blocked()
    breaker.record_blocked()
    breaker.record_ok()
    breaker.record_blocked()
    breaker.record_blocked()
    assert not breaker.tripped


def test_a_normal_failure_does_not_move_the_breaker():
    # 500 parts that genuinely have no LCSC entry must not look like a rate limit.
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.tripped


def test_the_breaker_reports_why_it_tripped():
    breaker = CircuitBreaker(threshold=1)
    breaker.record_blocked("HTTP Error 403: Forbidden")
    assert "403" in breaker.reason
    assert "lcsc" not in breaker.reason  # only what it was told


# --- pacing ------------------------------------------------------------------------------


def test_every_call_goes_through_the_limiter():
    waits = []

    class Limiter:
        def acquire(self):
            waits.append(1)

    inner = Recording([SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,))])
    paced = PacedSource(inner, limiter=Limiter())
    for _ in range(3):
        paced.supply(_rec())
    assert len(waits) == 3
    assert inner.calls == 3


def test_a_paced_source_keeps_the_inner_key_and_capabilities():
    # It is a wrapper, not a replacement: the engine must not be able to tell the difference.
    inner = Recording([SourceOutcome()])
    paced = PacedSource(inner, limiter=None)
    assert paced.key == "lcsc"
    assert paced.provides() == frozenset({Requirement.KICAD_SYMBOL})


def test_a_block_is_retried_with_backoff_before_being_given_up_on():
    """A single 403 may be a burst boundary rather than a ban. Retrying twice with a growing
    sleep costs seconds and saves a part; retrying forever costs a run."""
    slept: list[float] = []
    blocked = SourceOutcome(error="HTTP Error 403: Forbidden")
    ok = SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,))
    inner = Recording([blocked, blocked, ok])
    paced = PacedSource(inner, limiter=None, retries=2, backoff=1.0, sleeper=slept.append)
    outcome = paced.supply(_rec())
    assert outcome.satisfied == (Requirement.KICAD_SYMBOL,)
    assert inner.calls == 3
    assert slept == [1.0, 2.0]  # exponential, not a flat retry


def test_a_part_still_blocked_after_its_retries_is_reported_as_blocked():
    slept: list[float] = []
    blocked = SourceOutcome(error="Request blocked.")
    inner = Recording([blocked])
    paced = PacedSource(inner, limiter=None, retries=1, backoff=0.5, sleeper=slept.append)
    outcome = paced.supply(_rec())
    assert outcome.blocked is True
    assert inner.calls == 2


def test_an_ordinary_failure_is_never_retried():
    # Retrying a part that is genuinely absent from the catalogue is pure waste, 10,000 times.
    slept: list[float] = []
    inner = Recording([SourceOutcome(error="the converter produced nothing for C7666")])
    paced = PacedSource(inner, limiter=None, retries=3, backoff=1.0, sleeper=slept.append)
    outcome = paced.supply(_rec())
    assert inner.calls == 1
    assert slept == []
    assert outcome.blocked is False


# --- the engine stops instead of burning through the rest -----------------------------------


def test_the_run_stops_when_the_breaker_trips_and_says_why():
    """The whole point. Without this a 10,000-part run keeps going for hours against a WAF,
    turning one real problem into 9,900 false 'this part failed' rows."""
    blocked = SourceOutcome(error="HTTP Error 403: Forbidden")
    inner = Recording([blocked])
    paced = PacedSource(inner, limiter=None, retries=0, sleeper=lambda _s: None)
    breaker = CircuitBreaker(threshold=2)
    report = complete_library(
        [f"p{i}" for i in range(50)],
        load_record=lambda pid: _rec(pid),
        sources=[paced],
        breaker=breaker,
    )
    assert report.stopped is True
    assert "403" in report.stop_reason
    # Two parts attempted, not fifty.
    assert len(report.items) == 2
    assert [i.status for i in report.items] == ["deferred", "deferred"]


def test_a_deferred_part_is_not_counted_as_completed_or_failed():
    """`deferred` has to be its own status. Folded into `unchanged` it reads as "nothing can
    be done for this part", which is the opposite of the truth -- it was never attempted."""
    blocked = SourceOutcome(error="HTTP Error 429: Too Many Requests")
    paced = PacedSource(Recording([blocked]), limiter=None, retries=0, sleeper=lambda _s: None)
    report = complete_library(
        ["p0"], load_record=lambda pid: _rec(pid), sources=[paced],
        breaker=CircuitBreaker(threshold=99),
    )
    assert report.counts() == {"deferred": 1}
    assert report.items[0].remaining == [
        "kicad_symbol",
        "kicad_footprint",
        "kicad_model",
        "altium_symbol",
        "altium_footprint",
    ]


def test_a_healthy_run_is_unaffected_by_the_breaker():
    ok = SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,))

    class Filling(Recording):
        def supply(self, record):
            super().supply(record)
            from stockroom.model.part import AssetRef

            record.assets_for("kicad").set("symbol", AssetRef(lib="L", name="N"))
            return ok

    records = {f"p{i}": _rec(f"p{i}") for i in range(5)}
    paced = PacedSource(Filling([ok]), limiter=None, retries=0, sleeper=lambda _s: None)
    report = complete_library(
        list(records), load_record=lambda pid: records[pid], sources=[paced],
        breaker=CircuitBreaker(threshold=2),
    )
    assert report.stopped is False
    # The source made real progress but filled only one of the five required CAD roles.
    assert report.counts() == {"improved": 5}
