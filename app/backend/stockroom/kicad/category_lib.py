"""Create empty per-category KiCad libraries.

An empty symbol library must carry the installed KiCad's version stamp, and
Stockroom never invents a stamp (spec section 8). Verified route: upgrade a
canonical empty legacy library through kicad-cli, which emits the current
(version 20251024) stamp. An empty .pretty directory is already a valid empty
footprint library.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib

EMPTY_LEGACY_LIB = "EESchema-LIBRARY Version 2.4\n#\n#End Library\n"


def create_empty_symbol_lib(cli: KiCadCli, dst: Path) -> None:
    dst = Path(dst)
    if dst.exists():
        # already a valid symbol lib? leave it byte-for-byte untouched.
        try:
            SymbolLib.load(dst)
            return
        except Exception:
            pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "empty.lib"
        src.write_text(EMPTY_LEGACY_LIB, encoding="utf-8")
        cli.sym_upgrade(src, dst)


def ensure_footprint_lib(dst_pretty: Path) -> None:
    Path(dst_pretty).mkdir(parents=True, exist_ok=True)
