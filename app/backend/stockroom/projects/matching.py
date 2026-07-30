"""EDA-owned normalization for shared project-to-library matching.

Placed project components already enter shared matching through an adapter.
Library records need the same boundary: native symbol and footprint references
mean different things in KiCad and Altium, so shared matching consumes one
normalized shape and never branches on an EDA key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from stockroom.model.category import category_nickname
from stockroom.model.part import Asset, PartRecord


@dataclass(frozen=True, slots=True)
class NormalizedLibraryAssets:
    """The native asset identity shared matching is allowed to inspect."""

    symbol_name: str
    symbol_ref: str
    footprint_ref: str
    symbol_is_identity: bool
    nickname: str = ""


class ProjectMatchStrategy(Protocol):
    """Normalize one library part into an adapter's placement vocabulary."""

    def normalize_part(self, part: PartRecord) -> NormalizedLibraryAssets: ...


def _kicad_lib_id(ref: Asset | None) -> str:
    if ref is None:
        return ""
    library = (ref.lib or "").strip()
    name = (ref.name or "").strip()
    return f"{library}:{name}" if library and name else ""


class KiCadProjectMatchStrategy:
    """Normalize Stockroom records to KiCad ``<library>:<entry>`` identities."""

    def normalize_part(self, part: PartRecord) -> NormalizedLibraryAssets:
        try:
            nickname = category_nickname(part.category)
        except ValueError:
            nickname = ""
        assets = part.assets_for("kicad")
        symbol = assets.symbol
        footprint = assets.footprint
        symbol_name = ((symbol.name if symbol else "") or "").strip()
        return NormalizedLibraryAssets(
            symbol_name=symbol_name,
            symbol_ref=_kicad_lib_id(symbol),
            footprint_ref=_kicad_lib_id(footprint),
            symbol_is_identity=bool(
                nickname
                and symbol
                and (symbol.lib or "").strip() == nickname
            ),
            nickname=nickname,
        )


class AltiumProjectMatchStrategy:
    """Normalize Stockroom records to Altium Library Ref/model identities."""

    def normalize_part(self, part: PartRecord) -> NormalizedLibraryAssets:
        assets = part.assets_for("altium")
        symbol = assets.symbol
        footprint = assets.footprint
        symbol_name = ((symbol.name if symbol else "") or "").strip()
        footprint_name = ((footprint.name if footprint else "") or "").strip()
        return NormalizedLibraryAssets(
            symbol_name=symbol_name,
            symbol_ref=f"altium:{symbol_name}" if symbol_name else "",
            footprint_ref=footprint_name,
            # An Altium Library Ref can be a generic RES/CAP entry shared by
            # thousands of parts. It is never part identity on its own.
            symbol_is_identity=False,
        )
