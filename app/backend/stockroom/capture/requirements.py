"""Capture requirements: the KiCad + Altium asset types a part still needs.

Pure (no pywebview). Shared by the API (which reports a part's needs) and the
host capture session. ``Requirement.value`` strings are the wire contract
mirrored by the TypeScript ``Requirement`` union in the frontend.
"""

from __future__ import annotations

from enum import Enum


class Requirement(str, Enum):
    KICAD_SYMBOL = "kicad_symbol"
    KICAD_FOOTPRINT = "kicad_footprint"
    KICAD_MODEL = "kicad_model"
    ALTIUM_SYMBOL = "altium_symbol"
    ALTIUM_FOOTPRINT = "altium_footprint"


# missing_assets() human labels -> the KiCad requirement they map to.
# Labels come from stockroom.model.part.ATTACHABLE_ASSETS
# (('symbol', 'symbol'), ('footprint', 'footprint'), ('model', '3D model')).
_LABEL_TO_REQ = {
    "symbol": Requirement.KICAD_SYMBOL,
    "footprint": Requirement.KICAD_FOOTPRINT,
    "3D model": Requirement.KICAD_MODEL,
}


def _has_altium(ref) -> bool:
    return ref is not None and bool(getattr(ref, "name", ""))


def capture_needs(record) -> list[Requirement]:
    """The requirements a part is missing, KiCad assets then Altium assets."""
    needs: list[Requirement] = []
    missing = set(record.missing_assets())
    for label, req in _LABEL_TO_REQ.items():
        if label in missing:
            needs.append(req)
    if not _has_altium(getattr(record, "altium_symbol", None)):
        needs.append(Requirement.ALTIUM_SYMBOL)
    if not _has_altium(getattr(record, "altium_footprint", None)):
        needs.append(Requirement.ALTIUM_FOOTPRINT)
    return needs
