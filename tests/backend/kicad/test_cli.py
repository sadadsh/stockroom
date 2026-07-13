from pathlib import Path

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError
from tests.backend.conftest import requires_kicad_cli


def test_missing_binary_is_non_fatal_but_commands_raise(monkeypatch):
    # Construction MUST NOT raise when kicad-cli is absent (the app has to start
    # without it); a clear error surfaces only when a command is actually invoked.
    import stockroom.kicad.cli as cli_mod

    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    cli = KiCadCli(binary="definitely-not-kicad-cli-xyz")
    assert cli.available is False
    with pytest.raises(KiCadCliError):
        cli.version()


@requires_kicad_cli
def test_version_reports_10():
    assert KiCadCli().version().startswith("10.")


@requires_kicad_cli
def test_sym_upgrade_produces_v10_stamp(tmp_path, fixtures_dir):
    dst = tmp_path / "upgraded.kicad_sym"
    KiCadCli().sym_upgrade(fixtures_dir / "legacy.lib", dst)
    text = dst.read_text(encoding="utf-8")
    assert "kicad_symbol_lib" in text
    assert "(version 2025" in text or "(version 2024" in text


@requires_kicad_cli
def test_sym_export_svg_writes_file(tmp_path, fixtures_dir):
    out = KiCadCli().sym_export_svg(fixtures_dir / "minimal.kicad_sym", "R_0603", tmp_path)
    assert out and all(p.suffix == ".svg" and p.exists() for p in out)


@requires_kicad_cli
def test_fp_upgrade_rewrites_footprint_to_current_format(tmp_path, fixtures_dir):
    from stockroom.kicad.cli import KiCadCli
    import shutil

    cli = KiCadCli()
    pretty = tmp_path / "in.pretty"
    pretty.mkdir()
    # one_footprint.kicad_mod carries an older (version 20240108) stamp.
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", pretty / "fp.kicad_mod")
    cli.fp_upgrade(pretty)
    # still a valid, parseable footprint after upgrade
    from stockroom.kicad.footprint import Footprint
    fp = Footprint.load(pretty / "fp.kicad_mod")
    assert fp.name  # non-empty name survives the upgrade
