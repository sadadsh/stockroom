import pytest

from stockroom.kicad.category_lib import (
    create_empty_symbol_lib,
    ensure_footprint_lib,
)
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib
from tests.backend.conftest import requires_kicad_cli


def test_ensure_footprint_lib_creates_pretty_dir(tmp_path):
    pretty = tmp_path / "SR-ICs.pretty"
    ensure_footprint_lib(pretty)
    assert pretty.is_dir()
    # idempotent
    ensure_footprint_lib(pretty)
    assert pretty.is_dir()


@requires_kicad_cli
def test_create_empty_symbol_lib_is_v10_stamped(tmp_path):
    cli = KiCadCli()
    dst = tmp_path / "SR-ICs.kicad_sym"
    create_empty_symbol_lib(cli, dst)
    lib = SymbolLib.load(dst)
    assert lib.version == "20251024"
    assert lib.symbol_names == []


@requires_kicad_cli
def test_create_empty_symbol_lib_is_idempotent(tmp_path):
    cli = KiCadCli()
    dst = tmp_path / "SR-ICs.kicad_sym"
    create_empty_symbol_lib(cli, dst)
    first = dst.read_bytes()
    create_empty_symbol_lib(cli, dst)  # must not overwrite / re-stamp
    assert dst.read_bytes() == first
