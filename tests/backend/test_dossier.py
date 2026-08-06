"""The component dossier projection.

These tests hold the presentation contract: every canonical record field has one declared
destination, the projection is pure, provider payloads are normalized into product concepts, and
no state is claimed that the record does not actually prove.

The focused behaviour - category schemas, specification states, precedence, documents, the
manufacturer page, offers, related parts, raw levels, revisions and migration - lives beside its
own module under `tests/backend/dossier/`.
"""

from __future__ import annotations

import dataclasses

from stockroom.dossier import component_dossier
from stockroom.model.part import (
    Datasheet,
    EnrichmentField,
    PartRecord,
    Purchase,
    SourcedValue,
)
from stockroom.model.sourced import SourceEntry
from stockroom.workspace import (
    DATA_DESTINATIONS,
    REPRESENTATION_STATUSES,
    SOURCE_STATES,
    WORKSPACE_SCHEMA_VERSION,
    component_workspace,
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
            "Package / Case": "LQFP100",
            "Number of Pins": "100",
            "lifecycle": "Active",
            "Operating Temperature": "-40C to 85C",
            "Core Processor": "ARM Cortex-M7",
            "Voltage - Supply": "1.62V ~ 3.6V",
            "pinout": [{"pin": "1", "name": "VBAT"}],
            "Image": "https://example.test/image.png",
        },
        tags=["preferred"],
    )
    record.datasheet = Datasheet(file="datasheets/x.pdf", source_url="https://www.st.com/ds.pdf")
    record.purchase = [
        Purchase(vendor="Mouser", url="https://www.mouser.com/x", part_number="511-X",
                 stock=1240, price_breaks=[{"qty": 1, "price": 12.48}], currency="USD"),
        Purchase(vendor="DigiKey", url="https://www.digikey.com/x", part_number="497-X",
                 stock=3105, price_breaks=[{"qty": 10, "price": 11.92}], currency="USD"),
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


def test_every_destination_names_a_region_the_dossier_actually_serves():
    served = set(component_dossier(_complete_record()))
    for field_name, destination in DATA_DESTINATIONS.items():
        region = destination.split(".", 1)[0]
        assert region in served, f"{field_name} is destined for a region nothing serves"


# --------------------------------------------------------------- shape


def test_the_dossier_reports_its_schema_version():
    assert component_dossier(_record())["schemaVersion"] == WORKSPACE_SCHEMA_VERSION


def test_the_dossier_has_every_top_level_region():
    assert set(component_dossier(_complete_record())) == {
        "schemaVersion",
        "identity",
        "qualitySummary",
        "keySpecifications",
        "specificationGroups",
        "cadAssets",
        "cadSourceCoverage",
        "supplySummary",
        "distributorOffers",
        "documents",
        "relatedParts",
        "provenance",
        "revisions",
        "diagnostics",
    }


def test_the_historical_name_serves_the_same_document_not_a_second_projection():
    record = _complete_record()
    assert component_workspace(record) == component_dossier(record)


def test_identity_answers_what_this_is_without_reading_specs_twice():
    identity = component_dossier(_complete_record())["identity"]
    assert identity["mpn"] == "STM32H743VIT6"
    assert identity["manufacturer"] == "STMicroelectronics"
    assert identity["package"] == "LQFP100"
    assert identity["pinCount"] == 100
    assert identity["lifecycle"] == "Active"
    assert identity["tags"] == ["preferred"]
    assert identity["categorySchema"]["key"] == "microcontroller"


def test_the_projection_never_mutates_the_record():
    record = _complete_record()
    before = record.dumps()
    component_dossier(record)
    assert record.dumps() == before


def test_the_projection_is_deterministic():
    record = _complete_record()
    assert component_dossier(record) == component_dossier(record)


def test_the_storage_shape_never_leaks_into_the_product_shape():
    body = component_dossier(_complete_record())
    assert "schema_version" not in body
    assert "assets" not in body
    assert "specs" not in body


# --------------------------------------------------------------- cad assets


def test_all_three_representations_are_always_present():
    kinds = component_dossier(_record())["cadAssets"]["kinds"]
    assert set(kinds) == {"symbol", "footprint", "model"}
    assert all(item["status"] in REPRESENTATION_STATUSES for item in kinds.values())


# --------------------------------------------------------------- specifications


def test_bookkeeping_is_not_a_specification():
    dossier = component_dossier(_complete_record())
    every_key = {item["key"] for item in dossier["keySpecifications"]} | {
        item["key"] for group in dossier["specificationGroups"] for item in group["specifications"]
    }
    assert "image" not in every_key
    assert "pinout" not in every_key


def test_a_pinout_is_projected_as_a_table_not_a_specification_row():
    diagnostics = component_dossier(_complete_record())["diagnostics"]
    assert diagnostics["pinout"] == [{"pin": "1", "name": "VBAT"}]
    assert diagnostics["pinCount"] == 1


def test_many_specifications_all_land_in_a_group():
    record = _record(specs={f"Vendor Parameter {n}": f"{n}V" for n in range(80)})
    dossier = component_dossier(record)
    listed = {
        item["key"] for group in dossier["specificationGroups"] for item in group["specifications"]
    }
    assert len([key for key in listed if key.startswith("vendor_parameter")]) == 80


# --------------------------------------------------------------- sourcing


def test_offers_are_provider_neutral_and_carry_their_ladders():
    offers = {item["provider"]: item for item in component_dossier(_complete_record())[
        "distributorOffers"
    ]}
    assert offers["mouser"]["stock"] == 1240
    assert offers["digikey"]["priceBreaks"] == [{"qty": 10, "price": 11.92}]
    assert offers["mouser"]["providerLabel"] == "Mouser"


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
    dossier = component_dossier(record)
    related = dossier["relatedParts"][0]
    assert related["mpn"] == "ALT-1"
    assert related["providerLabel"] == "DigiKey"
    assert related["reason"]
    assert any(item["title"] == "Ultra Librarian" for item in dossier["documents"]["items"])


def test_a_component_with_no_sourcing_reports_empty_rather_than_absent():
    dossier = component_dossier(_record())
    assert dossier["distributorOffers"] == []
    assert dossier["relatedParts"] == []


def test_insecure_resource_links_are_not_offered():
    record = _complete_record()
    record.catalog = {"digikey": {"media": [{"title": "x", "url": "http://insecure/x"}]}}
    urls = {item["remoteUrl"] for item in component_dossier(record)["documents"]["items"]}
    assert "http://insecure/x" not in urls


# --------------------------------------------------------------- provenance


def test_field_sources_expose_the_value_in_force_and_every_alternate():
    record = _complete_record()
    record.alternates = {
        "Core Processor": [
            SourcedValue(value="ARM Cortex-M7", source="digikey"),
            SourcedValue(value="Cortex-M7F", source="mouser"),
        ]
    }
    dossier = component_dossier(record)
    core = next(item for item in dossier["keySpecifications"] if item["key"] == "core_processor")
    assert core["conflictState"] == "conflicting"
    assert {entry["sourceId"] for entry in core["sourceCandidates"]} == {"digikey", "mouser"}


def test_a_repeated_winning_value_is_never_shown_as_its_own_alternative():
    record = _complete_record()
    record.alternates = {"Core Processor": [SourcedValue(value="ARM Cortex-M7", source="digikey")]}
    core = next(
        item
        for item in component_dossier(record)["keySpecifications"]
        if item["key"] == "core_processor"
    )
    assert len(core["sourceCandidates"]) == 1
    assert core["conflictState"] == "none"


def test_a_disagreement_about_a_record_field_is_never_settled_in_silence():
    record = _complete_record()
    record.alternates = {
        "description": [
            SourcedValue(value="Arm Cortex-M7 microcontroller", source="digikey"),
            SourcedValue(value="High performance MCU", source="mouser"),
        ]
    }
    fields = {
        item["key"]: item for item in component_dossier(record)["provenance"]["recordFields"]
    }
    assert fields["description"]["conflictState"] == "conflicting"
    assert {entry["sourceId"] for entry in fields["description"]["sourceCandidates"]} == {
        "digikey",
        "mouser",
    }


def test_a_record_field_already_shown_as_a_specification_is_not_repeated():
    record = _complete_record()
    record.enrichment = {"Package / Case": EnrichmentField(source="digikey")}
    keys = {item["key"] for item in component_dossier(record)["provenance"]["recordFields"]}
    assert "package" not in keys


def test_source_records_include_the_datasheet_and_the_original_package():
    dossier = component_dossier(_complete_record())
    assert dossier["documents"]["hasDatasheet"] is True


def test_every_source_record_carries_a_state_from_the_closed_vocabulary():
    record = _complete_record()
    record.sources = {"mouser": SourceEntry(fetched_at="2026-01-01", file="sourced/x/mouser.json")}
    ledger = component_dossier(record)["provenance"]["sources"]
    assert ledger
    assert all(entry["state"] in SOURCE_STATES for entry in ledger)


def test_a_recorded_degraded_state_is_surfaced_rather_than_reported_as_success():
    record = _complete_record()
    record.sources = {
        "mouser": SourceEntry(fetched_at="2026-01-01", file="sourced/x/mouser.json"),
        "digikey": SourceEntry(extra={"state": "failed"}),
        "lcsc": SourceEntry(extra={"state": "not_configured"}),
        "arrow": SourceEntry(extra={"state": "unavailable"}),
    }
    states = {
        entry["id"]: entry["state"] for entry in component_dossier(record)["provenance"]["sources"]
    }
    assert states["mouser"] == "success"
    assert states["digikey"] == "failed"
    assert states["lcsc"] == "not_configured"
    assert states["arrow"] == "unavailable"


def test_an_unrecognised_state_never_smuggles_itself_into_the_vocabulary():
    record = _complete_record()
    record.sources = {"mouser": SourceEntry(extra={"state": "Traceback (most recent call last)"})}
    states = {
        entry["id"]: entry["state"] for entry in component_dossier(record)["provenance"]["sources"]
    }
    assert states["mouser"] == "success"


def test_a_source_that_won_a_field_is_in_the_ledger_even_with_no_stored_payload():
    record = _complete_record()
    record.sources = {}
    record.enrichment = {"Core Processor": EnrichmentField(source="digikey", confidence="high")}
    ledger = {entry["id"]: entry for entry in component_dossier(record)["provenance"]["sources"]}
    assert ledger["digikey"]["fieldCount"] >= 1
    assert ledger["digikey"]["state"] == "success"
    assert ledger["digikey"]["payloadRef"] == ""


def test_diagnostics_keep_technical_truth_reachable():
    diagnostics = component_dossier(_complete_record())["diagnostics"]
    assert diagnostics["recordSchemaVersion"] >= 1
    assert set(diagnostics["hashes"]) == {"symbolContent", "footprintContent", "modelFile"}


def test_unknown_keys_from_a_newer_build_are_surfaced_not_hidden():
    record = _complete_record()
    record.extra = {"future_field": 1}
    assert "future_field" in component_dossier(record)["diagnostics"]["unknownKeys"]


# --------------------------------------------------------------- attention


def test_attention_names_missing_identity_with_an_action():
    items = component_dossier(_record(mpn="", manufacturer=""))["qualitySummary"]["attention"]
    ids = {item["id"] for item in items}
    assert "identity.mpn" in ids and "identity.manufacturer" in ids
    assert all(item["action"] for item in items)


def test_a_conflict_becomes_one_attention_item_per_field():
    record = _complete_record()
    record.alternates = {
        "Package / Case": [
            SourcedValue(value="LQFP100", source="digikey"),
            SourcedValue(value="LQFP-100", source="mouser"),
        ]
    }
    ids = {item["id"] for item in component_dossier(record)["qualitySummary"]["attention"]}
    assert "specification.conflict.package" in ids


def test_a_category_expected_gap_is_actionable_rather_than_invisible():
    ids = {
        item["id"]
        for item in component_dossier(_record())["qualitySummary"]["attention"]
    }
    assert "specification.missing.program_memory_size" in ids


def test_the_passport_gate_is_reported_beside_the_category_completeness_not_as_it():
    summary = component_dossier(_record())["qualitySummary"]
    assert "datasheet" in summary["missingPassportFields"]
    assert summary["completeness"]["basis"] == "microcontroller"
