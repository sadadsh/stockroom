"""The automatic completion engine: fill every asset a part still needs from sources that
need no human.

These tests pin the two properties the owner's bar actually rests on -- "all files for a
component" and "if i handed u 10000 components it should work fully endlessly" -- so they
lean hard on STREAMING, per-part isolation and resumability rather than on any one source.
"""

from stockroom.capture.complete import (
    CompletionItem,
    SourceOutcome,
    complete_library,
    complete_part,
    iter_incomplete,
    sourceable_needs,
)
from stockroom.capture.requirements import Requirement
from stockroom.model.part import AssetRef, PartRecord


def _rec(part_id="p1", **kw) -> PartRecord:
    return PartRecord(id=part_id, display_name=part_id, category="ICs", mpn=part_id.upper(), **kw)


class FakeSource:
    """A source that fills the requirements it is told to, by mutating the record it is given."""

    def __init__(self, key, provides, fills=None, error="", calls=None):
        self.key = key
        self._provides = frozenset(provides)
        self._fills = frozenset(fills if fills is not None else provides)
        self._error = error
        self.calls = calls if calls is not None else []

    def provides(self):
        return self._provides

    def supply(self, record):
        self.calls.append(record.id)
        if self._error:
            return SourceOutcome(error=self._error)
        for req in self._fills:
            tool, _, kind = req.value.partition("_")
            record.assets_for(tool).set(kind, AssetRef(lib="L", name="N"))
        return SourceOutcome(satisfied=tuple(sorted(self._fills, key=lambda r: r.value)))


def _loader(records):
    """A load_record callable over a dict. Deliberately a CALLABLE, never a captured handle:
    a long run outlives whatever object it started with."""
    return lambda pid: records[pid]


# --- what a part still needs, filtered to what a source could actually give it ---------


def test_sourceable_needs_only_reports_what_a_registered_source_can_supply():
    # An Altium gap with no Altium source registered is NOT actionable work. Reporting it as
    # work is how a run ends "0 of 66 completed" forever with nothing to do about it.
    rec = _rec()
    kicad_only = FakeSource("k", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    assert sourceable_needs(rec, [kicad_only]) == [
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
    ]


def test_sourceable_needs_is_empty_when_the_part_already_has_those_assets():
    rec = _rec()
    rec.assets_for("kicad").set("symbol", AssetRef(lib="L", name="N"))
    rec.assets_for("kicad").set("footprint", AssetRef(lib="L", name="N"))
    src = FakeSource("k", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    assert sourceable_needs(rec, [src]) == []


def test_sourceable_needs_adds_a_tool_the_moment_a_source_for_it_is_registered():
    # The tool-agnostic promise, stated as a test: an Altium source plugs in and the SAME
    # engine starts reporting and filling Altium gaps, with no branch anywhere on "altium".
    rec = _rec()
    altium = FakeSource("a", [Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT])
    assert sourceable_needs(rec, [altium]) == [
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    ]


# --- one part -------------------------------------------------------------------------


def test_complete_part_runs_sources_until_the_needs_are_met():
    rec = _rec()
    records = {"p1": rec}
    src = FakeSource("lcsc", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    item = complete_part("p1", load_record=_loader(records), sources=[src])
    assert item.status == "completed"
    assert item.satisfied == ["kicad_symbol", "kicad_footprint"]
    assert item.remaining == []
    assert item.sources == ["lcsc"]


def test_complete_part_reports_improved_when_only_some_needs_were_met():
    # Honest partial completion. A part that gained a symbol and a footprint but no 3D model
    # is NOT "completed", and a report that says it is cannot answer "all files".
    rec = _rec()
    records = {"p1": rec}
    src = FakeSource(
        "lcsc",
        [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT, Requirement.KICAD_MODEL],
        fills=[Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT],
    )
    item = complete_part("p1", load_record=_loader(records), sources=[src])
    assert item.status == "improved"
    assert item.remaining == ["kicad_model"]


def test_complete_part_is_a_no_op_when_nothing_is_needed():
    # Idempotence, which is what makes a 10k run RESUMABLE: re-running costs nothing on the
    # parts already done, so "run it again" is never a full-price operation.
    rec = _rec()
    for kind in ("symbol", "footprint", "model"):
        rec.assets_for("kicad").set(kind, AssetRef(lib="L", name="N"))
    src = FakeSource("lcsc", [Requirement.KICAD_SYMBOL])
    item = complete_part("p1", load_record=_loader({"p1": rec}), sources=[src])
    assert item.status == "already-complete"
    assert src.calls == []


def test_a_source_that_errors_is_a_row_not_a_lost_part():
    rec = _rec()
    bad = FakeSource("bad", [Requirement.KICAD_SYMBOL], error="network down")
    item = complete_part("p1", load_record=_loader({"p1": rec}), sources=[bad])
    assert item.status == "unchanged"
    assert "network down" in item.error


def test_a_source_that_raises_is_caught_and_the_next_source_still_runs():
    class Exploding:
        key = "boom"

        def provides(self):
            return frozenset({Requirement.KICAD_SYMBOL})

        def supply(self, record):
            raise RuntimeError("converter segfaulted")

    rec = _rec()
    good = FakeSource("passive", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    item = complete_part("p1", load_record=_loader({"p1": rec}), sources=[Exploding(), good])
    assert item.status == "completed"
    assert "converter segfaulted" in item.error
    assert item.sources == ["passive"]


def test_a_later_source_is_skipped_once_its_requirements_are_already_met():
    # Sources are ordered cheapest-first (offline decode before a network fetch). Running an
    # expensive one for an asset that already landed is pure waste at 10k parts.
    rec = _rec()
    first = FakeSource("offline", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    second = FakeSource("network", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    item = complete_part("p1", load_record=_loader({"p1": rec}), sources=[first, second])
    assert second.calls == []
    assert item.sources == ["offline"]


def test_a_part_that_cannot_be_loaded_is_a_row_not_an_abort():
    def boom(_pid):
        raise FileNotFoundError("record went missing mid-run")

    item = complete_part("p1", load_record=boom, sources=[])
    assert item.status == "error"
    assert "went missing" in item.error


# --- many parts, at scale ---------------------------------------------------------------


def test_complete_library_streams_and_never_materialises_the_whole_worklist():
    """The 10k property. The engine must consume a GENERATOR and finish each part before the
    next is produced, so memory is one record deep no matter how long the list is."""
    seen_order: list[str] = []
    records = {f"p{i}": _rec(f"p{i}") for i in range(5)}

    def worklist():
        for i in range(5):
            seen_order.append(f"produced:p{i}")
            yield f"p{i}"

    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])

    def load(pid):
        seen_order.append(f"worked:{pid}")
        return records[pid]

    report = complete_library(worklist(), load_record=load, sources=[src])
    assert len(report.items) == 5
    # Strictly interleaved: every part is finished before the next is produced. A list()
    # anywhere in the engine would put all five "produced" entries ahead of the first
    # "worked" one. (A part is loaded more than once by design -- the engine re-reads to
    # confirm what actually landed -- so this asserts ordering, not call counts.)
    for i in range(4):
        assert seen_order.index(f"worked:p{i}") < seen_order.index(f"produced:p{i + 1}")


def test_one_failing_part_never_aborts_the_batch():
    records = {f"p{i}": _rec(f"p{i}") for i in range(4)}

    def load(pid):
        if pid == "p2":
            raise RuntimeError("disk read error")
        return records[pid]

    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    report = complete_library(["p0", "p1", "p2", "p3"], load_record=load, sources=[src])
    assert [i.status for i in report.items] == [
        "completed",
        "completed",
        "error",
        "completed",
    ]
    assert report.counts()["completed"] == 3


def test_a_run_can_be_stopped_and_reports_what_it_finished():
    """"Endlessly" has to mean STOPPABLE, or a 10k run is a hostage situation. The stop is
    cooperative and checked BEFORE each part, so a stopped run never leaves a half-attached
    part behind -- each part is its own atomic unit."""
    records = {f"p{i}": _rec(f"p{i}") for i in range(10)}
    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    done: list[str] = []

    def on_progress(ev):
        done.append(ev["part_id"])

    report = complete_library(
        [f"p{i}" for i in range(10)],
        load_record=_loader(records),
        sources=[src],
        on_progress=on_progress,
        should_stop=lambda: len(done) >= 3,
    )
    assert report.stopped is True
    assert len(report.items) == 3
    # Everything it DID do is really done; nothing is half-finished.
    assert all(i.status == "completed" for i in report.items)


def test_progress_names_the_part_it_is_on():
    # A bar with no part name cannot be told from a hang -- the same reason bulk_import
    # streams the query it is working.
    records = {"p0": _rec("p0")}
    events: list[dict] = []
    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    complete_library(
        ["p0"], load_record=_loader(records), sources=[src], total=1,
        on_progress=events.append,
    )
    assert events[0]["part_id"] == "p0"
    assert events[0]["mpn"] == "P0"
    assert events[0]["total"] == 1


def test_report_counts_group_by_status():
    records = {f"p{i}": _rec(f"p{i}") for i in range(3)}
    for kind in ("symbol", "footprint", "model"):
        records["p2"].assets_for("kicad").set(kind, AssetRef(lib="L", name="N"))
    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    report = complete_library(
        ["p0", "p1", "p2"], load_record=_loader(records), sources=[src]
    )
    assert report.counts() == {"completed": 2, "already-complete": 1}


# --- deriving the worklist from the library ---------------------------------------------


def test_iter_incomplete_yields_only_parts_a_source_could_help_and_stays_lazy(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    full = _rec("full")
    for kind in ("symbol", "footprint", "model"):
        full.assets_for("kicad").set(kind, AssetRef(lib="L", name="N"))
    empty = _rec("empty")
    for rec in (full, empty):
        (parts / f"{rec.id}.json").write_text(rec.dumps(), encoding="utf-8")

    src = FakeSource("s", [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT])
    got = iter_incomplete(parts, load_record=lambda pid: {"full": full, "empty": empty}[pid],
                          sources=[src])
    assert not isinstance(got, list)  # a generator: 10k records are never all in memory
    assert list(got) == ["empty"]


def test_iter_incomplete_skips_an_unreadable_record_instead_of_dying(tmp_path):
    # One corrupt JSON in a 10k library must not make the whole worklist unbuildable.
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "bad.json").write_text("{not json", encoding="utf-8")
    good = _rec("good")
    (parts / "good.json").write_text(good.dumps(), encoding="utf-8")

    def load(pid):
        if pid == "bad":
            raise ValueError("corrupt")
        return good

    src = FakeSource("s", [Requirement.KICAD_SYMBOL])
    assert list(iter_incomplete(parts, load_record=load, sources=[src])) == ["good"]


def test_completion_item_is_json_safe():
    item = CompletionItem(part_id="p", mpn="M", status="completed")
    assert item.to_dict()["part_id"] == "p"
