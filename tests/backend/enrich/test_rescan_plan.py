from dataclasses import dataclass

from stockroom.enrich.rescan import Pacer, plan_rescan
from stockroom.enrich.rescan_state import RescanState


@dataclass
class _Row:
    id: str
    mpn: str = ""


class _Index:
    def __init__(self, rows):
        self._rows = rows

    def search(self, query="", category=None, complete_only=False):
        return list(self._rows)


def test_plan_skips_no_mpn_and_fresh_parts_unless_forced(tmp_path):
    index = _Index([_Row("a", "MPN-A"), _Row("b", ""), _Row("c", "MPN-C")])
    state = RescanState(tmp_path / "st.json")
    state.record("a", "updated", "2026-07-18T10:00:00+00:00")     # a is fresh
    cutoff = "2026-07-11T10:00:00+00:00"
    # incremental: b dropped (no MPN), a dropped (fresh), c kept (stale)
    assert plan_rescan(index, state, cutoff, force=False) == [("c", "MPN-C")]
    # force: every MPN-bearing part, fresh or not (b still dropped - nothing to look up)
    assert plan_rescan(index, state, cutoff, force=True) == [("a", "MPN-A"), ("c", "MPN-C")]


def test_pacer_waits_the_minimum_interval_between_same_provider_calls():
    clock = [0.0]
    slept = []
    pacer = Pacer({"Mouser": 60}, now=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    pacer.wait("Mouser")                 # first call: no wait
    assert slept == []
    pacer.wait("Mouser")                 # immediately again: 60/min -> 1s min interval -> sleeps ~1s
    assert slept and abs(slept[0] - 1.0) < 1e-9


def test_pacer_no_rate_configured_never_waits():
    slept = []
    pacer = Pacer({}, now=lambda: 0.0, sleep=lambda s: slept.append(s))
    pacer.wait("Mouser")
    pacer.wait("Mouser")
    assert slept == []
