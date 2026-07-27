"""The v3 index: per-tool assets, every purchase row, incremental sync, trust as facts.

The shape this replaces could not express "has an Altium footprint" at all - one `footprint_name`
column, read off KiCad and named as such - and rebuilt itself from scratch after every library
write. Both are measured here rather than asserted.
"""
from __future__ import annotations

import json
from pathlib import Path

from stockroom.model.asset import Asset, AssetOrigin, AssetRef, EdaAssets
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass
from stockroom.model.trust import AssetCheck, Verdict
from stockroom.store.index import LibraryIndex


def _rec(part_id: str, mpn: str, **kw) -> PartRecord:
    return PartRecord(
        id=part_id, mpn=mpn, manufacturer="Acme", part_class=PartClass.COMPONENT,
        display_name=mpn, category="ICs", description=f"{mpn} part", **kw,
    )


def _write(parts: Path, rec: PartRecord) -> Path:
    path = parts / f"{rec.id}.json"
    path.write_text(rec.dumps(), encoding="utf-8")
    return path


def _lib(tmp_path: Path, records: list[PartRecord]) -> Path:
    parts = tmp_path / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    for r in records:
        _write(parts, r)
    return parts


# --------------------------------------------------------------- incremental sync

def test_a_sync_with_nothing_changed_parses_NOTHING(tmp_path):
    """The whole point. `rebuild_index` runs after every library write, and each one used to
    re-parse the entire library to reflect one edited part."""
    parts = _lib(tmp_path, [_rec(f"p{i}-aaaa", f"MPN-{i}") for i in range(5)])
    idx = LibraryIndex.build(parts)
    stats = idx.sync(parts)
    assert stats.parsed == 0, f"a no-op sync parsed {stats.parsed} records"
    assert stats.unchanged == 5
    idx.close()


def test_editing_ONE_record_parses_exactly_one(tmp_path):
    parts = _lib(tmp_path, [_rec(f"p{i}-aaaa", f"MPN-{i}") for i in range(5)])
    idx = LibraryIndex.build(parts)

    rec = _rec("p2-aaaa", "MPN-2")
    rec.description = "edited description"
    _write(parts, rec)

    stats = idx.sync(parts)
    assert stats.parsed == 1, f"expected 1 parse, got {stats}"
    assert stats.updated == 1 and stats.added == 0 and stats.removed == 0
    assert stats.unchanged == 4
    assert idx.get("p2-aaaa") is not None
    idx.close()


def test_a_new_record_is_ADDED_and_a_deleted_one_is_REMOVED(tmp_path):
    """The full rebuild got removal for free by dropping everything; an incremental path has to do
    it on purpose, or a part deleted on a peer stays in the index forever."""
    parts = _lib(tmp_path, [_rec("a-aaaa", "A"), _rec("b-aaaa", "B")])
    idx = LibraryIndex.build(parts)
    assert idx.count() == 2

    _write(parts, _rec("c-aaaa", "C"))
    (parts / "a-aaaa.json").unlink()
    stats = idx.sync(parts)

    assert stats.added == 1 and stats.removed == 1
    assert idx.count() == 2
    assert idx.get("a-aaaa") is None, "a deleted record survived the sync"
    assert idx.get("c-aaaa") is not None
    idx.close()


def test_a_removed_part_takes_its_CHILD_rows_with_it(tmp_path):
    """Orphaned child rows would make `vendors()` and `parts_missing_asset` count a part that is
    gone - a leak the old DROP TABLE could not have."""
    rec = _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=AssetRef(lib="L", name="S"))})
    parts = _lib(tmp_path, [rec])
    idx = LibraryIndex.build(parts)
    assert idx.assets_for_tool("kicad")

    (parts / "a-aaaa.json").unlink()
    idx.sync(parts)
    assert idx.assets_for_tool("kicad") == {}, "child asset rows outlived their part"
    idx.close()


def test_a_touched_but_UNCHANGED_file_is_not_reparsed(tmp_path):
    """Content, not mtime. `touch` is not a change, and this repo has shipped a bug from treating
    an mtime as one."""
    parts = _lib(tmp_path, [_rec("a-aaaa", "A")])
    idx = LibraryIndex.build(parts)
    path = parts / "a-aaaa.json"
    path.touch()  # mtime moves, bytes do not
    stats = idx.sync(parts)
    assert stats.parsed == 0, "a touch was mistaken for a content change"
    idx.close()


def test_an_edit_that_keeps_the_SAME_LENGTH_is_still_detected(tmp_path):
    """A size-only or mtime-only check would miss this; hashing the content cannot."""
    parts = _lib(tmp_path, [_rec("a-aaaa", "AAAA")])
    idx = LibraryIndex.build(parts)
    path = parts / "a-aaaa.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    before = len(path.read_text(encoding="utf-8"))
    raw["derived"]["description"] = "x" * len(raw["derived"]["description"])
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

    stats = idx.sync(parts)
    assert stats.parsed == 1, f"a same-ish-length content edit was missed (len {before})"
    idx.close()


# ------------------------------------------------------- per-tool assets (the old blind spot)

def test_the_index_can_answer_which_parts_have_an_ALTIUM_footprint(tmp_path):
    """Physically impossible before: there was one `footprint_name` column, read off KiCad."""
    both = _rec("both-aaaa", "BOTH", assets={
        "kicad": EdaAssets(symbol=AssetRef(lib="SR", name="S"),
                           footprint=AssetRef(lib="SR", name="F")),
        "altium": EdaAssets(symbol=AssetRef(lib="a.SchLib", name="S"),
                            footprint=AssetRef(lib="a.PcbLib", name="F")),
    })
    kicad_only = _rec("kic-aaaa", "KIC", assets={
        "kicad": EdaAssets(symbol=AssetRef(lib="SR", name="S"),
                           footprint=AssetRef(lib="SR", name="F")),
    })
    idx = LibraryIndex.build(_lib(tmp_path, [both, kicad_only]))

    altium = idx.assets_for_tool("altium")
    assert altium.get("both-aaaa", {}).get("footprint") is True
    assert "kic-aaaa" not in altium, "a part with no Altium bundle should have no Altium rows"

    missing = idx.parts_missing_asset("altium", "footprint")
    assert missing == ["kic-aaaa"], f"expected only the KiCad-only part, got {missing}"
    assert idx.parts_missing_asset("kicad", "footprint") == []
    idx.close()


def test_a_part_with_NO_row_for_a_tool_counts_as_missing_it(tmp_path):
    """The LEFT JOIN. An inner join would silently exclude every part never touched for that tool -
    the majority, and precisely the ones the question is about."""
    idx = LibraryIndex.build(_lib(tmp_path, [_rec("bare-aaaa", "BARE")]))
    assert idx.parts_missing_asset("altium", "symbol") == ["bare-aaaa"]
    idx.close()


def test_a_detached_asset_disappears_from_the_index(tmp_path):
    """Child rows are replaced wholesale on upsert. Merging would leave a detached asset in the
    index forever, still reading as present."""
    rec = _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=AssetRef(lib="L", name="S"))})
    parts = _lib(tmp_path, [rec])
    idx = LibraryIndex.build(parts)
    assert idx.assets_for_tool("kicad")["a-aaaa"]["symbol"] is True

    _write(parts, _rec("a-aaaa", "A"))  # same id, no assets at all
    idx.sync(parts)
    assert idx.assets_for_tool("kicad").get("a-aaaa", {}) == {}
    idx.close()


# ----------------------------------------------------------- every purchase row

def test_EVERY_purchase_row_is_indexed_not_just_the_first(tmp_path):
    from stockroom.model.part import Purchase

    rec = _rec("a-aaaa", "A")
    rec.purchase.extend([
        Purchase(vendor="mouser", url="https://m/x", part_number="595-A", stock=10, currency="USD"),
        Purchase(vendor="digikey", url="https://d/x", part_number="296-A", stock=5, currency="USD"),
    ])
    idx = LibraryIndex.build(_lib(tmp_path, [rec]))

    rows = idx.purchase_rows("a-aaaa")
    assert [r["vendor"] for r in rows] == ["mouser", "digikey"], "record order is priority order"
    assert rows[1]["part_number"] == "296-A"
    assert idx.vendors() == {"mouser": 1, "digikey": 1}
    idx.close()


# ------------------------------------------------- trust: facts stored, verdict derived

def test_the_check_FACTS_are_stored_and_the_verdict_is_DERIVED(tmp_path):
    """No verdict is ever written to the database. Tightening a check must re-judge the library with
    no re-audit, which a stored verdict makes impossible."""
    asset = Asset(
        ref=AssetRef(lib="SR", name="S"),
        checks=[AssetCheck(check="pins_vs_datasheet", measured=8, expected=8, against="ds rev C")],
    )
    idx = LibraryIndex.build(_lib(tmp_path, [
        _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=asset)}),
    ]))
    assert idx.asset_trust("a-aaaa", "kicad", "symbol") is Verdict.PASS

    # No column anywhere holds a verdict string.
    cols = [r[1] for r in idx._conn.execute("PRAGMA table_info(part_assets)")]
    assert "verdict" not in cols and "trust" not in cols, f"a verdict is stored: {cols}"
    idx.close()


def test_an_asset_with_NO_checks_is_UNKNOWN_never_a_pass(tmp_path):
    """UNKNOWN is mandatory: an asset nobody measured must not claim either outcome."""
    idx = LibraryIndex.build(_lib(tmp_path, [
        _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=AssetRef(lib="L", name="S"))}),
    ]))
    assert idx.asset_trust("a-aaaa", "kicad", "symbol") is Verdict.UNKNOWN
    idx.close()


def test_a_failing_measurement_derives_FAIL_from_the_stored_facts(tmp_path):
    """The negative control for the PASS case: without it, both tests would pass on a function that
    always returned the same verdict."""
    asset = Asset(
        ref=AssetRef(lib="SR", name="S"),
        checks=[AssetCheck(check="pins_vs_datasheet", measured=7, expected=8, against="ds rev C")],
    )
    idx = LibraryIndex.build(_lib(tmp_path, [
        _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=asset)}),
    ]))
    assert idx.asset_trust("a-aaaa", "kicad", "symbol") is Verdict.FAIL
    idx.close()


def test_asset_provenance_is_queryable_including_the_UNATTRIBUTED_ones(tmp_path):
    """The owner's complaint verbatim: 'its not trusted where we've gotten them'. An asset with no
    recorded origin must surface AS unattributed, not vanish from the count."""
    attributed = Asset(ref=AssetRef(lib="SR", name="S"),
                       origin=AssetOrigin(vendor="ultralibrarian", url="https://u/x"))
    idx = LibraryIndex.build(_lib(tmp_path, [
        _rec("a-aaaa", "A", assets={"kicad": EdaAssets(symbol=attributed)}),
        _rec("b-aaaa", "B", assets={"kicad": EdaAssets(symbol=AssetRef(lib="L", name="S"))}),
    ]))
    by_origin = idx.assets_by_origin()
    assert by_origin.get("ultralibrarian") == 1
    assert by_origin.get("(unrecorded)") == 1, f"unattributed assets went missing: {by_origin}"
    idx.close()


# ----------------------------------------------------------------- no regressions

def test_the_existing_read_api_is_unchanged(tmp_path):
    """Search, facets, duplicates and the completion rollup all read this index, so the public
    behaviour must be identical - the schema changed underneath, not the contract."""
    idx = LibraryIndex.build(_lib(tmp_path, [
        _rec("a-aaaa", "AAA"), _rec("b-aaaa", "BBB"),
    ]))
    assert idx.count() == 2
    assert [r.mpn for r in idx.search("AAA")] == ["AAA"]
    assert idx.facets().by_category == {"ICs": 2}
    assert [r.mpn for r in idx.find_by_mpn("aaa")] == ["AAA"]
    assert idx.get("a-aaaa").display_name == "AAA"
    idx.close()


def test_the_schema_creates_no_DROP_and_survives_being_applied_twice(tmp_path):
    """`sync` relies on the tables persisting. A DROP anywhere in the schema would silently make
    every sync a full rebuild again."""
    from stockroom.store.index import _SCHEMA

    assert "DROP TABLE" not in _SCHEMA.upper()
    parts = _lib(tmp_path, [_rec("a-aaaa", "A")])
    idx = LibraryIndex.build(parts)
    idx._conn.executescript(_SCHEMA)  # idempotent: must not raise or wipe
    assert idx.count() == 1
    idx.close()
