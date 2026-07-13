"""Fingerprint an unpacked vendor package by its CONTENT, never its origin, and
locate the symbol, footprint(s), 3D model, datasheet, and .dcm. Ported from the
reference importer Steffen-W/Import-LIB-KiCad-Plugin::identify_remote_type,
whose detection order and folder-name capitalization are load-bearing because
they must match real vendor output (spec section 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.errors import IngestError


@dataclass
class DetectedSource:
    vendor: str
    symbol_path: Path | None = None
    dcm_path: Path | None = None
    footprint_paths: list[Path] = field(default_factory=list)
    model_path: Path | None = None
    datasheet_path: Path | None = None


def _walk(root: Path):
    """Depth-first iterator over every path under root (dirs and files)."""
    for child in sorted(root.iterdir()):
        yield child
        if child.is_dir():
            yield from _walk(child)


def _find(root: Path, suffix: str) -> Path | None:
    """First path whose name ends with `suffix` (matches the reference's
    endswith semantics), searched depth-first for a stable result."""
    for p in _walk(root):
        if p.name.endswith(suffix):
            return p
    return None


def _find_all(root: Path, suffix: str) -> list[Path]:
    return [p for p in _walk(root) if p.is_file() and p.name.endswith(suffix)]


def _find_dir(root: Path, exact_name: str) -> Path | None:
    for p in _walk(root):
        if p.is_dir() and p.name == exact_name:
            return p
    return None


def _first_footprint_lib(root: Path) -> Path | None:
    for p in _walk(root):
        if p.is_dir() and p.name.endswith(".pretty"):
            return p
    return None


def _find_symbol(root: Path) -> Path | None:
    return _find(root, ".kicad_sym") or _find(root, ".lib")


def _find_model(root: Path) -> Path | None:
    return _find(root, ".step") or _find(root, ".stp") or _find(root, ".wrl")


def detect_source(root: Path) -> DetectedSource:
    root = Path(root)
    model = _find_model(root)
    datasheet = _find(root, ".pdf")

    # 1. Octopart: fixed legacy filenames device.lib + device.dcm.
    dev_lib = _find(root, "device.lib")
    dev_dcm = _find(root, "device.dcm")
    if dev_lib is not None and dev_dcm is not None:
        pretty = _first_footprint_lib(root)
        fps = _find_all(pretty, ".kicad_mod") if pretty else _find_all(root, ".kicad_mod")
        return DetectedSource("octopart", dev_lib, dev_dcm, fps, model, datasheet)

    # 2. Samacsys / Component Search Engine: a folder named exactly "KiCad" with a
    #    LOOSE .kicad_mod inside it.
    kicad_dir = _find_dir(root, "KiCad")
    if kicad_dir is not None:
        return DetectedSource(
            "samacsys",
            _find_symbol(kicad_dir),
            _find(kicad_dir, ".dcm"),
            _find_all(kicad_dir, ".kicad_mod"),
            model,
            datasheet,
        )

    # 3. UltraLibrarian: a folder named exactly "KiCAD" (capitalization is the
    #    discriminator from Samacsys) with a real .pretty inside it. The symbol
    #    file is often timestamp-named, so identity is never the filename.
    kicad_dir = _find_dir(root, "KiCAD")
    if kicad_dir is not None:
        pretty = _first_footprint_lib(kicad_dir)
        fps = _find_all(pretty, ".kicad_mod") if pretty else _find_all(kicad_dir, ".kicad_mod")
        return DetectedSource(
            "ultralibrarian",
            _find_symbol(kicad_dir),
            _find(kicad_dir, ".dcm"),
            fps,
            model,
            datasheet,
        )

    # 4. Snapeda / SnapMagic fallback: loose files, no marker folder.
    symbol = _find_symbol(root)
    if symbol is not None:
        fp = _find(root, ".kicad_mod")
        return DetectedSource(
            "snapeda",
            symbol,
            _find(root, ".dcm"),
            [fp] if fp is not None else [],
            model,
            datasheet,
        )

    # 5. Partial: only a 3D model.
    if model is not None:
        return DetectedSource("partial", None, None, [], model, datasheet)

    raise IngestError("unable to identify package: no symbol, footprint, or model found")
