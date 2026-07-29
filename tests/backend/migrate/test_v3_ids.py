"""The v2 -> v3 library migration: what it moves, what it refuses, and that it never loses a part.

This renames every record in someone's real library, so the interesting tests are the REFUSALS.
A migration that half-succeeds is worse than one that declines to start.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.migrate.v3_ids import (
    apply_migration,
    count_orphan_bindings,
    plan_migration,
)
from stockroom.model.part import SCHEMA_VERSION, PartRecord
from stockroom.model.part_id import is_valid_part_id, make_part_id


def _v2_record(part_id: str, mpn: str, *, datasheet: str | None = None, **extra) -> dict:
    """A record in the shape the owner's library really holds: schema 2, `eda`, `passive`."""
    out = {
        "schema_version": 2,
        "id": part_id,
        "mpn": mpn,
        "manufacturer": "Acme",
        "display_name": f"{mpn} thing",
        "category": "Other",
        "description": "a part",
        "specs": {"Resistance": "1 kOhms"},
        "tags": [],
        "eda": {"kicad": {"symbol": {"lib": "SR-Other", "name": mpn, "file": ""},
                          "footprint": None, "model": None}},
        "passive": False,
        "purchase": [],
        "enrichment": {},
    }
    if datasheet is not None:
        out["datasheet"] = {"file": datasheet, "source_url": "", "fetched_at": ""}
    out.update(extra)
    return out


def _library(tmp_path: Path, records: list[dict], *, datasheets: list[str] = ()) -> Path:
    root = tmp_path / "Lib"
    (root / "parts").mkdir(parents=True)
    (root / "datasheets").mkdir(parents=True)
    for raw in records:
        (root / "parts" / f"{raw['id']}.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
    for name in datasheets:
        (root / "datasheets" / name).write_bytes(b"%PDF-1.4 fake")
    return root


# --------------------------------------------------------------------------- the plan

def test_it_plans_a_new_id_and_a_schema_upgrade_for_every_v2_record(tmp_path):
    root = _library(tmp_path, [
        _v2_record("103at_2", "103AT-2"),
        _v2_record("10_era_2aeb1182x", "10-ERA-2AEB1182X"),
    ])
    plan = plan_migration(root)
    assert plan.ok, plan.errors
    assert len(plan.parts) == 2
    for item in plan.parts:
        assert item.renames_id
        assert item.old_schema == 2
        assert is_valid_part_id(item.new_id), f"{item.new_id} is not path-safe"
        assert "_" not in item.new_id, "an underscore is exactly what sourced/ refuses"
        assert item.new_id == make_part_id(item.mpn)


def test_the_underscore_ids_are_what_sourced_refuses_before_the_migration(tmp_path):
    """The whole reason this migration exists, stated as a test rather than as a claim: the OLD
    ids are genuinely unusable as evidence paths, and the NEW ones are usable."""
    root = _library(tmp_path, [_v2_record("103at_2", "103AT-2")])
    plan = plan_migration(root)
    assert not is_valid_part_id("103at_2")
    assert is_valid_part_id(plan.parts[0].new_id)


def test_a_datasheet_named_after_the_part_id_moves_with_it(tmp_path):
    root = _library(
        tmp_path, [_v2_record("103at_2", "103AT-2", datasheet="103at_2.pdf")],
        datasheets=["103at_2.pdf"],
    )
    plan = plan_migration(root)
    item = plan.parts[0]
    assert item.datasheet_from is not None
    assert item.datasheet_to is not None
    assert item.datasheet_to.name == f"{item.new_id}.pdf"


def test_a_datasheet_NOT_named_after_the_id_is_left_alone_and_noted(tmp_path):
    """It stays valid either way, so moving it would be churn - but silently doing nothing is how
    a reader concludes nothing needed doing."""
    root = _library(
        tmp_path, [_v2_record("103at_2", "103AT-2", datasheet="ti-datasheet.pdf")],
        datasheets=["ti-datasheet.pdf"],
    )
    plan = plan_migration(root)
    assert plan.parts[0].datasheet_from is None
    assert any("not named after the part id" in n for n in plan.notes)


def test_a_referenced_but_MISSING_datasheet_is_noted_not_invented(tmp_path):
    root = _library(tmp_path, [_v2_record("x_1", "X-1", datasheet="x_1.pdf")])  # file absent
    plan = plan_migration(root)
    assert plan.ok
    assert plan.parts[0].datasheet_from is None
    assert any("missing on disk" in n for n in plan.notes)


# ------------------------------------------------------------------------ the refusals

def test_two_records_with_the_SAME_mpn_are_a_refused_collision(tmp_path):
    """The 4-hex suffix makes this near-impossible except for a genuine duplicate - and merging
    two records by overwriting one file with the other would DESTROY one."""
    root = _library(tmp_path, [
        _v2_record("dupe_a", "SAME-MPN"),
        _v2_record("dupe_b", "SAME-MPN"),
    ])
    plan = plan_migration(root)
    assert not plan.ok
    assert any("COLLISION" in e for e in plan.errors)
    assert any("DESTROY" in e for e in plan.errors)


def test_a_filename_disagreeing_with_the_records_id_is_refused(tmp_path):
    """Picking one of the two as truth is a decision a migration must not make silently."""
    root = _library(tmp_path, [_v2_record("real_id", "REAL-1")])
    (root / "parts" / "real_id.json").rename(root / "parts" / "different_name.json")
    plan = plan_migration(root)
    assert not plan.ok
    assert any("disagrees with the record's id" in e for e in plan.errors)


def test_a_record_with_no_mpn_is_refused_because_the_id_is_derived_from_it(tmp_path):
    root = _library(tmp_path, [_v2_record("nompn", "")])
    plan = plan_migration(root)
    assert not plan.ok
    assert any("no MPN" in e for e in plan.errors)


def test_an_unreadable_record_is_reported_not_skipped_silently(tmp_path):
    root = _library(tmp_path, [_v2_record("good_1", "GOOD-1")])
    (root / "parts" / "broken.json").write_text("{not json", encoding="utf-8")
    plan = plan_migration(root)
    assert not plan.ok
    assert any("unreadable" in e for e in plan.errors)


def test_applying_a_plan_with_errors_RAISES_rather_than_half_migrating(tmp_path):
    root = _library(tmp_path, [_v2_record("d_a", "SAME"), _v2_record("d_b", "SAME")])
    plan = plan_migration(root)
    with pytest.raises(ValueError, match="blocking errors"):
        apply_migration(plan, root)


# --------------------------------------------------------------------------- applying

def test_apply_renames_the_record_upgrades_it_and_loses_nothing(tmp_path):
    root = _library(
        tmp_path, [_v2_record("103at_2", "103AT-2", datasheet="103at_2.pdf")],
        datasheets=["103at_2.pdf"],
    )
    plan = plan_migration(root)
    new_id = plan.parts[0].new_id
    apply_migration(plan, root)

    # The old path is gone and the new one is there - exactly one record, never two.
    assert not (root / "parts" / "103at_2.json").exists()
    assert (root / "parts" / f"{new_id}.json").is_file()
    assert len(list((root / "parts").glob("*.json"))) == 1

    written = json.loads((root / "parts" / f"{new_id}.json").read_text(encoding="utf-8"))
    assert written["id"] == new_id
    assert written["schema_version"] == SCHEMA_VERSION
    assert "eda" not in written and "passive" not in written, "v2 keys survived the upgrade"
    assert "derived" in written and "part_class" in written

    # The DATA survived the rename: identity, the derived block, and the asset reference.
    rec = PartRecord.from_dict(written)
    assert rec.mpn == "103AT-2"
    assert rec.manufacturer == "Acme"
    assert rec.specs.get("Resistance")
    assert rec.assets_for("kicad").symbol is not None

    # The datasheet moved AND the reference was updated to match - both, or the link dangles.
    assert (root / "datasheets" / f"{new_id}.pdf").is_file()
    assert not (root / "datasheets" / "103at_2.pdf").exists()
    assert rec.datasheet is not None and rec.datasheet.file == f"{new_id}.pdf"


def test_a_crash_MIDWAY_leaves_both_copies_never_neither(tmp_path, monkeypatch):
    """The documented ordering guarantee, which the happy path cannot observe.

    `apply_migration` writes every record to its NEW path first and only then removes the old
    ones, so a failure in between leaves BOTH copies - visible in `git status`, resolvable by a
    person. Removing first would lose the record entirely if the write then failed.

    Added after a mutation SURVIVED: reordering the unlink to before the write passed all 15 tests,
    because the outcome is identical unless something fails in between - and nothing simulated a
    failure. This does.
    """
    root = _library(tmp_path, [_v2_record("103at_2", "103AT-2")])
    plan = plan_migration(root)
    new_id = plan.parts[0].new_id

    real_write = Path.write_text

    def explode(self, *a, **k):
        if self.name == f"{new_id}.json":
            raise OSError("disk full, midway through the migration")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", explode)
    with pytest.raises(OSError, match="disk full"):
        apply_migration(plan, root)
    monkeypatch.undo()

    # The ORIGINAL record must still be on disk: a crashed migration may leave duplication, but it
    # must never leave a hole where a part used to be.
    assert (root / "parts" / "103at_2.json").is_file(), (
        "the original record was removed before its replacement was safely written - a crash "
        "here would have destroyed the part"
    )
    surviving = json.loads((root / "parts" / "103at_2.json").read_text(encoding="utf-8"))
    assert surviving["mpn"] == "103AT-2"


def test_apply_is_idempotent_a_second_run_is_a_no_op(tmp_path):
    """Once migrated, the ids are already correct, so re-running must not churn or duplicate."""
    root = _library(tmp_path, [_v2_record("103at_2", "103AT-2")])
    apply_migration(plan_migration(root), root)
    after_first = {p.name: p.read_text(encoding="utf-8") for p in (root / "parts").glob("*.json")}

    second = plan_migration(root)
    assert second.ok
    assert all(not p.renames_id for p in second.parts), "a migrated library still wants renaming"
    apply_migration(second, root)
    after_second = {p.name: p.read_text(encoding="utf-8") for p in (root / "parts").glob("*.json")}
    assert after_first == after_second


def test_an_already_migrated_library_reports_ZERO_work_not_phantom_moves(tmp_path):
    """The summary is what a person reads before typing --apply, so it must not overstate.

    Before this, `moves_datasheet` was "has a datasheet named after the id" - which stays TRUE
    after a migration (the id and the filename still agree), so a fully-migrated library reported
    "85 datasheets move" when nothing would move at all. `apply_migration` skipped them correctly;
    only the report lied, which is the half that gets believed.
    """
    root = _library(
        tmp_path, [_v2_record("103at_2", "103AT-2", datasheet="103at_2.pdf")],
        datasheets=["103at_2.pdf"],
    )
    apply_migration(plan_migration(root), root)

    again = plan_migration(root)
    assert again.ok
    assert sum(1 for p in again.parts if p.moves_datasheet) == 0
    assert sum(1 for p in again.parts if p.renames_id) == 0
    assert "0 datasheets move" in again.summary()
    assert "0 blocking errors" in again.summary()


def test_every_record_survives_a_whole_library_migration(tmp_path):
    """The property that matters most: the part COUNT is preserved and every MPN is still present.
    A rename loop that overwrote its own targets would quietly reduce the count."""
    mpns = [f"PART-{i:03d}" for i in range(40)]
    root = _library(tmp_path, [_v2_record(f"part_{i:03d}", m) for i, m in enumerate(mpns)])
    plan = plan_migration(root)
    assert plan.ok
    apply_migration(plan, root)

    files = list((root / "parts").glob("*.json"))
    assert len(files) == len(mpns), f"expected {len(mpns)} records, found {len(files)}"
    found = {json.loads(f.read_text(encoding="utf-8"))["mpn"] for f in files}
    assert found == set(mpns)
    for f in files:
        raw = json.loads(f.read_text(encoding="utf-8"))
        assert f.stem == raw["id"], "filename and id must agree after a migration"
        assert is_valid_part_id(raw["id"])


def test_a_sourced_payload_directory_moves_with_the_part(tmp_path):
    """No payload exists in the owner's library today, but a library that HAS them must not be
    half-migrated - the record's `sources` index stores the path, so both must move together."""
    root = _library(tmp_path, [_v2_record("103at_2", "103AT-2")])
    payload_dir = root / "sourced" / "103at_2"
    payload_dir.mkdir(parents=True)
    (payload_dir / "mouser.json").write_text('{"SearchResults": {}}', encoding="utf-8")

    plan = plan_migration(root)
    new_id = plan.parts[0].new_id
    assert plan.parts[0].sourced_from is not None
    apply_migration(plan, root)

    assert (root / "sourced" / new_id / "mouser.json").is_file()
    assert not (root / "sourced" / "103at_2").exists()


# ------------------------------------------------------------------- orphan bindings

def test_orphan_bindings_are_counted_so_the_caller_can_refuse(tmp_path):
    root = _library(tmp_path, [_v2_record("x_1", "X-1")])
    assert count_orphan_bindings(root) == 0
    (root / "projects").mkdir()
    (root / "projects" / "board.json").write_text("{}", encoding="utf-8")
    assert count_orphan_bindings(root) == 1
