import shutil

from tests.backend.conftest import requires_kicad_cli

# requires_kicad_cli is a pytest.mark.skipif; usable as a module-level pytestmark
# so every test here skips cleanly when the binary is absent.
pytestmark = requires_kicad_cli


def _cli():
    from stockroom.kicad.cli import KiCadCli
    return KiCadCli()


def test_normalize_legacy_lib_becomes_kicad_sym(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_symbol, read_symbol_names
    src = tmp_path / "in.lib"
    shutil.copyfile(fixtures_dir / "legacy.lib", src)
    out = normalize_symbol(_cli(), src, None, tmp_path / "work")
    assert out.suffix == ".kicad_sym"
    names = read_symbol_names(out)
    assert len(names) >= 1


def test_normalize_kicad_sym_passthrough_reads_inner_name(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_symbol, read_symbol_names
    src = tmp_path / "2025-02-10_09-58-00.kicad_sym"  # timestamp-named on purpose
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    out = normalize_symbol(_cli(), src, None, tmp_path / "work")
    # name comes from INSIDE the file, not the timestamp filename
    assert "TESTPART" in read_symbol_names(out)


def test_normalize_footprint_upgrades_in_place(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_footprint
    from stockroom.kicad.footprint import Footprint
    src = tmp_path / "old.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", src)
    out = normalize_footprint(_cli(), src, tmp_path / "work")
    assert out.suffix == ".kicad_mod"
    assert Footprint.load(out).name  # parseable, named
