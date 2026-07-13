import shutil

import pytest

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import Datasheet, LibRef, PartRecord
from stockroom.mutation.placement import (
    PlacementError,
    assert_only_added,
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)


def test_assert_only_added_passes_for_pure_addition():
    before = '(kicad_symbol_lib (version 20251024))'
    after = '(kicad_symbol_lib (version 20251024) (symbol "X"))'
    assert_only_added(before, after)  # no raise


def test_assert_only_added_rejects_a_change():
    before = '(kicad_symbol_lib (version 20251024))'
    after = '(kicad_symbol_lib (version 20240101))'
    with pytest.raises(PlacementError):
        assert_only_added(before, after)


def _empty_lib(tmp_path):
    p = tmp_path / "SR-ICs.kicad_sym"
    p.write_text('(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline="")
    return p


def test_merge_symbol_appends_renamed_symbol(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, source_name="TESTPART", new_name="TPS62130RGTR")
    lib = SymbolLib.load(lib_path)
    assert lib.symbol_names == ["TPS62130RGTR"]
    assert lib.version == "20251024"  # untouched


def test_merge_symbol_rejects_duplicate_name(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, "TESTPART", "PART1")
    with pytest.raises(PlacementError):
        merge_symbol_into_lib(lib_path, src, "TESTPART", "PART1")


def test_place_footprint_copies_and_renames(tmp_path, fixtures_dir):
    pretty = tmp_path / "SR-ICs.pretty"
    pretty.mkdir()
    src = tmp_path / "one_footprint.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", src)
    out = place_footprint(pretty, src, "VQFN-16")
    assert out == pretty / "VQFN-16.kicad_mod"
    assert Footprint.load(out).name == "VQFN-16"


def test_mirror_fields_writes_kicad_properties(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, "TESTPART", "TPS62130RGTR")
    lib = SymbolLib.load(lib_path)
    sym = lib.get_symbol("TPS62130RGTR")
    record = PartRecord(
        id="tps62130rgtr", display_name="TPS62130", category="ICs",
        description="buck", tags=["dcdc", "buck"], mpn="TPS62130RGTR",
        manufacturer="TI", datasheet=Datasheet(file="tps.pdf"),
    )
    mirror_fields_to_symbol(sym, record)
    lib.save(lib_path)
    reloaded = SymbolLib.load(lib_path).get_symbol("TPS62130RGTR")
    assert reloaded.get_property("MPN") == "TPS62130RGTR"
    assert reloaded.get_property("Manufacturer") == "TI"
    assert reloaded.get_property("Description") == "buck"
    assert reloaded.get_property("ki_keywords") == "dcdc buck"
    assert reloaded.get_property("Datasheet") == "${SR_LIB}/datasheets/tps.pdf"
