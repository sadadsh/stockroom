"""The baked-snapshot seed path: a committed xz compression of the derived index that a
fresh machine decompresses instead of building from a CubeMX source tree (owner decision
2026-07-23, amending the never-commit invariant: the COMPRESSED seed is committed, the raw
sqlite stays per-machine and gitignored). The rev-stamp load gate stays authoritative: a
stale seed decompresses but is then refused by StmIndex.load exactly like any stale file."""

from __future__ import annotations

import lzma
import os
from pathlib import Path

from stockroom.stm import db as db_mod
from stockroom.stm import seed as seed_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def _make_seed(tmp_path: Path) -> Path:
    """A real seed artifact: a fixture-built index file, xz-compressed."""
    raw = tmp_path / "built.sqlite"
    idx = db_mod.StmIndex.build(FIXTURES, db_path=raw)
    idx.close()
    seed = tmp_path / "index.sqlite.xz"
    seed.write_bytes(lzma.compress(raw.read_bytes(), preset=1))
    return seed


def test_restore_decompresses_the_seed_and_the_load_gate_accepts_it(tmp_path, monkeypatch):
    seed = _make_seed(tmp_path)
    monkeypatch.setenv("STOCKROOM_STM_SEED", str(seed))
    target = tmp_path / "cfg" / "index.sqlite"

    assert seed_mod.restore_baked_index(target) is True
    idx = db_mod.StmIndex.load(target)
    assert idx is not None
    assert int(idx.meta()["device_xml_count"]) > 0
    idx.close()


def test_restore_returns_false_when_no_seed_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKROOM_STM_SEED", str(tmp_path / "absent.sqlite.xz"))
    target = tmp_path / "index.sqlite"
    assert seed_mod.restore_baked_index(target) is False
    assert not target.exists()


def test_restore_survives_a_corrupt_seed_without_touching_the_target(tmp_path, monkeypatch):
    seed = tmp_path / "index.sqlite.xz"
    seed.write_bytes(b"not an xz stream at all")
    monkeypatch.setenv("STOCKROOM_STM_SEED", str(seed))
    target = tmp_path / "index.sqlite"
    target.write_bytes(b"pre-existing bytes stay put")

    assert seed_mod.restore_baked_index(target) is False
    assert target.read_bytes() == b"pre-existing bytes stay put"
    # no half-written temp litter next to the target
    assert [p.name for p in target.parent.glob("*.tmp*")] == []


def test_restore_is_atomic_no_partial_target_on_success(tmp_path, monkeypatch):
    seed = _make_seed(tmp_path)
    monkeypatch.setenv("STOCKROOM_STM_SEED", str(seed))
    target = tmp_path / "index.sqlite"
    assert seed_mod.restore_baked_index(target) is True
    assert [p.name for p in target.parent.glob("*.tmp*")] == []


def test_default_seed_path_points_at_the_committed_repo_artifact(monkeypatch):
    monkeypatch.delenv("STOCKROOM_STM_SEED", raising=False)
    p = seed_mod.default_seed_path()
    # repo-root data/stm/index.sqlite.xz, resolved from the package location
    assert p.as_posix().endswith("data/stm/index.sqlite.xz")
    assert (p.parent.parent.parent / "app" / "backend" / "stockroom").is_dir()


def test_stale_seed_is_refused_by_the_load_gate_not_silently_trusted(tmp_path, monkeypatch):
    seed = _make_seed(tmp_path)
    # stamp-tamper the seed's contents: rewrite classifier_rev so the gate must refuse it
    raw = tmp_path / "tamper.sqlite"
    raw.write_bytes(lzma.decompress(seed.read_bytes()))
    import sqlite3

    conn = sqlite3.connect(raw)
    conn.execute("UPDATE meta SET value='999' WHERE key='classifier_rev'")
    conn.commit()
    conn.close()
    seed.write_bytes(lzma.compress(raw.read_bytes(), preset=1))
    monkeypatch.setenv("STOCKROOM_STM_SEED", str(seed))

    target = tmp_path / "index.sqlite"
    assert seed_mod.restore_baked_index(target) is True  # restore itself succeeds
    assert db_mod.StmIndex.load(target) is None  # the gate refuses the stale content
