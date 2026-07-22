from pathlib import Path

import pytest

from stockroom.altium.extract import extract_intlib, normalize_altium_source
from stockroom.altium.oleread import read_footprint_names, read_symbol_names

FIX = Path(__file__).parent / "fixtures"
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def test_extract_intlib_yields_valid_standalone_libs(tmp_path):
    sch, pcb = extract_intlib(FIX / "sample.IntLib", tmp_path)
    assert sch.read_bytes()[:8] == CFB_MAGIC
    assert pcb.read_bytes()[:8] == CFB_MAGIC
    # the extracted loose libs carry the real component names
    assert read_symbol_names(sch) == ["S1M"]
    assert read_footprint_names(pcb) == ["DIOM5227X270N"]


def test_extract_rejects_intlib_missing_a_footprint_lib(tmp_path):
    # symbol_only.IntLib (B6B) has a SchLib but no PcbLib stream -> fail loud, honest fallback
    with pytest.raises(ValueError, match="Extract"):
        extract_intlib(FIX / "symbol_only.IntLib", tmp_path)


def test_normalize_passes_through_a_loose_pair():
    sch, pcb = normalize_altium_source(FIX / "sample.SchLib", FIX / "sample.PcbLib")
    assert sch.name == "sample.SchLib" and pcb.name == "sample.PcbLib"


def test_normalize_extracts_an_intlib(tmp_path):
    sch, pcb = normalize_altium_source(FIX / "sample.IntLib", out_dir=tmp_path)
    assert read_symbol_names(sch) == ["S1M"]
    assert read_footprint_names(pcb) == ["DIOM5227X270N"]


def test_normalize_rejects_ambiguous_input():
    with pytest.raises(ValueError):
        normalize_altium_source(FIX / "sample.SchLib")  # schlib only: neither a pair nor an IntLib
