"""Raw data preserved at three levels, and never offered as the normal way to read a part."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.model.part import EnrichmentField, SourcedValue
from stockroom.model.sourced import SourceEntry
from tests.backend.dossier import records


def _raw(record) -> dict:
    return component_dossier(record)["provenance"]["raw"]


def _record() -> object:
    record = records.resistor()
    record.specs["Panasonic Internal Class"] = "Class 9"
    record.enrichment = {
        "Resistance": EnrichmentField(source="mouser", confidence="high"),
        "Panasonic Internal Class": EnrichmentField(source="mouser", confidence="low"),
    }
    record.sources = {
        "mouser": SourceEntry(
            fetched_at="2026-08-01T00:00:00+00:00",
            file="sourced/erj-p03f1101v-0001/mouser.json",
            extra={"endpoint": "https://api.mouser.com/search"},
        )
    }
    return record


def test_the_three_levels_are_all_declared():
    assert [item["id"] for item in _raw(_record())["levels"]] == [
        "canonical",
        "source_fields",
        "evidence",
    ]


def test_level_one_is_the_canonical_normalized_specifications():
    canonical = _raw(_record())["canonical"]
    assert "resistance" in canonical["fields"]
    assert canonical["count"] == len(canonical["fields"])


def test_level_two_keeps_a_source_field_that_maps_to_nothing_canonical():
    source_fields = _raw(_record())["sourceFields"]
    assert source_fields["count"] == 1
    entry = source_fields["items"][0]
    assert entry["sourceKey"] == "Panasonic Internal Class"
    assert entry["value"] == "Class 9"
    assert entry["sourceId"] == "mouser"


def test_level_three_traces_a_value_back_to_the_payload_that_carried_it():
    evidence = {item["field"]: item for item in _raw(_record())["evidence"]["items"]}
    entry = evidence["resistance"]
    assert entry["originalKey"] == "Resistance"
    assert entry["originalValue"] == "1.1 kOhms"
    assert entry["payloadRef"] == "sourced/erj-p03f1101v-0001/mouser.json"
    assert entry["endpoint"] == "https://api.mouser.com/search"
    assert entry["retrievedAt"] == "2026-08-01T00:00:00+00:00"
    assert entry["parserVersion"].startswith("enrich/")
    assert entry["normalizationResult"]["normalizedValue"] == 1100.0


def test_the_payload_is_referenced_and_never_inlined():
    for item in _raw(_record())["evidence"]["items"]:
        assert "payload" not in item
        assert isinstance(item["payloadRef"], str)


def test_a_losing_answer_names_the_answer_it_lost_to():
    record = _record()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
        ]
    }
    rows = [
        item
        for item in _raw(record)["evidence"]["items"]
        if item["field"] == "resistance"
    ]
    # Both answers are distributors, so the tie is settled by the registry's own order rather
    # than by whichever source happened to be merged first.
    losers = [item for item in rows if item["conflictsWith"]]
    assert [item["sourceId"] for item in losers] == ["mouser"]
    assert losers[0]["conflictsWith"] == "digikey"


def test_an_agreeing_answer_is_in_conflict_with_nothing():
    for item in _raw(_record())["evidence"]["items"]:
        assert item["conflictsWith"] is None


def test_no_provider_field_is_discarded_by_the_projection():
    record = _record()
    dossier = component_dossier(record)
    presented = {
        item["key"]
        for group in dossier["specificationGroups"]
        for item in group["specifications"]
    } | {item["key"] for item in dossier["keySpecifications"]}
    # The unmapped vendor key still renders under the source's own wording; nothing was dropped
    # for want of a canonical definition.
    assert "panasonic_internal_class" in presented


# --------------------------------------------------------------- translation for the reader

def test_a_disagreement_travels_as_a_field_with_named_answers():
    """`conflictState: conflicting` on a key is not something a person can settle.

    "Sources disagree about Resistance: Mouser says 1.1 kOhms, DigiKey says 1.2 kOhms" is. So the
    projection sends the answers and which one is in force, and no surface re-decides either.
    """
    record = _record()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
        ]
    }
    conflicts = component_dossier(record)["provenance"]["conflicts"]
    entry = next(item for item in conflicts if item["field"] == "resistance")
    assert entry["label"] == "Resistance"
    assert {item["displayValue"] for item in entry["candidates"]} == {"1.1 kOhms", "1.2 kOhms"}
    assert [item["sourceLabel"] for item in entry["candidates"] if item["inForce"]] == ["DigiKey"]


def test_a_record_nothing_disagrees_about_reports_no_conflicts():
    assert component_dossier(records.resistor())["provenance"]["conflicts"] == []


def test_a_record_this_build_understands_completely_carries_no_compatibility_notice():
    compatibility = component_dossier(records.resistor())["provenance"]["compatibility"]
    assert compatibility["hasNotice"] is False
    assert compatibility["readOnlyFieldCount"] == 0
    assert compatibility["fields"] == []


def test_keys_a_newer_build_wrote_travel_as_counted_named_fields():
    """A storage key is not an explanation. A count and a NAME are.

    The keys themselves stay in diagnostics, which is developer territory; what the reader gets is
    how many fields this build cannot edit and what those fields are called.
    """
    record = _record()
    record.extra = {"manufacturer_part_number_raw": "ERJ-P03F1101V"}
    record.derived_extra = {"projection_v4": {"x": 1}}
    compatibility = component_dossier(record)["provenance"]["compatibility"]
    assert compatibility["hasNotice"] is True
    assert compatibility["readOnlyFieldCount"] == 2
    assert [item["label"] for item in compatibility["fields"]] == [
        "Manufacturer part number raw",
        "Projection v4",
    ]
    assert [item["origin"] for item in compatibility["fields"]] == ["record", "derived"]
