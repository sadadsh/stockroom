"""Normalize incoming vendor symbol/footprint files to current KiCad V10 format
through KiCad's own tooling (spec section 5, stage 2). Legacy .lib and foreign
formats are a standard input, not an edge case. Incoming files are re-serialized
freely here; byte preservation applies only to the TARGET library files, which
are written later by the M2 placement primitives."""

from __future__ import annotations

import shutil
from pathlib import Path

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib


def normalize_symbol(cli: KiCadCli, src: Path, dcm: Path | None, workdir: Path) -> Path:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    if src.suffix == ".kicad_sym":
        # already a native symbol library: copy into the sandbox and use as-is
        # (the reference importer loads .kicad_sym directly, upgrading only .lib).
        dst = workdir / src.name
        shutil.copyfile(src, dst)
        return dst
    # legacy .lib or foreign format: upgrade via kicad-cli. Keep the source and
    # the output on distinct paths (never src == dst). A sibling .dcm named like
    # the library is copied next to the source so kicad-cli merges descriptions.
    in_dir = workdir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    staged_src = in_dir / src.name
    shutil.copyfile(src, staged_src)
    if dcm is not None:
        shutil.copyfile(dcm, in_dir / (staged_src.stem + ".dcm"))
    out = workdir / "normalized.kicad_sym"
    cli.sym_upgrade(staged_src, out)
    return out


def read_symbol_names(kicad_sym: Path) -> list[str]:
    return SymbolLib.load(kicad_sym).symbol_names


def normalize_footprint(cli: KiCadCli, src: Path, workdir: Path) -> Path:
    workdir = Path(workdir)
    pretty = workdir / "normalize.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    dst = pretty / src.name
    shutil.copyfile(src, dst)
    cli.fp_upgrade(pretty)
    return dst
