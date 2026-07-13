import pytest

from stockroom.kicad.errors import KiCadFileError
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.sexp.document import SexpDocument
from stockroom.verify.semdiff import assert_only_changed, semantic_diff


def test_lists_symbols_and_version(fixtures_dir):
    lib = SymbolLib.load(fixtures_dir / "minimal.kicad_sym")
    assert lib.symbol_names == ["R_0603"]
    assert lib.version == "20251024"


def test_get_and_set_existing_property(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    sym = lib.get_symbol("R_0603")
    assert sym.get_property("Value") == "R_0603"
    original = lib.serialize()
    sym.set_property("MPN", "RC0603FR-0710KL")
    assert sym.get_property("MPN") == "RC0603FR-0710KL"
    assert_only_changed(original, lib.serialize(), allowed_changes=1)


def test_set_absent_property_inserts(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    sym = lib.get_symbol("R_0603")
    original = lib.serialize()
    assert sym.get_property("Description") is None
    sym.set_property("Description", "10k 1% 0603 resistor")
    assert sym.get_property("Description") == "10k 1% 0603 resistor"
    # a pure insert adds nodes; assert no existing node was lost or changed
    diffs = [
        d
        for d in semantic_diff(original, lib.serialize())
        if d.startswith(("LOST", "CHANGED", "TYPE"))
    ]
    assert diffs == []


def test_version_stamp_is_preserved_on_edit(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    lib.get_symbol("R_0603").set_property("Value", "22k")
    assert "(version 20251024)" in lib.serialize()


def test_two_absent_properties_insert_without_corruption(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    sym = lib.get_symbol("R_0603")
    sym.set_property("Tolerance", "1%")
    sym.set_property("Wattage", "0.1W")
    out = lib.serialize()
    reparsed = SymbolLib(SexpDocument.parse(out)).get_symbol("R_0603")
    assert reparsed.get_property("Tolerance") == "1%"
    assert reparsed.get_property("Wattage") == "0.1W"
    assert "(version 20251024)" in out


def test_insert_symbol_appends_and_only_adds(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    before = lib.serialize()
    lib.insert_symbol('(symbol "NEWPART" (property "Reference" "U" (at 0 0 0)))')
    after = lib.serialize()
    assert "NEWPART" in lib.symbol_names
    assert all(d.startswith("ADDED") for d in semantic_diff(before, after))
    assert "(version 20251024)" in after


def test_remove_symbol_and_missing_raises(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    lib.remove_symbol("R_0603")
    assert lib.symbol_names == []
    with pytest.raises(KiCadFileError):
        lib.remove_symbol("R_0603")
