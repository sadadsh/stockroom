import sqlite3

from stockroom.model.part import AltiumRef, PartRecord


def _db_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("Parts")')]
        return [dict(zip(cols, row)) for row in conn.execute('SELECT * FROM "Parts"')]
    finally:
        conn.close()


def _place_ready(pid, mpn):
    return PartRecord(
        id=pid, display_name=pid, category="ICs", mpn=mpn, manufacturer="TI",
        description="d", value=mpn,
        altium_symbol=AltiumRef(lib=f"{pid}.SchLib", name=mpn),
        altium_footprint=AltiumRef(lib=f"{pid}.PcbLib", name="FP"),
    )


def test_regenerate_emits_only_place_ready(library_ops):
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    # not place-ready: no altium refs
    (ops.lib.parts_dir / "b.json").write_text(
        PartRecord(id="b", display_name="b", category="ICs", mpn="BBB").dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1
    assert "b" in result["skipped"]
    assert result["dblib"].exists()
    assert result["db"].exists()
    rows = _db_rows(result["db"])
    assert [r["MPN"] for r in rows] == ["AAA"]

    # The .db data source is COMMITTED with the .DbLib (owner decision 2026-07-23): a fresh
    # clone is placeable with no regenerate step. No local .gitignore hides it.
    ops = library_ops
    tracked = ops.repo._run("ls-files", "--", str(result["db"].parent)).stdout.splitlines()
    names = {p.rsplit("/", 1)[-1] for p in tracked}
    assert "stockroom-parts.db" in names
    assert "Stockroom.DbLib" in names
    assert ".gitignore" not in names


def test_place_ready_does_not_require_a_persisted_value(library_ops):
    """The place-ready gate must NOT require record.value (nothing in the real pipeline sets it);
    the Value column is derived at emit time. A part with value="" but full identity + assets is
    emitted, with Value derived (an active's MPN)."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    rec = PartRecord(
        id="c", display_name="c", category="ICs", mpn="CCC", manufacturer="TI",
        description="a chip", value="",  # NOT populated by the real pipeline
        altium_symbol=AltiumRef(lib="c.SchLib", name="CCC"),
        altium_footprint=AltiumRef(lib="c.PcbLib", name="FP"),
    )
    (ops.lib.parts_dir / "c.json").write_text(rec.dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1  # emitted despite value==""
    row = _db_rows(result["db"])[0]
    assert row["Value"] == "CCC"  # derived (active -> MPN), not blank


def test_regenerate_is_idempotent(library_ops):
    """Regenerate runs on every data refresh; an unchanged .DbLib must not crash on an
    empty commit or spawn a noisy empty commit (GitRepo.commit no-ops on an empty diff)."""
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")

    first = ops.regenerate_altium_dblib()
    head_after_first = ops.repo.head()
    second = ops.regenerate_altium_dblib()  # identical content

    assert second["emitted"] == 1
    assert ops.repo.head() == head_after_first  # no new (empty) commit
    assert second["dblib"].exists()
