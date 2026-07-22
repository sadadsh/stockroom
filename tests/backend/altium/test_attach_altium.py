from pathlib import Path

import pytest

from stockroom.model.part import PartRecord

FIX = Path(__file__).parent / "fixtures"


def _seed(ops, pid, mpn):
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / f"{pid}.json").write_text(
        PartRecord(id=pid, display_name=pid, category="Diodes", mpn=mpn).dumps(), encoding="utf-8"
    )


def test_attach_from_loose_pair(library_ops):
    ops = library_ops
    _seed(ops, "r", "S1M")

    record = ops.attach_altium_assets("r", FIX / "sample.SchLib", FIX / "sample.PcbLib")

    altium_dir = ops.lib.parts_dir.parent / "altium"
    assert (altium_dir / "r.SchLib").exists() and (altium_dir / "r.PcbLib").exists()
    assert record.altium_symbol.lib == "r.SchLib" and record.altium_symbol.name == "S1M"
    assert record.altium_footprint.lib == "r.PcbLib"
    assert record.altium_footprint.name == "DIOM5227X270N"
    assert ops.load_record("r").altium_symbol == record.altium_symbol  # persisted


def test_attach_from_intlib_autoextracts(library_ops):
    ops = library_ops
    _seed(ops, "d", "S1M")

    record = ops.attach_altium_assets("d", FIX / "sample.IntLib")

    altium_dir = ops.lib.parts_dir.parent / "altium"
    assert (altium_dir / "d.SchLib").exists() and (altium_dir / "d.PcbLib").exists()
    assert record.altium_symbol.name == "S1M"
    assert record.altium_footprint.name == "DIOM5227X270N"
    # only loose files are stored; the .IntLib itself is not committed into the library
    assert not (altium_dir / "d.IntLib").exists()


def test_attach_rejects_symbol_only_intlib_zero_trace(library_ops):
    ops = library_ops
    _seed(ops, "x", "B6B")

    with pytest.raises(ValueError, match="Extract"):
        ops.attach_altium_assets("x", FIX / "symbol_only.IntLib")

    # zero trace: no altium dir/files created, record left untouched
    assert not (ops.lib.parts_dir.parent / "altium").exists()
    assert ops.load_record("x").altium_symbol is None


def test_attach_rejects_ambiguous_multi_symbol_lib_zero_trace(library_ops):
    # multi_symbol.SchLib holds two symbols; with an MPN matching neither, binding is ambiguous
    ops = library_ops
    _seed(ops, "amb", "NOMATCH")

    with pytest.raises(ValueError, match="entries"):
        ops.attach_altium_assets("amb", FIX / "multi_symbol.SchLib", FIX / "sample.PcbLib")

    assert not (ops.lib.parts_dir.parent / "altium").exists()
    assert ops.load_record("amb").altium_symbol is None


def test_attach_picks_the_mpn_matching_symbol_from_a_multi_symbol_lib(library_ops):
    ops = library_ops
    _seed(ops, "hir", "HIROSE_BM28_40_RECEPTACLE")

    record = ops.attach_altium_assets("hir", FIX / "multi_symbol.SchLib", FIX / "sample.PcbLib")

    assert record.altium_symbol.name == "HIROSE_BM28_40_RECEPTACLE"  # not the alphabetical first


def test_attach_rolls_back_first_file_if_second_copy_fails(library_ops, monkeypatch):
    import shutil

    ops = library_ops
    _seed(ops, "leak", "S1M")
    real = shutil.copyfile
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # fail the second copy (the .PcbLib), after the .SchLib landed
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(shutil, "copyfile", flaky)
    with pytest.raises(OSError):
        ops.attach_altium_assets("leak", FIX / "sample.SchLib", FIX / "sample.PcbLib")

    # the first-copied .SchLib must NOT leak, and the record stays untouched (zero trace)
    assert not (ops.lib.parts_dir.parent / "altium" / "leak.SchLib").exists()
    assert ops.load_record("leak").altium_symbol is None
