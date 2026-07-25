"""Capture requirements: the per-EDA-tool assets a part still needs.

Pure (no pywebview). Shared by the API (which reports a part's needs) and the host capture
session. ``Requirement`` values are the wire contract the TypeScript ``Requirement`` union
mirrors, and the same `<tool>_<kind>` vocabulary ``LibraryOps.detach_asset`` speaks.

The members are spelled out rather than generated at import time. This is a WIRE CONTRACT --
the TypeScript union, the capture HUD's labels and the host bridge all speak these exact
strings -- and a contract belongs in source where it can be read, grepped and jumped to, not
conjured from a loop. What keeps it honest instead is
`test_the_enum_covers_exactly_the_registry`: registering a third EDA tool turns that test red
with the members to add, so the enum can never silently fall behind the registry.

An asset kind a tool cannot take by reference has NO member: an Altium 3D model lives inside
the footprint's `.PcbLib` binary, so asking a capture session to fetch one names a gap that
can never be closed.
"""

from __future__ import annotations

from enum import Enum

from stockroom.eda.registry import all_tools


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
    """
    needs: list[Requirement] = []
    for tool_key, kind in _capturable():
        if kind == "model" and getattr(record, "passive", False):
            # A passive references the stock footprint, which carries its own 3D body.
            continue
        ref = record.assets_for(tool_key).get(kind)
        if ref is None or not (ref.name or ref.file):
            needs.append(requirement(tool_key, kind))
    return needs
