from pathlib import Path

from stockroom.altium.oleread import read_footprint_names, read_symbol_names

FIX = Path(__file__).parent / "fixtures"


def test_symbol_names_from_real_schlib():
    assert read_symbol_names(FIX / "sample.SchLib") == ["S1M"]


def test_footprint_names_from_real_pcblib_excludes_metadata():
    # FileVersionInfo + Library are metadata storages that ALSO carry a Data stream; a naive
    # "storage with a Data child" walk returns them as false-positive footprints. They must be
    # excluded so only the real footprint DIOM5227X270N remains.
    assert read_footprint_names(FIX / "sample.PcbLib") == ["DIOM5227X270N"]
