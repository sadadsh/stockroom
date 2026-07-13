from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from tests.backend.conftest import requires_kicad_cli


@requires_kicad_cli
def test_edited_symbol_lib_still_exports(tmp_fixture, tmp_path):
    src = tmp_fixture("minimal.kicad_sym")
    lib = SymbolLib.load(src)
    lib.get_symbol("R_0603").set_property("MPN", "RC0603FR-0710KL")
    lib.get_symbol("R_0603").set_property("Tolerance", "1%")
    lib.save(src)
    # kicad-cli parsing the edited lib and exporting a symbol proves it is valid.
    out = KiCadCli().sym_export_svg(src, "R_0603", tmp_path)
    assert out and out[0].exists()


@requires_kicad_cli
def test_edited_footprint_still_exports(tmp_fixture, tmp_path):
    # place the fixture inside a .pretty dir, since fp export needs the directory
    pretty = tmp_path / "SR-Resistors.pretty"
    pretty.mkdir()
    src = pretty / "R_0603.kicad_mod"
    # Read with newline="" to preserve line endings exactly
    with open(tmp_fixture("minimal.kicad_mod"), encoding="utf-8", newline="") as f:
        content = f.read()
    # Write with newline="" to preserve line endings exactly
    with open(src, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    fp = Footprint.load(src)
    fp.set_model_path("${SR_LIB}/models/Resistors/R_0603.step")
    fp.save(src)
    svg = KiCadCli().fp_export_svg(pretty, "R_0603", tmp_path / "out")
    assert svg.exists()
