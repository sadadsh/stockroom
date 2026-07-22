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
