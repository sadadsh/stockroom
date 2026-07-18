"""Library-scale rescan: enumerate -> pace -> lookup (read lane) -> commit (write lane) ->
checkpoint. See the plan header for the lane model and the uncommitted-staleness decision."""
from __future__ import annotations

import time


def plan_rescan(index, state, cutoff_iso: str, force: bool) -> list[tuple[str, str]]:
    """(part_id, mpn) for each library part worth refreshing: it has an MPN, and (unless force)
    it was NOT already checked at/after cutoff_iso. No-MPN parts are dropped (nothing to look up);
    fresh parts are dropped (incremental). Deterministic index order."""
    out: list[tuple[str, str]] = []
    for row in index.search(""):
        if not row.mpn:
            continue
        if not force and state.is_fresh(row.id, cutoff_iso):
            continue
        out.append((row.id, row.mpn))
    return out


class Pacer:
    """Per-provider minimum-interval pacer so a rescan trickles within each API's published quota
    instead of bursting into a 429. `per_minute` is calls/minute per provider; `wait(provider)`
    blocks (via the injected sleep) only as long as needed since that provider's last call.
    Deterministic under an injected clock/sleep."""

    def __init__(self, per_minute: dict[str, float], *, now=None, sleep=None):
        self._min_interval = {k: (60.0 / v) for k, v in per_minute.items() if v and v > 0}
        self._last: dict[str, float] = {}
        self._now = now or time.monotonic
        self._sleep = sleep or time.sleep

    def wait(self, provider: str) -> None:
        interval = self._min_interval.get(provider, 0.0)
        if interval <= 0:
            self._last[provider] = self._now()
            return
        last = self._last.get(provider)
        if last is not None:
            gap = self._now() - last
            if gap < interval:
                self._sleep(interval - gap)
        self._last[provider] = self._now()
