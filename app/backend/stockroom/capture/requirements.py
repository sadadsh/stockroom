"""Capture requirements: the per-EDA-tool assets a part still needs.

Pure (no pywebview). Shared by the API planner and provider-evidence workflow.
``Requirement`` values are the wire contract the TypeScript ``Requirement`` union
mirrors, and the same `<tool>_<kind>` vocabulary ``LibraryOps.detach_asset`` speaks.

The members are spelled out rather than generated at import time. This is a WIRE CONTRACT --
the TypeScript union and provider HUD both speak these exact strings -- and a contract
belongs in source where it can be read, grepped and jumped to, not
conjured from a loop. What keeps it honest instead is
`test_the_enum_covers_exactly_the_registry`: registering a third EDA tool turns that test red
with the members to add, so the enum can never silently fall behind the registry.

An asset kind a tool cannot take by reference has NO member: an Altium 3D model lives inside
the footprint's `.PcbLib` binary, so asking the acquisition workflow to fetch one names a gap that
can never be closed.
"""

from __future__ import annotations

from enum import Enum

from stockroom.eda.registry import all_tools
from stockroom.model.part import asset_present


class Requirement(str, Enum):
    """One EDA tool's asset kind, as the wire value `<tool>_<kind>`."""

    KICAD_SYMBOL = "kicad_symbol"
    KICAD_FOOTPRINT = "kicad_footprint"
    KICAD_MODEL = "kicad_model"
    ALTIUM_SYMBOL = "altium_symbol"
    ALTIUM_FOOTPRINT = "altium_footprint"


def _capturable() -> list[tuple[str, str]]:
    """(tool key, asset kind) for every asset a tool can actually be given by reference,
    tools in registry order and kinds in each tool's registered order."""
    return [(tool.key, kind) for tool in all_tools() for kind in tool.capturable_assets()]


def requirement(tool: str, kind: str) -> "Requirement":
    """The Requirement for one tool/kind pair. Raises ValueError for a pair no registered
    tool can be given by reference -- never returns a silent None."""
    return Requirement(f"{tool}_{kind}")


def split_requirement(req: "Requirement") -> tuple[str, str]:
    """Requirement.KICAD_SYMBOL -> ("kicad", "symbol")."""
    tool, _, kind = str(req.value).partition("_")
    return tool, kind


def capture_needs(record) -> list[Requirement]:
    """The requirements a part is missing, in registry order (each tool's kinds together).

    Reads the record's per-tool asset bundles directly, so a part carrying a full KiCad set
    and no Altium set reports exactly the Altium gaps. The asymmetry that made every part
    read "CAD Incomplete" forever is gone by construction, not by a branch.

    A requirement is `f(part class, tool)`, and BOTH halves are data:

    - the PART CLASS says which asset kinds this part needs at all (model/part_class.py, spec
      decision D3), with `requires_override` for the genuine exception;
    - the EDA REGISTRY says which of those the tool can actually be given by reference.

    A passive therefore resolves to `[]` for every tool without this function knowing what a
    passive is. Owner, 2026-07-27: *"passive components dont need files, models or symbols not
    for kicad or for altium, theyre built in."* MEASURED before that rule existed: the
    completion surface demanded `altium_symbol` and `altium_footprint` from all 68 of the
    owner's passives - 136 requirements nothing could ever satisfy.
    """
    needs: list[Requirement] = []
    for tool_key, kind in _capturable():
        if kind not in record.capturable(tool_key):
            continue
        if not asset_present(record.assets_for(tool_key).get(kind)):
            needs.append(requirement(tool_key, kind))
    return needs
