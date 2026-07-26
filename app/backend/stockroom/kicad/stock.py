"""Locate files inside the installed KiCad STOCK libraries.

A passive references KiCad's stock symbol/footprint/3D by lib_id (Device:R,
Resistor_SMD:R_0603_1608Metric, ...) instead of owning copied asset files, so any
operation that needs the actual file (previews) resolves it here from the installed
KiCad share directory. Returns None when KiCad is not installed, so callers degrade
honestly rather than crash.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else -1 for p in name.split("."))


def _candidate_share_dirs() -> list[Path]:
    """The KiCad `share/kicad` directories (holding symbols/ footprints/ 3dmodels/),
    newest install first, per OS."""
    if sys.platform.startswith("win"):
        out: list[Path] = []
        seen: set[Path] = set()
        for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            root = Path(base) / "KiCad"
            if root in seen:
                continue
            seen.add(root)
            try:
                if not root.is_dir():
                    continue
                vers = [d for d in root.iterdir() if d.is_dir() and d.name[:1].isdigit()]
            except OSError:
                continue
            for ver in sorted(vers, key=lambda d: _version_key(d.name), reverse=True):
                out.append(ver / "share" / "kicad")
        return out
    if sys.platform == "darwin":
        return [Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")]
    return [Path("/usr/share/kicad"), Path("/usr/local/share/kicad")]


def find_kicad_share_dir() -> Path | None:
    """The installed KiCad share directory, or None if KiCad is not installed."""
    for cand in _candidate_share_dirs():
        try:
            if cand.is_dir():
                return cand
        except OSError:
            continue
    return None


def stock_symbol_lib_file(lib: str, share: Path | None = None) -> Path | None:
    """The stock symbol library file for a symbol lib nickname (e.g. "Device" ->
    <share>/symbols/Device.kicad_sym), or None if absent."""
    share = share or find_kicad_share_dir()
    if share is None:
        return None
    path = share / "symbols" / f"{lib}.kicad_sym"
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def stock_footprint_file(lib: str, name: str, share: Path | None = None) -> Path | None:
    """The stock footprint .kicad_mod for a footprint lib_id (e.g. Resistor_SMD,
    R_0603_1608Metric), or None if absent."""
    share = share or find_kicad_share_dir()
    if share is None:
        return None
    path = share / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def stock_model_file(lib: str, name: str, share: Path | None = None) -> Path | None:
    """The stock 3D model for a footprint lib_id (the .wrl or .step under
    <share>/3dmodels/<lib>.3dshapes/), or None if absent."""
    share = share or find_kicad_share_dir()
    if share is None:
        return None
    base = share / "3dmodels" / f"{lib}.3dshapes"
    for ext in (".wrl", ".step", ".stp", ".STEP"):
        path = base / f"{name}{ext}"
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None
