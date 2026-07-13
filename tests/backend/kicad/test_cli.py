from pathlib import Path

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError
from tests.backend.conftest import requires_kicad_cli


def test_missing_binary_raises():
    with pytest.raises(KiCadCliError):
        KiCadCli(binary="definitely-not-kicad-cli-xyz")


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
