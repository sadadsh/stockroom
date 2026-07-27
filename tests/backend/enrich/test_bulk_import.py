"""The bulk import seam: a list of part numbers becomes library parts.

`enrich/bulk.py` had been enrichment-only and wired to nothing (no route, no UI) while the
batch plan recorded it as shipped. These tests define what "import a list" actually has to do,
and each is written against a failure that is cheap to ship and expensive to find:

* a distributor stock number must be resolved BEFORE enrichment, not fed to every source;
* re-running must not duplicate a part;
* one bad part must never abort the batch;
* an incomplete part must be REPORTED, never force-added past the complete-to-add gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.enrich.bulk import bulk_import
from stockroom.enrich.pipeline import ResolvedQuery


class _Pipeline:
    """Resolves stock numbers from a table and fills a candidate the way the real one does."""

    def __init__(self, resolve=None, fill=None, raises=()):
        self._resolve = resolve or {}
        self._fill = fill or {}
        self._raises = set(raises)
        self.enriched: list[str] = []

    def resolve_to_mpn(self, query):
        mpn = self._resolve.get(query)
        if mpn is None:
            return ResolvedQuery(mpn=query, query=query)
        return ResolvedQuery(mpn=mpn, query=query, vendor="mouser", resolved=True)

    def enrich_candidate(self, candidate, overwrite=None):
        self.enriched.append(candidate.mpn)
        if candidate.mpn in self._raises:
            raise RuntimeError("boom")
        for attr, value in self._fill.get(candidate.mpn, {}).items():
            setattr(candidate, attr, value)
        return candidate


def _complete(datasheet: Path):
    from stockroom.model.part import Purchase

    return {
        "manufacturer": "TI",
        "description": "a real part",
        "category": "ICs",
        "datasheet_path": datasheet,
        "purchase": [Purchase(vendor="mouser", url="https://mouser/x")],
    }


class _Ops:
    def __init__(self, fail_on=()):
        self.added: list = []
        self._fail_on = set(fail_on)

    def add_part(self, staged, require_complete: bool = True):
        if staged.mpn in self._fail_on:
            raise OSError("disk on fire")
        self.added.append(staged)

        class _R:
            id = f"{staged.mpn.lower()}"
            display_name = staged.display_name

        return _R


def _index(existing: dict):
    class _Row:
        def __init__(self, pid):
            self.id = pid

    class _Index:
        def find_by_mpn(self, mpn):
            pid = existing.get(mpn)
            return [_Row(pid)] if pid else []

    return _Index()


def test_a_stock_number_is_resolved_before_anything_is_enriched(tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(resolve={"595-TPS62130RGTR": "TPS62130RGTR"},
                     fill={"TPS62130RGTR": _complete(ds)})
    ops = _Ops()
    report = bulk_import(["595-TPS62130RGTR"], pipe, ops, index=_index({}))
    assert pipe.enriched == ["TPS62130RGTR"], "the SKU itself must never reach enrichment"
    item = report.items[0]
    assert item.status == "added"
    assert item.query == "595-TPS62130RGTR"
    assert item.mpn == "TPS62130RGTR"
    assert ops.added[0].mpn == "TPS62130RGTR"


def test_a_part_already_in_the_library_is_skipped_not_duplicated(tmp_path):
    pipe = _Pipeline(resolve={"595-TPS62130RGTR": "TPS62130RGTR"})
    ops = _Ops()
    report = bulk_import(["595-TPS62130RGTR"], pipe, ops,
                         index=_index({"TPS62130RGTR": "tps62130rgtr"}))
    assert report.items[0].status == "exists"
    assert report.items[0].part_id == "tps62130rgtr"
    assert ops.added == []
    assert pipe.enriched == [], "an existing part costs no enrichment call"


def test_an_incomplete_part_is_reported_and_never_force_added(tmp_path):
    pipe = _Pipeline(fill={"MYSTERY": {"manufacturer": "?"}})
    ops = _Ops()
    report = bulk_import(["MYSTERY"], pipe, ops, index=_index({}))
    item = report.items[0]
    assert item.status == "incomplete"
    assert item.missing, "it must say WHICH fields are missing"
    assert ops.added == []


def test_one_bad_part_never_aborts_the_batch(tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"GOOD": _complete(ds)}, raises=["BAD"])
    ops = _Ops()
    report = bulk_import(["BAD", "GOOD"], pipe, ops, index=_index({}))
    assert [i.status for i in report.items] == ["error", "added"]
    assert report.items[0].error
    assert len(ops.added) == 1


def test_a_failing_add_is_an_error_row_not_a_crash(tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"GOOD": _complete(ds), "ALSOGOOD": _complete(ds)})
    ops = _Ops(fail_on=["GOOD"])
    report = bulk_import(["GOOD", "ALSOGOOD"], pipe, ops, index=_index({}))
    assert [i.status for i in report.items] == ["error", "added"]


def test_dry_run_writes_nothing_but_reports_what_would_land(tmp_path):
    """The owner's library is a git repo; a 169-part import must be previewable before it
    commits anything. Without this the only way to find out what an import does is to do it."""
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"GOOD": _complete(ds)})
    ops = _Ops()
    report = bulk_import(["GOOD"], pipe, ops, index=_index({}), dry_run=True)
    assert report.items[0].status == "would-add"
    assert ops.added == []


def test_duplicate_queries_collapse_to_one_import(tmp_path):
    """The register groups by line item, and three of its rows name the same part number."""
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"GOOD": _complete(ds)})
    ops = _Ops()
    report = bulk_import(["GOOD", "GOOD"], pipe, ops, index=_index({}))
    assert len(ops.added) == 1
    assert [i.status for i in report.items] == ["added", "duplicate"]


def test_a_part_added_earlier_in_the_same_run_is_not_added_twice(tmp_path):
    """Two DIFFERENT queries can resolve to the same manufacturer part (a Mouser SKU and a
    DigiKey number for one device). The index cannot see the first one yet, because the index
    is only rebuilt after the run."""
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(resolve={"595-X": "SAMEPART", "296-Y-ND": "SAMEPART"},
                     fill={"SAMEPART": _complete(ds)})
    ops = _Ops()
    report = bulk_import(["595-X", "296-Y-ND"], pipe, ops, index=_index({}))
    assert len(ops.added) == 1
    assert [i.status for i in report.items] == ["added", "duplicate"]


def test_progress_names_the_part_it_is_on(tmp_path):
    """A 169-part run is minutes long; a bar with no part name is indistinguishable from a
    hang (the same reason the Altium embed job reports per-part)."""
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"A": _complete(ds), "B": _complete(ds)})
    seen = []
    bulk_import(["A", "B"], pipe, _Ops(), index=_index({}),
                on_progress=lambda done, total, q: seen.append((done, total, q)))
    assert seen == [(0, 2, "A"), (1, 2, "B")]


def test_the_report_counts_every_outcome(tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"A": _complete(ds), "C": {"manufacturer": "?"}}, raises=["D"])
    report = bulk_import(["A", "B", "C", "D"], pipe, _Ops(),
                         index=_index({"B": "b-part"}))
    assert report.counts() == {"added": 1, "exists": 1, "incomplete": 1, "error": 1}
    assert len(report.items) == 4


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_queries_are_dropped_not_looked_up(blank):
    pipe = _Pipeline()
    report = bulk_import([blank], pipe, _Ops(), index=_index({}))
    assert report.items == []
    assert pipe.enriched == []


# --------------------------------------------------------------------------- #
# The passive lane. This is what makes an import produce PLACEABLE parts rather than
# records: a resistor/capacitor/inductor MPN resolves the KiCad STOCK symbol, footprint
# and 3D model offline, with no vendor download at all. Without this routing the decoder
# could be perfect and every capacitor would still land with no files.
# --------------------------------------------------------------------------- #


class _PassivePipeline:
    """Fills a candidate the way the real one does for a Murata MLCC."""

    def __init__(self, resolve):
        self._resolve = resolve

    def resolve_to_mpn(self, query):
        from stockroom.enrich.pipeline import ResolvedQuery

        mpn = self._resolve.get(query)
        if mpn is None:
            return ResolvedQuery(mpn=query, query=query)
        return ResolvedQuery(mpn=mpn, query=query, vendor="mouser", resolved=True)

    def enrich_candidate(self, candidate, overwrite=None):
        from stockroom.model.part import Provenance, Purchase

        candidate.manufacturer = "Murata"
        candidate.description = "100 nF X7R 0402"
        candidate.category = "Capacitors"
        candidate.specs = {"Capacitance": "100 nF", "Tolerance": "10%"}
        candidate.purchase = [Purchase(vendor="mouser", url="https://mouser/x")]
        candidate.provenance = Provenance(source="mouser", source_url="https://ds/x.pdf")
        return candidate


class _PassiveOps:
    def __init__(self):
        self.passives: list = []
        self.plain: list = []

    def add_passive_part(self, record, require_complete: bool = True):
        self.passives.append(record)
        record.id = record.mpn.lower()
        return record

    def add_part(self, staged, require_complete: bool = True):
        self.plain.append(staged)

        class _R:
            id = "plain"
            display_name = staged.display_name

        return _R


def test_a_capacitor_lands_with_stock_kicad_symbol_footprint_and_3d():
    pipe = _PassivePipeline({"81-GRM155R71C104KA88D": "GRM155R71C104KA88D"})
    ops = _PassiveOps()
    report = bulk_import(["81-GRM155R71C104KA88D"], pipe, ops, index=_index({}))

    assert report.items[0].status == "added"
    assert ops.plain == [], "a passive must not take the file-less path"
    assert len(ops.passives) == 1
    record = ops.passives[0]
    kicad = record.assets_for("kicad")
    assert kicad.symbol.lib == "Device" and kicad.symbol.name == "C"
    assert kicad.footprint.lib == "Capacitor_SMD"
    assert kicad.footprint.name == "C_0402_1005Metric"
    # `record.passive` is what makes the 3D model RENDER. The model endpoint branches on it and
    # resolves the model from the stock footprint lib_id at serve time
    # (`previews.model_glb`: `if rec.passive: stock_model_file(...)`), so a passive deliberately
    # carries NO owned model file. Asserting `kicad.model is not None` here was asserting the
    # opposite of the design - it would have failed a correct part and passed a broken one.
    assert record.passive is True
    assert kicad.model is None


def test_the_report_says_a_passive_landed_with_its_assets():
    """The owner's whole complaint is 'I want the FILES'. A report that cannot distinguish a
    record from a placeable part cannot answer that question."""
    pipe = _PassivePipeline({"81-GRM155R71C104KA88D": "GRM155R71C104KA88D"})
    report = bulk_import(["81-GRM155R71C104KA88D"], pipe, _PassiveOps(), index=_index({}))
    item = report.items[0]
    assert item.assets == "kicad-stock"


def test_a_non_passive_still_takes_the_file_less_path_and_says_so(tmp_path):
    ds = tmp_path / "d.pdf"
    ds.write_bytes(b"%PDF-")
    pipe = _Pipeline(fill={"TPD6E05U06RVZR": _complete(ds)})
    ops = _PassiveOps()
    report = bulk_import(["TPD6E05U06RVZR"], pipe, ops, index=_index({}))
    assert report.items[0].status == "added"
    assert report.items[0].assets == "none"
    assert ops.passives == [] and len(ops.plain) == 1


def test_a_passive_whose_package_cannot_be_resolved_is_not_forced():
    """An undecodable passive must fall through to the honest file-less add, never guess a
    package. A wrong footprint is worse than no footprint."""
    pipe = _PassivePipeline({"81-MYSTERYCAP": "MYSTERYCAP99"})
    ops = _PassiveOps()
    report = bulk_import(["81-MYSTERYCAP"], pipe, ops, index=_index({}))
    assert ops.passives == []
    assert report.items[0].assets in ("none", "")
