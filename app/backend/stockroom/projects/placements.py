"""Read a registered project's PLACED components, in one shape, whichever EDA tool owns it.

The adapter layer the registry implies: the registry holds a tool's facts as data, this module
holds the one piece that genuinely cannot be data (how to open that tool's files), and everything
downstream -- readiness, the fill plan, bulk assign, the BOM -- is generic code over the result.
Adding a third tool is a registry entry plus one reader here, never a branch at a call site.

Every reader yields the same dict, so the binding layer, the matcher and the completion passport
cannot tell the tools apart:

    {ref, uuid, lib_id, value, footprint, props, _sheet}

`uuid` is the tool's own durable per-placement identity (a KiCad symbol `(uuid ...)`, an Altium
component `UNIQUEID`), which is what a binding is keyed by; `_sheet` is the sheet path relative to
the project root, for display.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.projects import binding


def sheet_paths(rec) -> list[Path]:
    """The project's schematic sheets that exist on disk, absolute, in registered order. A sheet
    that moved after registration is skipped: it cannot be read, and pretending otherwise would
    turn a stale registration into a crash deep inside a parser."""
    root = Path(rec.root)
    return [root / s for s in (rec.sheet_paths or []) if (root / s).exists()]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _read_kicad(rec, root: Path) -> list[dict]:
    from stockroom.projects.fill import read_components
    from stockroom.sexp.document import SexpDocument

    out: list[dict] = []
    for path in sheet_paths(rec):
        rel = _relative(path, root)
        for comp in read_components(SexpDocument.load(path)):
            comp["_sheet"] = rel
            out.append(comp)
    return out


def _read_altium(rec, root: Path) -> list[dict]:
    from stockroom.projects.health import _collect_altium

    comps, _findings, _n = _collect_altium(root, rec.sheet_paths)
    for comp in comps:
        # `_collect_altium` already dedupes across sheets by (ref, lib_ref); the sheet a
        # component was found on is not tracked there, so the label stays honest rather than
        # guessing one.
        comp.setdefault("_sheet", rec.pro_path or "")
    return comps


# The one place a tool's file reader is named. Keyed by the registry's tool key.
_READERS = {"kicad": _read_kicad, "altium": _read_altium}


def supported(tool_key: str) -> bool:
    return tool_key in _READERS


def read_placements(rec, stored_bindings: dict[str, str] | None = None) -> list[dict]:
    """Every placed component of a registered project, with its durable binding already resolved
    into `props` so every downstream stage reads the binding the same way.

    Raises ValueError for a tool with no reader, naming it, rather than silently returning an
    empty project (which would read as "this project has no components").
    """
    tool = getattr(rec, "eda", "") or "kicad"
    reader = _READERS.get(tool)
    if reader is None:
        raise ValueError(
            f"{rec.name} is registered for {tool!r}, which Stockroom cannot read placements for"
        )
    comps = reader(rec, Path(rec.root))
    stored = stored_bindings if stored_bindings is not None else binding.stored_for(rec, tool)
    return binding.resolve(comps, tool, stored=stored)
