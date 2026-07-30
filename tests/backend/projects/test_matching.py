from __future__ import annotations

from stockroom.model.part import AssetRef, EdaAssets, PartRecord
from stockroom.projects.adapters import get_adapter
from stockroom.projects.fill import library_match_records, match_component
from stockroom.projects.matching import (
    AltiumProjectMatchStrategy,
    KiCadProjectMatchStrategy,
)


def _part() -> PartRecord:
    return PartRecord(
        id="resistor",
        display_name="10k 0402",
        category="Resistors",
        mpn="RC0402FR-0710KL",
        manufacturer="Yageo",
        assets={
            "kicad": EdaAssets(
                symbol=AssetRef(lib="SR-Resistors", name="R_10k"),
                footprint=AssetRef(lib="SR-Resistors", name="R_0402"),
            ),
            "altium": EdaAssets(
                symbol=AssetRef(lib="Stockroom.SchLib", name="RES"),
                footprint=AssetRef(lib="Stockroom.PcbLib", name="R_0402"),
            ),
        },
    )


def test_adapters_own_their_library_matching_strategy() -> None:
    assert isinstance(get_adapter("kicad").matching, KiCadProjectMatchStrategy)
    assert isinstance(get_adapter("altium").matching, AltiumProjectMatchStrategy)


def test_kicad_normalizes_owned_library_references_to_placement_shape() -> None:
    normalized = get_adapter("kicad").matching.normalize_part(_part())

    assert normalized.symbol_name == "R_10k"
    assert normalized.symbol_ref == "SR-Resistors:R_10k"
    assert normalized.footprint_ref == "SR-Resistors:R_0402"
    assert normalized.symbol_is_identity
    assert normalized.nickname == "SR-Resistors"


def test_kicad_stock_symbol_is_not_part_identity() -> None:
    part = _part()
    part.assets["kicad"] = EdaAssets(
        symbol=AssetRef(lib="Device", name="R"),
        footprint=AssetRef(lib="Resistor_SMD", name="R_0402_1005Metric"),
    )

    normalized = get_adapter("kicad").matching.normalize_part(part)

    assert normalized.symbol_ref == "Device:R"
    assert not normalized.symbol_is_identity


def test_altium_normalizes_library_ref_without_promoting_generic_symbol() -> None:
    normalized = get_adapter("altium").matching.normalize_part(_part())

    assert normalized.symbol_name == "RES"
    assert normalized.symbol_ref == "altium:RES"
    assert normalized.footprint_ref == "R_0402"
    assert not normalized.symbol_is_identity
    assert normalized.nickname == ""


def test_shared_matcher_uses_adapter_normalization_and_preserves_mpn_tier() -> None:
    part = _part()
    index = library_match_records([part], tool="altium")
    placement = {
        "ref": "R1",
        "lib_id": "altium:RES",
        "props": {"Reference": "R1", "MPN": part.mpn},
    }

    matched = match_component(placement, index)

    assert matched["confidence"] == "mpn"
    assert matched["part"]["id"] == part.id
