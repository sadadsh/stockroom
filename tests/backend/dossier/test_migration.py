"""The v5 migration: safe, idempotent, non-destructive, and reversible by construction.

v5 adds typed documents, the separated manufacturer page, and reviewed overrides. It moves
nothing and deletes nothing, which is what makes it reversible without a down-migration: a v5
record with none of the three new fields IS a v4 record apart from its version stamp.
"""

from __future__ import annotations

import json

import pytest

from stockroom.dossier import component_dossier
from stockroom.model.part import (
    SCHEMA_VERSION,
    FieldOverride,
    ManufacturerPage,
    PartDocument,
    PartRecord,
    UnmigratableRecord,
    migrate_record,
)

_V4 = {
    "schema_version": 4,
    "id": "erj-p03f1101v-0001",
    "mpn": "ERJ-P03F1101V",
    "manufacturer": "Panasonic",
    "part_class": "passive",
    "derived": {
        "display_name": "ERJ-P03F1101V",
        "category": "Resistors",
        "description": "RES 1.1K OHM 1% 1/5W 0603",
        "specs": {"Resistance": "1.1 kOhms", "Tolerance": "1%"},
    },
    "sources": {"mouser": {"fetched_at": "2026-01-01", "file": "sourced/x/mouser.json"}},
    "assets": {"kicad": {"symbol": {"ref": {"lib": "SR-Resistors", "name": "R", "file": ""}}}},
    "tags": ["preferred"],
    "datasheet": {"file": "", "source_url": "https://industrial.panasonic.com/ds.pdf",
                  "fetched_at": "2026-01-01"},
    "purchase": [{"vendor": "Mouser", "url": "https://www.mouser.com/x", "part_number": "667-ERJ",
                  "price_breaks": [], "stock": 10, "currency": "USD", "fetched_at": "2026-01-01"}],
    "provenance": None,
    "hashes": None,
    "enrichment": {},
    "future_field_from_a_newer_peer": {"kept": True},
}


def test_the_schema_version_is_five():
    assert SCHEMA_VERSION == 5


def test_a_v4_record_migrates_without_mutating_its_input():
    source = json.loads(json.dumps(_V4))
    migrated = migrate_record(source)
    assert source["schema_version"] == 4, "migration mutated its input"
    assert migrated["schema_version"] == 5


def test_the_migration_is_idempotent():
    once = migrate_record(json.loads(json.dumps(_V4)))
    twice = migrate_record(once)
    assert once == twice


def test_the_migration_deletes_nothing_the_record_already_held():
    migrated = migrate_record(json.loads(json.dumps(_V4)))
    for key, value in _V4.items():
        if key == "schema_version":
            continue
        assert migrated[key] == value, f"migration changed {key}"


def test_the_manufacturer_page_is_never_seeded_from_a_purchase_url():
    migrated = migrate_record(json.loads(json.dumps(_V4)))
    assert "manufacturer_page" not in migrated
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    assert record.manufacturer_page is None
    assert component_dossier(record)["identity"]["manufacturerPage"]["url"] == ""


def test_a_migrated_record_round_trips_and_gains_no_empty_scaffolding():
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    blob = json.loads(record.dumps())
    assert blob["schema_version"] == 5
    for added in ("documents", "manufacturer_page", "overrides"):
        assert added not in blob, f"{added} was written onto a record that does not use it"


def test_a_field_a_newer_peer_wrote_survives_the_migration():
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    assert json.loads(record.dumps())["future_field_from_a_newer_peer"] == {"kept": True}


def test_a_v1_record_still_climbs_all_the_way_to_the_current_shape():
    v1 = {
        "id": "old-0001",
        "mpn": "OLD",
        "manufacturer": "ACME",
        "display_name": "OLD",
        "category": "Resistors",
        "symbol": {"lib": "SR-Resistors", "name": "R"},
        "passive": True,
    }
    record = PartRecord.from_dict(v1)
    assert record.schema_version == SCHEMA_VERSION
    assert record.assets_for("kicad").symbol.ref.name == "R"


def test_a_legacy_record_projects_into_the_new_shape():
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    dossier = component_dossier(record)
    assert dossier["identity"]["categorySchema"]["key"] == "resistor"
    keys = {item["key"] for item in dossier["keySpecifications"]}
    assert "resistance" in keys
    assert dossier["documents"]["hasDatasheet"] is True
    assert dossier["distributorOffers"][0]["provider"] == "mouser"


def test_a_version_with_no_migration_step_is_refused_rather_than_relabelled():
    with pytest.raises(UnmigratableRecord):
        migrate_record({"id": "x-0000", "schema_version": 0})


def test_a_record_from_the_future_keeps_its_own_stamp():
    future = dict(_V4, schema_version=SCHEMA_VERSION + 7)
    record = PartRecord.from_dict(json.loads(json.dumps(future)))
    assert record.schema_version == SCHEMA_VERSION + 7
    assert record.is_future_schema()


def test_the_new_fields_round_trip_when_a_record_actually_uses_them():
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    record.documents = [
        PartDocument(
            document_type="package_drawing",
            title="Outline",
            remote_url="https://industrial.panasonic.com/drawing.pdf",
            source_type="manufacturer",
        )
    ]
    record.manufacturer_page = ManufacturerPage(
        url="https://industrial.panasonic.com/erj", source="user"
    )
    record.overrides = {"resistance": FieldOverride(value="1.1 kOhms", reviewed_by="owner")}
    reloaded = PartRecord.loads(record.dumps())
    assert reloaded.documents[0].title == "Outline"
    assert reloaded.manufacturer_page.url == "https://industrial.panasonic.com/erj"
    assert reloaded.overrides["resistance"].reviewed_by == "owner"


def test_a_newer_builds_keys_inside_the_new_blocks_are_kept_verbatim():
    record = PartRecord.from_dict(json.loads(json.dumps(_V4)))
    record.documents = [PartDocument.from_dict({"title": "X", "future": 7})]
    reloaded = PartRecord.loads(record.dumps())
    assert reloaded.documents[0].extra == {"future": 7}
    assert json.loads(reloaded.dumps())["documents"][0]["future"] == 7
