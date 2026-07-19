from dataclasses import dataclass
from datetime import datetime, timezone

from stockroom.enrich.rescan import Pacer, RescanEngine
from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced


@dataclass
class _Row:
    id: str
    mpn: str = ""


class _Index:
    def __init__(self, rows):
        self._rows = rows

    def search(self, query="", category=None, complete_only=False):
        return list(self._rows)


class _Adapter:
    def __init__(self, vendor, results, statuses=None):
        self.vendor, self.enabled, self._results = vendor, True, results
        self.calls = []
        self._statuses = statuses or {}
        self.last_status = ""

    def lookup(self, mpn):
        self.calls.append(mpn)
        self.last_status = self._statuses.get(mpn, "ok")
        return self._results.get(mpn, EnrichmentResult())


class _Ops:
    def __init__(self, changed_ids):
        self._changed = set(changed_ids)
        self.commits = []

    def refresh_procurement(self, part_id, per_vendor, now_iso):
        self.commits.append(part_id)
        return part_id  # stand-in record


class _Repo:
    def __init__(self, changed_ids, ops):
        self._changed, self._ops = set(changed_ids), ops
        self._h = 0

    def head(self):
        # emulate "a commit happened" by bumping head when the just-committed part was a changed one
        if self._ops.commits and self._ops.commits[-1] in self._changed:
            self._h += 1
        return str(self._h)


class _Jobs:
    def run_write(self, fn):
        return fn()


class _Ctx:
    def __init__(self, tmp_path, index, ops, adapters, changed_ids):
        from types import SimpleNamespace
        self.index, self.ops = index, ops
        self.jobs = _Jobs()
        self.enrich_cache_dir = tmp_path
        self.config = SimpleNamespace(rescan_ttl_days=7, rescan_mouser_per_min=0, rescan_digikey_per_min=0)
        self.repo = _Repo(changed_ids, ops)
        self.rebuilt = self.pushed = 0

    def rebuild_index(self):
        self.rebuilt += 1

    def auto_push(self):
        self.pushed += 1


def _priced(mpn):
    r = EnrichmentResult()
    r.mpn = Sourced(mpn, "x", "high")
    r.price_breaks = [PriceBreak(1, 0.5)]
    return r


def _fixed_now():
    return datetime(2026, 7, 18, tzinfo=timezone.utc)


class _RecordingPacer(Pacer):
    """A Pacer that records every provider it was asked to wait on, so a test can assert the
    engine paces exactly once per enabled provider per processed part - no more, no less."""

    def __init__(self):
        super().__init__({})
        self.calls: list[str] = []

    def wait(self, provider):
        self.calls.append(provider)
        super().wait(provider)


def test_run_refreshes_stale_mpn_parts_and_summarizes(tmp_path):
    index = _Index([_Row("a", "MPN-A"), _Row("b", ""), _Row("c", "MPN-C")])
    ops = _Ops(changed_ids=["a"])                         # only part a actually changes
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A")})]  # only MPN-A returns data
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=["a"])
    events = []
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        events.append, force=True, now_fn=_fixed_now)
    assert summary["total"] == 2                          # a, c (b has no MPN)
    assert summary["updated"] == 1 and summary["unchanged"] == 0 and summary["no_data"] == 1
    assert ops.commits == ["a"]                           # c returned no data -> the write lane is skipped
    assert ctx.rebuilt == 1 and ctx.pushed == 1           # one rebuild + one push, at the end
    assert any(e.get("outcome") == "updated" for e in events)


def test_a_part_with_data_but_no_change_is_unchanged_and_does_not_rebuild_or_push(tmp_path):
    index = _Index([_Row("a", "MPN-A")])
    ops = _Ops(changed_ids=[])                             # "a" is NOT a changed id -> head never moves
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A")})]  # returns real data
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=[])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert summary["total"] == 1
    assert summary["unchanged"] == 1 and summary["updated"] == 0
    assert ops.commits == ["a"]                            # it had data, so still committed-through
    # the guarantee: a non-empty worklist that changes nothing must NOT rebuild the index or push
    assert ctx.rebuilt == 0 and ctx.pushed == 0


def test_incremental_skips_fresh_parts(tmp_path):
    from stockroom.enrich.rescan_state import RescanState
    index = _Index([_Row("a", "MPN-A")])
    RescanState(tmp_path / "rescan-state.json").record("a", "updated", "2026-07-18T00:00:00+00:00")
    ops = _Ops(changed_ids=[])
    adapters = [_Adapter("Mouser", {})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=[])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=False, now_fn=_fixed_now)   # a checked today, ttl 7d -> fresh -> skipped
    assert summary["total"] == 0 and ops.commits == []
    assert ctx.rebuilt == 0 and ctx.pushed == 0


def test_a_failing_part_is_recorded_and_never_fails_the_run(tmp_path):
    from stockroom.enrich.rescan_state import RescanState
    index = _Index([_Row("a", "MPN-A"), _Row("c", "MPN-C")])

    class _Boom(_Ops):
        def refresh_procurement(self, part_id, per_vendor, now_iso):
            if part_id == "a":
                raise RuntimeError("write blew up")
            return super().refresh_procurement(part_id, per_vendor, now_iso)

    ops = _Boom(changed_ids=["c"])
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A"), "MPN-C": _priced("MPN-C")})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=["c"])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert summary["failed"] == 1 and summary["updated"] == 1     # a failed, c updated - run finished
    assert RescanState(tmp_path / "rescan-state.json").outcome("a") == "failed"


def test_a_rate_limited_provider_is_paused_for_the_rest_of_the_run(tmp_path):
    # the FIRST part trips the breaker (rate_limited); every later part must skip that
    # provider entirely - no pace, no call - and the run still finishes without raising.
    index = _Index([_Row("a", "MPN-A"), _Row("b", "MPN-B"), _Row("c", "MPN-C")])
    ops = _Ops(changed_ids=[])
    adapters = [_Adapter("DigiKey", {}, statuses={"MPN-A": "rate_limited"})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=[])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert summary["total"] == 3
    assert adapters[0].calls == ["MPN-A"]                 # b, c never call the paused provider
    assert summary["paused_providers"] == ["DigiKey"]
    assert "paused: DigiKey" in summary["message"]
    assert summary["failed"] == 0                         # never fails the run


def test_an_auth_error_also_trips_the_breaker(tmp_path):
    index = _Index([_Row("a", "MPN-A"), _Row("b", "MPN-B")])
    ops = _Ops(changed_ids=[])
    adapters = [_Adapter("Mouser", {}, statuses={"MPN-A": "auth_error"})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=[])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert adapters[0].calls == ["MPN-A"]
    assert summary["paused_providers"] == ["Mouser"]


def test_a_raising_progress_callback_never_aborts_the_run(tmp_path):
    # a subscriber's progress callback throwing (a broken SSE consumer, a bug in the UI
    # handler) must not abort the run itself - "one part never fails the run" also has to
    # hold when the failure is in the progress plumbing, not the lookup/commit.
    index = _Index([_Row("a", "MPN-A"), _Row("b", "MPN-B")])
    ops = _Ops(changed_ids=["a", "b"])
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A"), "MPN-B": _priced("MPN-B")})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=["a", "b"])

    def _boom_progress(data):
        raise RuntimeError("progress callback exploded")

    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        _boom_progress, force=True, now_fn=_fixed_now)
    assert summary["total"] == 2
    assert summary["updated"] == 2
    assert ops.commits == ["a", "b"]


def test_no_paused_providers_when_nothing_trips_the_breaker(tmp_path):
    index = _Index([_Row("a", "MPN-A")])
    ops = _Ops(changed_ids=["a"])
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A")})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=["a"])
    summary = RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert summary["paused_providers"] == []
    assert "paused" not in summary["message"]


def test_pacer_wait_is_called_once_per_enabled_provider_per_processed_part(tmp_path):
    index = _Index([_Row("a", "MPN-A"), _Row("b", "MPN-B")])
    ops = _Ops(changed_ids=[])
    adapters = [_Adapter("Mouser", {}), _Adapter("DigiKey", {})]
    pacer = _RecordingPacer()
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=[])
    RescanEngine(ctx, pacer=pacer, adapters=adapters).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    # 2 parts x 2 enabled providers, in adapter order, every single time - not skipped,
    # not batched, not deduped.
    assert pacer.calls == ["Mouser", "DigiKey", "Mouser", "DigiKey"]


def test_a_disabled_adapter_is_skipped_and_never_looked_up(tmp_path):
    index = _Index([_Row("a", "MPN-A")])
    ops = _Ops(changed_ids=[])
    adapter = _Adapter("Mouser", {"MPN-A": _priced("MPN-A")})
    adapter.enabled = False
    ctx = _Ctx(tmp_path, index, ops, [adapter], changed_ids=[])
    pacer = _RecordingPacer()
    summary = RescanEngine(ctx, pacer=pacer, adapters=[adapter]).run(
        lambda e: None, force=True, now_fn=_fixed_now)
    assert adapter.calls == []          # lookup is never called on a disabled adapter
    assert pacer.calls == []            # and it is never even paced
    assert summary["no_data"] == 1      # so the part just comes back with nothing


def test_a_failed_part_fires_a_warn_progress_event_with_the_part_id(tmp_path):
    index = _Index([_Row("a", "MPN-A"), _Row("c", "MPN-C")])

    class _Boom(_Ops):
        def refresh_procurement(self, part_id, per_vendor, now_iso):
            if part_id == "a":
                raise RuntimeError("write blew up")
            return super().refresh_procurement(part_id, per_vendor, now_iso)

    ops = _Boom(changed_ids=["c"])
    adapters = [_Adapter("Mouser", {"MPN-A": _priced("MPN-A"), "MPN-C": _priced("MPN-C")})]
    ctx = _Ctx(tmp_path, index, ops, adapters, changed_ids=["c"])
    events = []
    RescanEngine(ctx, pacer=Pacer({}), adapters=adapters).run(
        events.append, force=True, now_fn=_fixed_now)
    warns = [e for e in events if e.get("level") == "warn"]
    assert len(warns) == 1
    assert warns[0]["part_id"] == "a"
    assert "write blew up" in warns[0]["message"]
