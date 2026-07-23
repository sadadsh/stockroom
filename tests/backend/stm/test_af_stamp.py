"""Phase 2 Plan 02 Task 1: the af_schema_rev stamp round-trip + stale-index
load-refusal, through the SAME StmIndex.load stamp-gate function that already
checks classifier_rev/geometry_rev (DATA-08 extended, not a parallel gate)."""

from __future__ import annotations

from pathlib import Path

from stockroom.stm import db as db_mod

AF_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm" / "af_join"


def test_af_schema_rev_stamped_into_meta_on_build(tmp_path):
    db_path = tmp_path / "index.sqlite"
    idx = db_mod.StmIndex.build(AF_FIXTURES / "happy", db_path=db_path)
    try:
        assert idx.meta()["af_schema_rev"] == str(db_mod.AF_SCHEMA_REV)
    finally:
        idx.close()


def test_load_round_trips_a_matching_af_schema_rev(tmp_path):
    db_path = tmp_path / "index.sqlite"
    db_mod.StmIndex.build(AF_FIXTURES / "happy", db_path=db_path).close()

    loaded = db_mod.StmIndex.load(db_path)
    assert loaded is not None
    assert loaded.meta()["af_schema_rev"] == str(db_mod.AF_SCHEMA_REV)
    loaded.close()


def test_load_returns_none_on_af_schema_rev_mismatch(tmp_path, monkeypatch):
    db_path = tmp_path / "index.sqlite"
    db_mod.StmIndex.build(AF_FIXTURES / "happy", db_path=db_path).close()

    monkeypatch.setattr(db_mod, "AF_SCHEMA_REV", db_mod.AF_SCHEMA_REV + 1)
    assert db_mod.StmIndex.load(db_path) is None


def test_stale_af_schema_rev_refused_through_the_same_shared_gate(tmp_path):
    """Mutating the STORED af_schema_rev value directly (rather than the
    module constant) proves this goes through the SAME stamp-gate function
    that already refuses a classifier_rev/geometry_rev mismatch, not a
    second, parallel mechanism."""
    db_path = tmp_path / "index.sqlite"
    db_mod.StmIndex.build(AF_FIXTURES / "happy", db_path=db_path).close()

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE meta SET value = '999999' WHERE key = 'af_schema_rev'"
    )
    conn.commit()
    conn.close()

    assert db_mod.StmIndex.load(db_path) is None
