"""Library-scale rescan: enumerate -> pace -> lookup (read lane) -> commit (write lane) ->
checkpoint. See the plan header for the lane model and the uncommitted-staleness decision."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from stockroom.enrich.refresh import _has_data
from stockroom.enrich.rescan_state import RescanState


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


class RescanEngine:
    def __init__(self, ctx, *, pacer: "Pacer | None" = None, adapters: list | None = None):
        # adapters are INJECTED (the endpoint builds them via build_refresh_adapters and passes them
        # in) so the enrich layer never imports the api layer - no backwards dependency, no cycle.
        self._ctx = ctx
        self._adapters = list(adapters) if adapters is not None else []
        if pacer is None:
            rates = {"Mouser": float(getattr(ctx.config, "rescan_mouser_per_min", 20) or 0),
                     "DigiKey": float(getattr(ctx.config, "rescan_digikey_per_min", 60) or 0)}
            pacer = Pacer(rates)
        self._pacer = pacer
        # circuit breaker (Phase-1b-2b, reactive): a provider that comes back rate-limited or
        # auth-failed is paused for the REST of this run - no more pacing, no more calls to it -
        # so a throttled/misconfigured provider never gets hammered for the whole rescan.
        self._tripped: set[str] = set()

    def run(self, progress, *, ttl_days: int | None = None, force: bool = False, now_fn=None) -> dict:
        now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        if ttl_days is None:
            ttl_days = int(getattr(self._ctx.config, "rescan_ttl_days", 7) or 7)
        state = RescanState(self._ctx.enrich_cache_dir / "rescan-state.json")
        cutoff_iso = (now_fn() - timedelta(days=ttl_days)).isoformat()
        worklist = plan_rescan(self._ctx.index, state, cutoff_iso, force)
        total = len(worklist)
        summary = {"total": total, "updated": 0, "unchanged": 0, "no_data": 0, "failed": 0}
        progress({"pct": 0, "done": 0, "total": total, "message": f"{total} parts to refresh"})
        for i, (part_id, mpn) in enumerate(worklist):
            checked_at = now_fn().isoformat()
            try:
                per_vendor = self._lookup(mpn)
                if not per_vendor:
                    outcome = "no_data"
                else:
                    def _commit(part_id=part_id, per_vendor=per_vendor, checked_at=checked_at):
                        before = self._ctx.repo.head()
                        self._ctx.ops.refresh_procurement(part_id, per_vendor, checked_at)
                        return self._ctx.repo.head() != before

                    changed = self._ctx.jobs.run_write(_commit)
                    outcome = "updated" if changed else "unchanged"
            except Exception as exc:  # noqa: BLE001 - one part never fails the whole run (graceful)
                outcome = "failed"
                progress({"level": "warn", "part_id": part_id, "message": f"{part_id}: {exc}"})
            summary[outcome] += 1
            state.record(part_id, outcome, checked_at)
            done = i + 1
            progress({"pct": round(done * 100 / total) if total else 100, "done": done,
                      "total": total, "part_id": part_id, "outcome": outcome})
        if summary["updated"]:
            self._ctx.jobs.run_write(self._ctx.rebuild_index)
            self._ctx.jobs.run_write(self._ctx.auto_push)
        paused = sorted(self._tripped)
        summary["paused_providers"] = paused
        summary["message"] = (f"Refreshed {summary['updated']} of {total} "
                              f"({summary['unchanged']} unchanged, {summary['no_data']} no data, "
                              f"{summary['failed']} failed)")
        if paused:
            summary["message"] += f" (paused: {', '.join(paused)})"
        return summary

    def _lookup(self, mpn: str) -> list:
        """Paced per-provider lookups (runs on the READ lane). Returns [(vendor, EnrichmentResult)]
        for each enabled provider that returned real data. A provider already tripped by the
        circuit breaker (see _tripped) is skipped entirely for the rest of the run - no pace,
        no call - and any provider whose lookup just came back rate-limited/auth-failed trips
        here so every later part skips it too."""
        out = []
        for adapter in self._adapters:
            if not getattr(adapter, "enabled", False):
                continue
            vendor = getattr(adapter, "vendor", "distributor")
            if vendor in self._tripped:
                continue
            self._pacer.wait(vendor)
            result = adapter.lookup(mpn)
            last_status = getattr(adapter, "last_status", "")
            if last_status in ("rate_limited", "auth_error"):
                self._tripped.add(vendor)
            if _has_data(result):
                out.append((vendor, result))
        return out
