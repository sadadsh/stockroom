"""PartRecord v4 keeps one coherent CAD bundle per tool separate from EDA projections."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from stockroom.model.asset import AssetRef
from stockroom.model.cad_variant import (
    CAD_VARIANT_ROLE_MAP,
    CadVariantArtifactPointer,
    CadVariantPointer,
    CadVariantSelections,
)
from stockroom.model.part import SCHEMA_VERSION, PartRecord, migrate_record


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _pointer(
    character: str,
    *,
    tool: str = "kicad",
    provider: str = "ultralibrarian",
    **extra,
) -> CadVariantPointer:
    hexadecimal = "0123456789abcdef"
    start = hexadecimal.index(character)
    artifacts = {
        asset_kind: CadVariantArtifactPointer(
            artifact_digest=_digest(hexadecimal[(start + index + 1) % len(hexadecimal)]),
            evidence_role=evidence_role,
        )
        for index, (asset_kind, evidence_role) in enumerate(CAD_VARIANT_ROLE_MAP[tool].items())
    }
    return CadVariantPointer(
        manifest_digest=_digest(character),
        provider=provider,
        artifacts=artifacts,
        extra=extra,
    )


def _record() -> PartRecord:
    return PartRecord(
        id="s1m-0000",
        mpn="S1M",
        manufacturer="ON Semiconductor",
        display_name="S1M",
        category="Diodes",
    )


def test_v3_migrates_to_v4_without_inventing_a_variant_for_an_existing_asset() -> None:
    source = {
        "schema_version": 3,
        "id": "s1m-0000",
        "mpn": "S1M",
        "manufacturer": "ON Semiconductor",
        "part_class": "component",
        "derived": {"display_name": "S1M", "category": "Diodes"},
        "sources": {},
        "assets": {
            "kicad": {
                "symbol": {
                    "ref": {"lib": "SR-Diodes", "name": "S1M", "file": ""},
                }
            }
        },
        "lifecycle": {"status": "active"},
    }

    migrated = migrate_record(source)
    record = PartRecord.from_dict(source)
    output = json.loads(record.dumps())

    assert source["schema_version"] == 3, "migration mutated its input"
    assert migrated["schema_version"] == SCHEMA_VERSION == 4
    assert record.assets_for("kicad").symbol.ref.name == "S1M"
    assert record.cad_variants.is_empty()
    assert "cad_variants" not in output, "migration fabricated an evidence link"
    assert output["lifecycle"] == {"status": "active"}, "unknown v3 data was dropped"


def test_active_bundles_round_trip_per_tool_without_changing_assets() -> None:
    record = _record()
    record.assets_for("kicad").symbol = AssetRef(lib="SR-Diodes", name="S1M")
    record.assets_for("altium").symbol = AssetRef(lib="S1M.SchLib", name="S1M")
    kicad_asset = record.assets_for("kicad").symbol
    altium_asset = record.assets_for("altium").symbol

    record.cad_variants.select("kicad", _pointer("a"))
    record.cad_variants.select(
        "altium",
        _pointer("e", tool="altium", provider="snapmagic"),
    )
    restored = PartRecord.loads(record.dumps())

    assert restored.cad_variants.selection_for("kicad") == _pointer("a")
    assert restored.cad_variants.selection_for("altium") == _pointer(
        "e",
        tool="altium",
        provider="snapmagic",
    )
    assert record.assets_for("kicad").symbol is kicad_asset
    assert record.assets_for("altium").symbol is altium_asset
    assert restored.assets_for("kicad").symbol.ref == kicad_asset.ref
    assert restored.assets_for("altium").symbol.ref == altium_asset.ref


def test_switching_or_clearing_changes_only_the_whole_tool_pointer() -> None:
    selections = CadVariantSelections()
    first = _pointer("a")
    second = _pointer("e", provider="snapmagic")

    selections.select("kicad", first)
    selections.select("kicad", second)

    assert selections.selection_for("kicad") == second
    assert first.manifest_digest == _digest("a")
    assert selections.clear("kicad") == second
    assert selections.is_empty()


def test_a_selection_cannot_mix_independently_chosen_roles() -> None:
    complete = _pointer("a")
    partial = CadVariantPointer(
        manifest_digest=complete.manifest_digest,
        provider=complete.provider,
        artifacts={"symbol": complete.artifacts["symbol"]},
    )
    mismatched = CadVariantPointer(
        manifest_digest=complete.manifest_digest,
        provider=complete.provider,
        artifacts={
            **complete.artifacts,
            "footprint": CadVariantArtifactPointer(
                artifact_digest=_digest("f"),
                evidence_role="altium_footprint",
            ),
        },
    )
    selections = CadVariantSelections()

    with pytest.raises(ValueError, match="bundle roles"):
        selections.select("kicad", partial)
    with pytest.raises(ValueError, match="bundle roles"):
        selections.select("kicad", mismatched)
    assert selections.is_empty()


def test_altium_selection_has_no_independent_step_pointer() -> None:
    altium = _pointer("a", tool="altium")
    assert set(altium.artifacts) == {"symbol", "footprint"}
    assert "model" not in altium.artifacts

    with_model = CadVariantPointer(
        manifest_digest=altium.manifest_digest,
        provider=altium.provider,
        artifacts={
            **altium.artifacts,
            "model": CadVariantArtifactPointer(
                artifact_digest=_digest("f"),
                evidence_role="model",
            ),
        },
    )
    with pytest.raises(ValueError, match="bundle roles"):
        CadVariantSelections().select("altium", with_model)


def test_unknown_future_tool_and_pointer_fields_survive_a_round_trip() -> None:
    record = _record().to_dict()
    record["cad_variants"] = {
        "active": {
            "eagle": {
                "manifest_digest": _digest("a"),
                "provider": "future-provider",
                "artifacts": {
                    "package": {
                        "artifact_digest": _digest("b"),
                        "evidence_role": "package",
                        "quality_rank": 7,
                    }
                },
                "source_manifests": [],
                "selection_policy": "owner",
            }
        },
        "selection_revision": 2,
    }

    restored = json.loads(PartRecord.from_dict(record).dumps())

    pointer = restored["cad_variants"]["active"]["eagle"]
    assert pointer["selection_policy"] == "owner"
    assert pointer["artifacts"]["package"]["quality_rank"] == 7
    assert restored["cad_variants"]["selection_revision"] == 2


def test_pointer_fields_are_canonical_and_the_pointer_is_frozen() -> None:
    pointer = _pointer("a")
    with pytest.raises(FrozenInstanceError):
        pointer.provider = "snapmagic"  # type: ignore[misc]
    with pytest.raises(ValueError, match="manifest digest"):
        CadVariantPointer("not-a-digest", "ultralibrarian", pointer.artifacts)
    with pytest.raises(ValueError, match="provider key"):
        CadVariantPointer(_digest("a"), "Ultra Librarian", pointer.artifacts)


def test_new_selections_refuse_unregistered_tools_but_reads_preserve_them() -> None:
    selections = CadVariantSelections.from_dict(
        {
            "active": {
                "eagle": {
                    "manifest_digest": _digest("a"),
                    "provider": "future-provider",
                    "artifacts": {
                        "package": {
                            "artifact_digest": _digest("b"),
                            "evidence_role": "package",
                        }
                    },
                }
            }
        }
    )
    assert selections.selection_for("eagle") is not None
    with pytest.raises(KeyError):
        selections.select("eagle", _pointer("e"))
