from stockroom.kicad.symbol_lib import SymbolLib
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
