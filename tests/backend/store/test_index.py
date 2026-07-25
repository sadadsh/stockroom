from pathlib import Path

from stockroom.model.part import AssetRef, Datasheet, EdaAssets, PartRecord, Purchase
from stockroom.store.index import LibraryIndex


def _complete(pid, name, cat="ICs", mpn="M1", mfr="TI", fp="VQFN-16") -> PartRecord:
    return PartRecord(
        id=pid,
        display_name=name,
        category=cat,
        description="desc " + name,
        tags=["t"],
        mpn=mpn,
        manufacturer=mfr,
        datasheet=Datasheet(file=f"{pid}.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/" + pid)],
        eda={"kicad": EdaAssets(
            symbol=AssetRef(lib="SR-" + cat, name=name),
            footprint=AssetRef(lib="SR-" + cat, name=fp),
            model=AssetRef(file=f"models/{name}.step"),
        )},
    )


def _write(parts_dir: Path, rec: PartRecord) -> None:
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / f"{rec.id}.json").write_text(rec.dumps(), encoding="utf-8")


def test_build_and_count(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha"))
    _write(pd, _complete("b", "Beta"))
    assert LibraryIndex.build(pd).count() == 2


def test_build_missing_dir_is_empty(tmp_path):
    idx = LibraryIndex.build(tmp_path / "nope")
    assert idx.count() == 0
    assert idx.search() == []


def test_search_by_name_mpn_manufacturer(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", mpn="TPS62130", mfr="TI"))
    _write(pd, _complete("b", "Bravo", mpn="LM358", mfr="OnSemi"))
    idx = LibraryIndex.build(pd)
    assert [r.id for r in idx.search("alpha")] == ["a"]
    assert [r.id for r in idx.search("tps")] == ["a"]
    assert [r.id for r in idx.search("onsemi")] == ["b"]
    assert {r.id for r in idx.search()} == {"a", "b"}  # empty query returns all


def test_search_category_and_complete_only(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", cat="ICs"))
    inc = _complete("b", "Beta", cat="ICs")
    inc.datasheet = None  # missing a required passport field => incomplete (assets no longer gate)
    _write(pd, inc)
    _write(pd, _complete("c", "Gamma", cat="Passives"))
    idx = LibraryIndex.build(pd)
    assert {r.id for r in idx.search(category="ICs")} == {"a", "b"}
    assert {r.id for r in idx.search(complete_only=True)} == {"a", "c"}
    assert [r.id for r in idx.incomplete()] == ["b"]
    b = idx.get("b")
    assert b is not None and not b.is_complete and "datasheet" in b.missing


def test_facets(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", cat="ICs", mfr="TI"))
    _write(pd, _complete("b", "Beta", cat="ICs", mfr="TI"))
    inc = _complete("c", "Gamma", cat="Passives", mfr="Yageo")
    inc.datasheet = None  # incomplete
    _write(pd, inc)
    f = LibraryIndex.build(pd).facets()
    assert f.by_category == {"ICs": 2, "Passives": 1}
    assert f.by_manufacturer == {"TI": 2, "Yageo": 1}
    assert f.complete == 2
    assert f.incomplete == 1


def test_duplicates_by_mpn_and_footprint(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", mpn="DUP", fp="SOT23"))
    _write(pd, _complete("b", "Beta", mpn="DUP", fp="SOT23"))
    _write(pd, _complete("c", "Gamma", mpn="UNIQ", fp="0402"))
    idx = LibraryIndex.build(pd)
    assert idx.duplicates_by_mpn() == {"DUP": ["a", "b"]}
    assert idx.duplicates_by_footprint() == {"SOT23": ["a", "b"]}


def test_persists_to_a_real_db_file(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha"))
    db = tmp_path / "index.db"
    idx = LibraryIndex.build(pd, db_path=db)
    assert idx.count() == 1
    idx.close()
    assert db.exists()  # a rebuildable per-machine cache file, never committed


def test_find_by_mpn_is_punctuation_and_case_insensitive(tmp_path):
    # a BOM line rarely spells the MPN exactly as the record does; matching is
    # normalized (case + separators) but never substring-loose
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", mpn="TPS62130RGTR"))
    _write(pd, _complete("b", "Beta", mpn="LM358DR"))
    idx = LibraryIndex.build(pd)
    assert [r.id for r in idx.find_by_mpn("tps-62130-rgtr")] == ["a"]
    assert [r.id for r in idx.find_by_mpn("TPS62130RGTR")] == ["a"]
    assert idx.find_by_mpn("TPS62130") == []  # a prefix is NOT the same part
    assert idx.find_by_mpn("") == []
    assert idx.find_by_mpn("WIDGET99") == []


# -- thread safety -------------------------------------------------------------
#
# The index is a WARM, long-lived connection shared by the API. FastAPI runs sync route handlers in a
# threadpool, so several requests read this one connection at the same time (the Components detail
# view alone fires the symbol, footprint and model previews in parallel, and each resolves the part
# through `get`). A `sqlite3.Connection` is not safe for concurrent use: the sqlite3 module RELEASES
# the GIL around the C calls precisely so other threads can run, so two workers really are inside
# execute/fetch simultaneously. SQLite answers that with SQLITE_MISUSE, and a torn read hands back
# column values that were never in the database, which is how `missing` came back None from a column
# declared NOT NULL DEFAULT ''.
#
# This reproduced as two seemingly unrelated 500s in the live app for days:
#   sqlite3.InterfaceError: bad parameter or other API misuse   (the bind never even ran)
#   AttributeError: 'NoneType' object has no attribute 'split'  (in _to_row, on `missing`)
# Both are the same bug. This test hammers EVERY reader, not just `get`, because they all shared it.


def _index_with_parts(tmp_path):
    pd = tmp_path / "parts"
    _write(pd, _complete("a", "Alpha", mpn="TPS62130RGTR"))
    _write(pd, _complete("b", "Beta", cat="Resistors", mpn="RC0402", fp="R_0402"))
    _write(pd, _complete("c", "Gamma", cat="Resistors", mpn="RC0402", fp="R_0402"))
    return LibraryIndex.build(pd)


def test_every_reader_is_safe_under_concurrent_access(tmp_path):
    import threading

    idx = _index_with_parts(tmp_path)
    errors: list[str] = []
    bad_rows: list[str] = []

    def reader():
        for _ in range(150):
            try:
                row = idx.get("a")
                # A torn read yields values that were never stored. `missing` is NOT NULL, so a None
                # here means the row did not come from the table.
                if row is not None and row.missing is None:
                    bad_rows.append("missing is None")
                if idx.count() != 3:
                    bad_rows.append("count is wrong")
                idx.search("alpha")
                idx.facets()
                idx.find_by_mpn("tps-62130-rgtr")
                idx.incomplete()
                idx.duplicates_by_mpn()
                idx.duplicates_by_footprint()
            except BaseException as exc:  # noqa: BLE001 - the point is that NOTHING may escape
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"{len(errors)} concurrent read failures, first few: {errors[:3]}"
    assert bad_rows == [], f"{len(bad_rows)} torn reads, first few: {bad_rows[:3]}"
