"""Where one component's files are, and how they leave the library.

Three Manage actions need this module and nothing else does: `Export Component...`,
`Open In...` and `Reveal Component Files...`. All three end in the operating system doing
something with a path, which is why every path they use is computed HERE, from the active
library root and a part id, and never accepted from a caller.

That is the whole security posture. A shell-open command that takes a path from the web layer
is a remote-code-execution shape wearing a convenience label: the browser process is the least
trusted thing in the product, and "reveal this folder" with a caller-supplied argument is
"start Explorer on anything". So the API surface takes a part id, this module resolves the
directory, `_require_inside` refuses anything that leaves the root, and the native window host
independently refuses the same thing again. Two checks that can each fail closed is the point;
one check is a check that stops existing the day someone edits the other side.

The export writes OUTSIDE the library, into a machine-local directory. Exports are derived
copies, not library content: writing them into the profile would put a growing pile of
regenerable files into every peer's git history. Nothing here mutates the library, so no
`mutation.Transaction` is opened; the one KiCad write it performs (extracting a single symbol
from its category library) goes through `sexp` via `SymbolLib`, the same reader/writer every
other KiCad write in the product uses.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import PartRecord
from stockroom.model.sourced import SOURCED_DIRNAME
from stockroom.store.machine_config import config_dir

# The formats a component can leave the library in. `altium` is deliberately absent: native
# Altium libraries are binary containers Stockroom stores verbatim and cannot subset, so an
# "Altium" entry here would be an offer this code cannot keep.
EXPORT_FORMATS: tuple[str, ...] = ("kicad", "step")

_EXPORT_ROOT_NAME = "Component Exports"


class ComponentShellError(Exception):
    """A component's files cannot be located, exported, or handed to the shell."""


@dataclass(frozen=True, slots=True)
class ExportedComponent:
    """One completed export: where it went, and what a person can open from it."""

    format: str
    root: Path
    directory: Path
    primary_file: Path
    files: tuple[Path, ...]


def _require_inside(root: Path, candidate: Path, label: str) -> Path:
    """`candidate`, resolved, once it is proved to be inside `root`.

    `Path.resolve` follows links, so a junction planted inside the library that points at
    `C:\\Windows` is caught here rather than being followed later by Explorer.
    """

    resolved_root = Path(root).resolve(strict=False)
    resolved = Path(candidate).resolve(strict=False)
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ComponentShellError(f"{label} escapes the library root")
    return resolved


def component_directory(library_root: Path, part_id: str) -> Path:
    """The one directory this library gives this component, resolved through the root.

    `sourced/<part id>` is that directory: every other library folder is shared by kind
    (`symbols/`, `footprints/`, `models/`), so it is the only place on disk that belongs to one
    component and nothing else.

    The part id is never joined blind. A traversal id resolves outside the root and is refused
    by `_require_inside`, which is the check `Reveal Component Files...` rests on.
    """

    if not part_id or part_id != part_id.strip():
        raise ComponentShellError("component id is invalid")
    return _require_inside(
        library_root,
        Path(library_root) / SOURCED_DIRNAME / part_id,
        "component directory",
    )


def export_root() -> Path:
    """The machine-local root every export lands under. Never inside the library."""

    return (config_dir() / _EXPORT_ROOT_NAME).resolve(strict=False)


def component_export_directory(part_id: str, export_format: str) -> Path:
    """Where one component's export of one format lives, resolved through the export root."""

    if export_format not in EXPORT_FORMATS:
        raise ComponentShellError(f"unsupported export format: {export_format}")
    if not part_id or part_id != part_id.strip():
        raise ComponentShellError("component id is invalid")
    root = export_root()
    candidate = root / part_id / export_format
    resolved_root = root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved_root not in resolved.parents:
        raise ComponentShellError("component export directory escapes the export root")
    return resolved


def available_export_formats(profile_library, record: PartRecord) -> tuple[str, ...]:
    """The formats this component really has the files for, in presentation order.

    A format with nothing behind it is left out rather than offered and failed: `Export
    Component...` lists what can be exported, and an entry that produces an empty folder is a
    dead click path with a progress bar.
    """

    available: list[str] = []
    if _kicad_symbol_source(profile_library, record) is not None:
        available.append("kicad")
    if _model_source(profile_library, record) is not None:
        available.append("step")
    return tuple(available)


def _kicad_symbol_source(profile_library, record: PartRecord) -> tuple[Path, str] | None:
    """The category symbol library holding this component, and its entry name."""

    try:
        assets = record.assets_for("kicad")
    except KeyError:
        return None
    symbol = assets.symbol
    name = "" if symbol is None else (symbol.ref.name or "")
    if not name:
        return None
    path = profile_library.symbol_lib_path(record.category)
    return (path, name) if path.is_file() else None


def _kicad_footprint_source(profile_library, record: PartRecord) -> Path | None:
    try:
        assets = record.assets_for("kicad")
    except KeyError:
        return None
    footprint = assets.footprint
    name = "" if footprint is None else (footprint.ref.name or "")
    if not name:
        return None
    path = profile_library.footprint_lib_path(record.category) / f"{name}.kicad_mod"
    return path if path.is_file() else None


def _model_source(profile_library, record: PartRecord) -> Path | None:
    for tool in ("kicad", "altium"):
        try:
            assets = record.assets_for(tool)
        except KeyError:
            continue
        model = assets.model
        basename = "" if model is None else Path(model.ref.file or "").name
        if not basename:
            continue
        path = profile_library.models_dir / basename
        if path.is_file():
            return path
    return None


def export_component(
    profile_library,
    record: PartRecord,
    export_format: str,
) -> ExportedComponent:
    """Write this component's CAD set for one format into its machine-local export directory.

    Idempotent by replacement: the format's directory is emptied first, so exporting twice
    leaves one current set rather than a pile of ambiguous siblings.
    """

    if export_format not in EXPORT_FORMATS:
        raise ComponentShellError(f"unsupported export format: {export_format}")
    if export_format not in available_export_formats(profile_library, record):
        raise ComponentShellError(
            f"this component has no {export_format} files to export"
        )
    destination = component_export_directory(record.id, export_format)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if export_format == "kicad":
        primary = _export_kicad(profile_library, record, destination, written)
    else:
        primary = _export_step(profile_library, record, destination, written)
    return ExportedComponent(
        format=export_format,
        root=export_root(),
        directory=destination,
        primary_file=primary,
        files=tuple(written),
    )


def _export_kicad(
    profile_library,
    record: PartRecord,
    destination: Path,
    written: list[Path],
) -> Path:
    """One `.kicad_sym` holding only this component, plus its footprint and 3D model."""

    source = _kicad_symbol_source(profile_library, record)
    if source is None:  # pragma: no cover - availability was checked by the caller
        raise ComponentShellError("this component has no KiCad symbol to export")
    library_path, entry_name = source
    # Through `sexp`, like every other KiCad write in the product: the category library is
    # parsed, every entry that is not this component is removed, and the remainder is
    # serialized by the same writer, so the exported file is byte-shaped like KiCad's own.
    library = SymbolLib.load(library_path)
    for name in library.symbol_names:
        if name != entry_name:
            library.remove_symbol(name)
    if not library.symbol_names:
        raise ComponentShellError("this component's symbol is not in its category library")
    symbol_path = destination / f"{entry_name}.kicad_sym"
    library.save(symbol_path)
    written.append(symbol_path)
    footprint = _kicad_footprint_source(profile_library, record)
    if footprint is not None:
        footprint_path = destination / footprint.name
        shutil.copy2(footprint, footprint_path)
        written.append(footprint_path)
    model = _model_source(profile_library, record)
    if model is not None:
        model_path = destination / model.name
        shutil.copy2(model, model_path)
        written.append(model_path)
    return symbol_path


def _export_step(
    profile_library,
    record: PartRecord,
    destination: Path,
    written: list[Path],
) -> Path:
    model = _model_source(profile_library, record)
    if model is None:  # pragma: no cover - availability was checked by the caller
        raise ComponentShellError("this component has no 3D model to export")
    model_path = destination / model.name
    shutil.copy2(model, model_path)
    written.append(model_path)
    return model_path


__all__ = [
    "EXPORT_FORMATS",
    "ComponentShellError",
    "ExportedComponent",
    "available_export_formats",
    "component_directory",
    "component_export_directory",
    "export_component",
    "export_root",
]
