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

from stockroom.projects import binding
from stockroom.projects.adapters import get_adapter


def supported(tool_key: str) -> bool:
    try:
        get_adapter(tool_key)
    except ValueError:
        return False
    return True


def read_placements(rec, stored_bindings: dict[str, str] | None = None) -> list[dict]:
    """Every placed component of a registered project, with its durable binding already resolved
    into `props` so every downstream stage reads the binding the same way.

    Raises ValueError for a tool with no reader, naming it, rather than silently returning an
    empty project (which would read as "this project has no components").
    """
    tool = getattr(rec, "eda", "") or "kicad"
    adapter = get_adapter(tool)
    comps = adapter.placements(rec)
    stored = stored_bindings if stored_bindings is not None else binding.stored_for(rec, tool)
    return binding.resolve(comps, tool, stored=stored)
