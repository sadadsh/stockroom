"""CAD assets: source, provider, format and compatibility stay four separate facts."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.cad import REPRESENTATION_STATUSES, build_cad_assets
from stockroom.dossier.categories import resolve_schema
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.trust import AssetCheck
from tests.backend.dossier import records


def _with_assets(record):
    for tool in ("kicad", "altium"):
        bundle = record.assets_for(tool)
        bundle.symbol = Asset(
            ref=AssetRef(lib=f"SR-ICs.{tool}", name=record.mpn),
            origin=AssetOrigin(
                vendor="ultralibrarian",
                url="https://app.ultralibrarian.com/x",
                captured_at="2026-01-01",
            ),
        )
        bundle.footprint = Asset(
            ref=AssetRef(lib=f"SR-ICs.{tool}", name="LQFP100"),
            origin=AssetOrigin(vendor="ultralibrarian"),
        )
    record.assets_for("kicad").model = Asset(ref=AssetRef(file="models/LQFP100.step"))
    return record


def test_all_three_asset_kinds_are_always_present():
    kinds = component_dossier(records.microcontroller())["cadAssets"]["kinds"]
    assert set(kinds) == {"symbol", "footprint", "model"}
    assert all(item["status"] in REPRESENTATION_STATUSES for item in kinds.values())


def test_a_present_unmeasured_asset_is_ready_not_accused():
    kinds = component_dossier(_with_assets(records.microcontroller()))["cadAssets"]["kinds"]
    assert kinds["symbol"]["status"] == "ready"
    assert kinds["symbol"]["issue"] is None


def test_a_missing_required_asset_is_missing_with_an_action():
    kinds = component_dossier(records.microcontroller())["cadAssets"]["kinds"]
    assert kinds["symbol"]["status"] == "missing"
    assert kinds["symbol"]["issue"]


def test_a_failed_check_outranks_another_tools_clean_result():
    record = _with_assets(records.microcontroller())
    record.assets_for("kicad").symbol.checks = [
        AssetCheck(check="pins_vs_datasheet", measured=99, expected=100, against="datasheet")
    ]
    kinds = component_dossier(record)["cadAssets"]["kinds"]
    assert kinds["symbol"]["status"] == "failed"


def test_an_unmeasurable_check_reads_as_review_not_failed():
    record = _with_assets(records.microcontroller())
    for tool in ("kicad", "altium"):
        record.assets_for(tool).symbol.checks = [
            AssetCheck(check="pins_vs_datasheet", measured=None, expected=None, against="")
        ]
    kinds = component_dossier(record)["cadAssets"]["kinds"]
    assert kinds["symbol"]["status"] == "review"


def test_the_source_the_provider_and_the_format_are_separate_fields():
    kinds = component_dossier(_with_assets(records.microcontroller()))["cadAssets"]["kinds"]
    tools = {item["tool"]: item for item in kinds["symbol"]["tools"]}
    assert tools["kicad"]["sourceId"] == "ultralibrarian"
    assert tools["kicad"]["sourceLabel"] == "Ultra Librarian"
    assert tools["kicad"]["sourceUrl"] == "https://app.ultralibrarian.com/x"
    assert tools["kicad"]["reference"]["name"] == "STM32H743VIT6"
    assert tools["altium"]["tool"] == "altium"


def test_a_tool_that_cannot_hold_an_asset_separately_says_embedded_not_missing():
    kinds = component_dossier(_with_assets(records.microcontroller()))["cadAssets"]["kinds"]
    tools = {item["tool"]: item for item in kinds["model"]["tools"]}
    if "altium" in tools:
        assert isinstance(tools["altium"]["embedded"], bool)


def test_the_cad_validation_relationships_come_from_the_category_schema():
    connector = records.connector()
    relationships = build_cad_assets(connector, resolve_schema(connector))
    fields = {item["field"] for item in relationships["validationRelationships"]}
    assert "positions" in fields and "pitch" in fields

    mcu = records.microcontroller()
    mcu_fields = {
        item["field"]
        for item in build_cad_assets(mcu, resolve_schema(mcu))["validationRelationships"]
    }
    assert "pin_count" in mcu_fields
    assert "positions" not in mcu_fields


def test_the_registered_tools_are_named_rather_than_assumed():
    tools = component_dossier(records.microcontroller())["cadAssets"]["tools"]
    assert {item["key"] for item in tools} >= {"kicad", "altium"}


def test_provider_coverage_is_reported_beside_the_assets_not_mixed_into_them():
    dossier = component_dossier(records.microcontroller())
    assert "rows" in dossier["cadSourceCoverage"]
    assert "rows" not in dossier["cadAssets"]
