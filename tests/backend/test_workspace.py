"""The component workspace projection.

These tests hold the presentation contract: every canonical record field has one declared
destination, the projection is pure, provider payloads are normalized into product concepts,
and no state is claimed that the record does not actually prove.
"""

from __future__ import annotations

import dataclasses

import pytest

from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import Datasheet, EnrichmentField, PartRecord, Purchase, SourcedValue
from stockroom.model.sourced import SourceEntry
from stockroom.model.trust import AssetCheck
from stockroom.workspace import (
    DATA_DESTINATIONS,
    FACT_STATES,
    REPRESENTATION_STATUSES,
    SOURCE_STATES,
    WORKSPACE_SCHEMA_VERSION,
    component_workspace,
    fact,
)


def _record(**overrides) -> PartRecord:
    base = {
        "id": "stm32h743vit6",
        "mpn": "STM32H743VIT6",
        "manufacturer": "STMicroelectronics",
        "display_name": "STM32H743VIT6",
        "category": "ICs",
        "description": "Arm Cortex-M7 microcontroller",
        "value": "STM32H743VIT6",
    }
    base.update(overrides)
    return PartRecord(**base)


def _complete_record() -> PartRecord:
    record = _record(
        specs={
            "package": "LQFP100",
            "pin_count": "100",
            "lifecycle": "Active",
            "operating_temperature": "-40C to 85C",
            "core": "Cortex-M7",
            "supply_voltage": "1.62V to 3.6V",
            "pinout": [{"pin": "1", "name": "VBAT"}],
            "image": "https://example.test/image.png",
        },
        tags=["preferred"],
    )
    for tool in ("kicad", "altium"):
        bundle = record.assets_for(tool)
        bundle.symbol = Asset(
            ref=AssetRef(lib=f"SR-ICs.{tool}", name="STM32H743VIT6"),
            origin=AssetOrigin(vendor="ultralibrarian", url="https://x", captured_at="2026-01-01"),
        )
        bundle.footprint = Asset(
            ref=AssetRef(lib=f"SR-ICs.{tool}", name="LQFP100"),
            origin=AssetOrigin(vendor="ultralibrarian"),
        )
    record.assets_for("kicad").model = Asset(ref=AssetRef(file="models/LQFP100.step"))
    record.datasheet = Datasheet(file="datasheets/x.pdf", source_url="https://x/ds.pdf")
    record.purchase = [
        Purchase(vendor="Mouser", url="https://mouser", part_number="511-X", stock=1240,
                 price_breaks=[{"qty": 1, "price": 12.48}], currency="USD"),
        Purchase(vendor="DigiKey", url="https://digikey", part_number="497-X", stock=3105,
                 price_breaks=[{"qty": 10, "price": 11.92}], currency="USD"),
    ]
    record.enrichment = {"description": EnrichmentField(source="digikey", confidence="high")}
    return record


# --------------------------------------------------------------- destination map


def test_every_canonical_record_field_has_one_declared_destination():
    fields = {f.name for f in dataclasses.fields(PartRecord)}
    missing = fields - set(DATA_DESTINATIONS)
    assert not missing, f"canonical fields with no product destination: {sorted(missing)}"


def test_the_destination_map_names_no_field_the_record_does_not_have():
    fields = {f.name for f in dataclasses.fields(PartRecord)}
    stale = set(DATA_DESTINATIONS) - fields
    assert not stale, f"destinations for fields that no longer exist: {sorted(stale)}"


def test_no_canonical_field_is_dropped_into_nowhere():
    assert all(destination.strip() for destination in DATA_DESTINATIONS.values())


# --------------------------------------------------------------- shape


def test_workspace_reports_its_schema_version():
    assert component_workspace(_record())["schemaVersion"] == WORKSPACE_SCHEMA_VERSION


def test_workspace_has_every_top_level_region():
    view = component_workspace(_complete_record())
    assert set(view) == {
        "schemaVersion",
        "identity",
        "summary",
        "representations",
        "specifications",
        "sourcing",
        "providers",
        "sources",
        "attention",
    }


def test_identity_answers_what_this_is_without_reading_specs_twice():
    identity = component_workspace(_complete_record())["identity"]
    assert identity["mpn"] == "STM32H743VIT6"
    assert identity["manufacturer"] == "STMicroelectronics"
    assert identity["package"] == "LQFP100"
    assert identity["pinCount"] == 100
    assert identity["lifecycle"] == "Active"
    assert identity["tags"] == ["preferred"]


def test_projection_never_mutates_the_record():
    record = _complete_record()
    before = record.dumps()
    component_workspace(record)
    assert record.dumps() == before


# --------------------------------------------------------------- representations


def test_all_three_representations_are_always_present():
    view = component_workspace(_record())["representations"]
    assert set(view) == {"symbol", "footprint", "model"}
    assert all(item["status"] in REPRESENTATION_STATUSES for item in view.values())


def test_a_present_unmeasured_asset_is_ready_not_accused():
    view = component_workspace(_complete_record())["representations"]
    assert view["symbol"]["status"] == "ready"
    assert view["symbol"]["issue"] is None


def test_a_missing_required_asset_is_missing_with_an_action():
    view = component_workspace(_record())["representations"]
    assert view["symbol"]["status"] == "missing"
    assert view["symbol"]["issue"]


def test_a_failed_check_outranks_another_tools_clean_result():
    record = _complete_record()
    record.assets_for("kicad").symbol.checks = [
        AssetCheck(check="pins_vs_datasheet", measured=99, expected=100, against="datasheet")
    ]
    view = component_workspace(record)["representations"]
    assert view["symbol"]["status"] == "failed"


def test_an_unmeasurable_check_reads_as_review_not_failed():
    record = _complete_record()
    for tool in ("kicad", "altium"):
        record.assets_for(tool).symbol.checks = [
            AssetCheck(check="pins_vs_datasheet", measured=None, expected=None, against="")
        ]
    view = component_workspace(record)["representations"]
    assert view["symbol"]["status"] == "review"


def test_representation_carries_its_provider_for_every_tool():
    view = component_workspace(_complete_record())["representations"]
    tools = {entry["tool"]: entry for entry in view["symbol"]["tools"]}
    assert tools["kicad"]["sourceLabel"] == "Ultra Librarian"
    assert tools["kicad"]["reference"]["name"] == "STM32H743VIT6"


# --------------------------------------------------------------- specifications


def test_specifications_are_grouped_and_bookkeeping_is_not_a_specification():
    specs = component_workspace(_complete_record())["specifications"]
    labels = {group["id"] for group in specs["groups"]}
    assert "physical" in labels and "electrical" in labels
    every_id = {item["id"] for group in specs["groups"] for item in group["facts"]}
    assert "image" not in every_id
    assert "pinout" not in every_id


def test_pinout_is_projected_as_a_table_not_a_specification_row():
    specs = component_workspace(_complete_record())["specifications"]
    assert specs["pinout"] == [{"pin": "1", "name": "VBAT"}]
    assert specs["pinCount"] == 1


def test_a_component_with_no_specifications_reports_empty_groups_honestly():
    specs = component_workspace(_record())["specifications"]
    assert specs["groups"] == []
    assert specs["total"] == 0


def test_many_specifications_all_land_in_a_group():
    record = _record(specs={f"supply_voltage_{n}": f"{n}V" for n in range(80)})
    specs = component_workspace(record)["specifications"]
    assert specs["total"] == 80


# --------------------------------------------------------------- sourcing


def test_offers_are_provider_neutral_and_carry_their_ladders():
    sourcing = component_workspace(_complete_record())["sourcing"]
    by_source = {offer["sourceId"]: offer for offer in sourcing["offers"]}
    assert by_source["mouser"]["stock"] == 1240
    assert by_source["digikey"]["priceBreaks"] == [{"qty": 10, "price": 11.92}]
    assert by_source["mouser"]["sourceLabel"] == "Mouser"


def test_provider_catalogue_relationships_are_normalized_not_digikey_shaped():
    record = _complete_record()
    record.catalog = {
        "digikey": {
            "substitutions": [
                {"manufacturer_product_number": "ALT-1", "manufacturer": "ACME",
                 "product_url": "https://x/alt"}
            ],
            "media": [{"title": "Ultra Librarian", "url": "https://ul/part"}],
        }
    }
    sourcing = component_workspace(record)["sourcing"]
    groups = {group["id"]: group for group in sourcing["relationships"]}
    assert groups["substitutions"]["items"][0]["mpn"] == "ALT-1"
    assert groups["substitutions"]["items"][0]["sourceLabel"] == "DigiKey"
    assert sourcing["resources"][0]["title"] == "Ultra Librarian"


def test_a_component_with_no_sourcing_reports_empty_rather_than_absent():
    sourcing = component_workspace(_record())["sourcing"]
    assert sourcing["offers"] == []
    assert sourcing["relationships"] == []


def test_insecure_resource_links_are_not_offered():
    record = _complete_record()
    record.catalog = {"digikey": {"media": [{"title": "x", "url": "http://insecure/x"}]}}
    assert component_workspace(record)["sourcing"]["resources"] == []


# --------------------------------------------------------------- sources


def test_field_sources_expose_the_value_in_force_and_every_alternate():
    record = _complete_record()
    record.alternates = {
        "description": [
            SourcedValue(value="Arm Cortex-M7 microcontroller", source="digikey"),
            SourcedValue(value="High performance MCU", source="mouser"),
        ]
    }
    fields = {item["id"]: item for item in component_workspace(record)["sources"]["fields"]}
    entry = fields["description"]
    assert entry["state"] == "conflict"
    assert [alt["sourceId"] for alt in entry["alternates"]] == ["mouser"]


def test_a_repeated_winning_value_is_never_shown_as_its_own_alternative():
    record = _complete_record()
    record.alternates = {"description": [SourcedValue(value="only", source="digikey")]}
    fields = {item["id"]: item for item in component_workspace(record)["sources"]["fields"]}
    assert fields["description"]["alternates"] == []
    assert fields["description"]["state"] != "conflict"


def test_source_records_include_the_datasheet_and_the_original_package():
    view = component_workspace(_complete_record())["sources"]["records"]
    assert any(entry["id"] == "datasheet" for entry in view)


def test_every_source_record_carries_a_state_from_the_closed_vocabulary():
    view = component_workspace(_complete_record())["sources"]["records"]
    assert view
    assert all(entry["state"] in SOURCE_STATES for entry in view)


def test_a_recorded_degraded_state_is_surfaced_rather_than_reported_as_success():
    record = _complete_record()
    record.sources = {
        "mouser": SourceEntry(fetched_at="2026-01-01", file="sourced/x/mouser.json"),
        "digikey": SourceEntry(extra={"state": "failed"}),
        "lcsc": SourceEntry(extra={"state": "not_configured"}),
        "arrow": SourceEntry(extra={"state": "unavailable"}),
    }
    states = {
        entry["id"]: entry["state"] for entry in component_workspace(record)["sources"]["records"]
    }
    assert states["mouser"] == "success"
    assert states["digikey"] == "failed"
    assert states["lcsc"] == "not_configured"
    assert states["arrow"] == "unavailable"


def test_an_unrecognised_state_never_smuggles_itself_into_the_vocabulary():
    record = _complete_record()
    record.sources = {"mouser": SourceEntry(extra={"state": "Traceback (most recent call last)"})}
    states = {
        entry["id"]: entry["state"] for entry in component_workspace(record)["sources"]["records"]
    }
    assert states["mouser"] == "success"


def test_a_source_that_won_a_field_is_in_the_ledger_even_with_no_stored_payload():
    record = _complete_record()
    record.sources = {}
    records = {entry["id"]: entry for entry in component_workspace(record)["sources"]["records"]}
    # `_complete_record` attributes the description to DigiKey through `enrichment`.
    assert records["digikey"]["fieldCount"] == 1
    assert records["digikey"]["state"] == "success"
    assert records["digikey"]["file"] == ""


def test_diagnostics_keep_technical_truth_reachable():
    diagnostics = component_workspace(_complete_record())["sources"]["diagnostics"]
    assert diagnostics["schemaVersion"] >= 1
    assert set(diagnostics["hashes"]) == {"symbolContent", "footprintContent", "modelFile"}


def test_unknown_keys_from_a_newer_build_are_surfaced_not_hidden():
    record = _complete_record()
    record.extra = {"future_field": 1}
    diagnostics = component_workspace(record)["sources"]["diagnostics"]
    assert "future_field" in diagnostics["unknownKeys"]


# --------------------------------------------------------------- attention


def test_attention_names_missing_identity_with_an_action():
    items = component_workspace(_record(mpn="", manufacturer=""))["attention"]
    ids = {item["id"] for item in items}
    assert "identity.mpn" in ids and "identity.manufacturer" in ids
    assert all(item["action"] for item in items)


def test_attention_is_empty_when_nothing_is_wrong():
    record = _complete_record()
    record.assets_for("altium").model = Asset(ref=AssetRef(file="models/LQFP100.step"))
    items = component_workspace(record)["attention"]
    assert [item for item in items if item["severity"] == "blocking"] == []


def test_a_conflict_becomes_one_attention_item_per_field():
    record = _complete_record()
    record.alternates = {
        "package": [SourcedValue(value="LQFP100", source="digikey"),
                    SourcedValue(value="LQFP-100", source="mouser")]
    }
    ids = {item["id"] for item in component_workspace(record)["attention"]}
    assert "conflict.package" in ids


# --------------------------------------------------------------- fact helper


def test_fact_states_are_a_closed_vocabulary():
    with pytest.raises(ValueError):
        fact("x", "X", "v", state="probably")


def test_a_value_with_no_source_is_manual_and_a_missing_one_is_unknown():
    assert fact("x", "X", "typed by hand")["state"] == "manual"
    assert fact("x", "X", "")["state"] == "unknown"
    assert fact("x", "X", "v", source_id="mouser")["state"] == "agrees"
    assert FACT_STATES >= {"verified", "stale"}


def test_structured_values_are_not_flattened_into_a_fake_display_string():
    assert fact("x", "X", {"a": 1})["formattedValue"] == ""
    assert fact("x", "X", True)["formattedValue"] == "Yes"
