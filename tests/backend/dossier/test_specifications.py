"""The canonical specification record, and the six states it must never conflate.

Missing, Not Reported, Not Applicable, Unverified, Conflicting and Verified are six different
sentences about a field. The old projection had one word for four of them, so a category's real
gap looked exactly like a parameter nobody happened to publish.
"""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.categories import SCHEMAS_BY_KEY, resolve_schema
from stockroom.dossier.specifications import build_specifications, is_presented
from stockroom.dossier.vocabulary import (
    APPLICABILITY_STATES,
    IMPORTANCE_LEVELS,
    VERIFICATION_STATES,
)
from stockroom.model.part import EnrichmentField, FieldOverride, PartRecord, SourcedValue
from tests.backend.dossier import records


def _specs(record):
    schema = resolve_schema(record)
    return build_specifications(record, schema)


def _by_key(record) -> dict:
    return records.by_key(_specs(record).records)


# ------------------------------------------------------------------ the record shape


def test_every_specification_carries_the_whole_canonical_shape():
    item = _by_key(records.resistor())["resistance"]
    assert set(item) >= {
        "key",
        "label",
        "group",
        "order",
        "valueType",
        "preferredValue",
        "normalizedValue",
        "displayValue",
        "unit",
        "applicability",
        "importance",
        "verificationState",
        "sourceCandidates",
        "preferredSource",
        "confidence",
        "conflictState",
        "expectedForCategory",
        "filterable",
        "sortable",
        "comparable",
    }


def test_every_state_comes_from_the_closed_vocabulary():
    for record in (records.logic_gate(), records.microcontroller(), records.connector()):
        for item in _specs(record).records:
            assert item["verificationState"] in VERIFICATION_STATES
            assert item["applicability"] in APPLICABILITY_STATES
            assert item["importance"] in IMPORTANCE_LEVELS


# ------------------------------------------------------------------ the six states


def test_an_expected_field_with_no_value_is_missing_and_is_still_emitted():
    item = _by_key(records.microcontroller(specs={}))["program_memory_size"]
    assert item["verificationState"] == "missing"
    assert item["expectedForCategory"] is True
    assert item["displayValue"] == ""


def test_a_field_nobody_reported_is_not_reported_and_is_not_a_gap():
    item = _by_key(records.microcontroller())["debug_interface"]
    assert item["verificationState"] == "not_reported"
    assert item["expectedForCategory"] is False


def test_a_field_that_does_not_apply_to_the_category_is_not_applicable():
    item = _by_key(records.connector())["program_memory_size"]
    assert item["verificationState"] == "not_applicable"
    assert item["applicability"] == "not_applicable"


def test_the_four_absent_states_are_all_different_words():
    item = _by_key(records.microcontroller(specs={}))
    assert item["program_memory_size"]["verificationState"] == "missing"
    assert item["debug_interface"]["verificationState"] == "not_reported"
    assert item["positions"]["verificationState"] == "not_applicable"


def test_a_distributor_value_is_unverified_not_verified():
    record = records.resistor()
    record.enrichment = {"Resistance": EnrichmentField(source="mouser", confidence="high")}
    assert _by_key(record)["resistance"]["verificationState"] == "unverified"


def test_a_datasheet_value_is_verified():
    record = records.resistor()
    record.enrichment = {"Resistance": EnrichmentField(source="datasheet", confidence="high")}
    item = _by_key(record)["resistance"]
    assert item["verificationState"] == "verified"
    assert item["preferredSource"]["tier"] == "manufacturer_datasheet"


def test_disagreeing_sources_are_conflicting_and_every_answer_is_kept():
    record = records.resistor()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
        ]
    }
    item = _by_key(record)["resistance"]
    assert item["verificationState"] == "conflicting"
    assert item["conflictState"] == "conflicting"
    assert {entry["sourceId"] for entry in item["sourceCandidates"]} == {"mouser", "digikey"}


def test_an_unattributed_value_never_claims_to_be_verified():
    item = _by_key(records.resistor())["resistance"]
    assert item["verificationState"] == "unverified"
    assert item["preferredSource"]["sourceLabel"] == "Unattributed"


# ------------------------------------------------------------------ manual overrides


def test_a_reviewed_override_wins_the_slot_and_is_verified():
    record = records.resistor()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
        ]
    }
    record.overrides = {
        "resistance": FieldOverride(
            value="1.1 kOhms", note="Measured", reviewed_by="owner", reviewed_at="2026-08-01"
        )
    }
    item = _by_key(record)["resistance"]
    assert item["preferredSource"]["tier"] == "manual_override"
    assert item["verificationState"] == "verified"


def test_an_override_settles_a_conflict_without_discarding_the_losers():
    record = records.resistor()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
        ]
    }
    record.overrides = {"resistance": FieldOverride(value="1.15 kOhms", reviewed_by="owner")}
    item = _by_key(record)["resistance"]
    assert item["conflictState"] == "resolved"
    assert len(item["sourceCandidates"]) == 3


def test_an_override_reaches_the_dossier_provenance_with_its_reviewer():
    record = records.resistor()
    record.overrides = {
        "resistance": FieldOverride(value="1.1 kOhms", reviewed_by="owner", note="Measured")
    }
    overrides = component_dossier(record)["provenance"]["manualOverrides"]
    assert overrides == [
        {
            "field": "resistance",
            "value": "1.1 kOhms",
            "hasValue": True,
            "preferredSource": "",
            "preferredSourceLabel": "",
            "replacedValue": None,
            "replacedSource": "",
            "replacedSourceLabel": "",
            "note": "Measured",
            "reviewedBy": "owner",
            "reviewedAt": "",
        }
    ]


# ------------------------------------------------------------------ grouping


def test_two_spellings_of_one_field_become_one_row_rather_than_two():
    record = records.resistor(
        specs={"DCR": "0.5 Ohms", "DC Resistance": "0.5 Ohms", "Package / Case": "0603"}
    )
    keys = [item["key"] for item in _specs(record).records]
    assert keys.count("dc_resistance") == 1


def test_a_key_the_registry_does_not_know_is_placed_and_never_dropped():
    record = records.resistor(
        specs={"Panasonic Special Rating": "Class 9", "Package / Case": "0603"}
    )
    item = records.by_key(_specs(record).records)["panasonic_special_rating"]
    assert item["group"] == "other"
    assert item["displayValue"] == "Class 9"
    assert item["mapped"] is False
    assert item["label"] == "Panasonic Special Rating"


def test_bookkeeping_keys_never_take_a_specification_row():
    assert not is_presented("Image")
    assert not is_presented("pinout")
    assert not is_presented("Brand Id")
    assert is_presented("Resistance")
    assert is_presented("Grid")


def test_a_key_specification_also_appears_in_its_own_engineering_group():
    # Resistance is a key fact ABOUT a resistor and an electrical parameter OF it. A reader
    # working down the engineering groups to find it has to find it there, so the headline block
    # LIFTS the row rather than taking it away. The duplication is deliberate.
    dossier = component_dossier(records.resistor())
    key_specs = {item["key"] for item in dossier["keySpecifications"]}
    listed = {
        item["key"]
        for group in dossier["specificationGroups"]
        for item in group["specifications"]
    }
    assert key_specs
    assert key_specs <= listed


def test_no_group_is_ever_emitted_under_the_key_specifications_id():
    # That id names the headline region and nothing else; emitting it as a group as well would
    # put the same block on screen twice under two different headings.
    for record in (records.resistor(), records.microcontroller(), records.connector()):
        ids = {group["id"] for group in component_dossier(record)["specificationGroups"]}
        assert "key_specifications" not in ids


def test_a_row_whose_group_the_category_never_declared_still_reaches_the_sheet():
    # A field's registry group does not have to be one the category listed - a resistor's
    # Mounting Type belongs to `mounting`, which the resistor schema never declares. A row with
    # nowhere to go used to vanish from the sheet entirely, which is the invisible hole the whole
    # category schema exists to prevent.
    dossier = component_dossier(records.resistor())
    listed = {
        item["key"]
        for group in dossier["specificationGroups"]
        for item in group["specifications"]
    }
    assert "mounting_type" in listed
    assert {group["id"] for group in dossier["specificationGroups"]} >= {"mounting"}


def test_a_group_with_nothing_but_inapplicable_rows_is_never_a_heading():
    # MEASURED on a 100 nF 0402 ceramic capacitor: the sheet offered `Memory` and
    # `Communication Interfaces` - two microcontroller headings - because the capacitor schema
    # rules `program_memory_size` and `interface` inapplicable and those keys live in those
    # groups. Nothing was under either heading but the words "Not Applicable", and the column's
    # anchor strip offered both. A heading is a promise that something is below it.
    dossier = component_dossier(records.capacitor())
    groups = {group["id"] for group in dossier["specificationGroups"]}
    assert not groups & {"memory", "communication_interfaces", "interface_pinout"}
    # The rows themselves are NOT discarded: the projection still knows the fields were
    # considered and ruled out, which is what keeps completeness and the evidence levels honest.
    by_key = records.by_key(dossier["keySpecifications"] + [
        item for group in dossier["specificationGroups"] for item in group["specifications"]
    ])
    assert "program_memory_size" not in by_key
    ruled_out = records.by_key(_specs(records.capacitor()).records)
    assert ruled_out["program_memory_size"]["verificationState"] == "not_applicable"
    assert ruled_out["interface"]["verificationState"] == "not_applicable"


def test_a_group_whose_only_row_is_an_expected_gap_is_still_a_heading():
    # The opposite case, and the reason the rule is about the STATE rather than about emptiness:
    # `Tolerance and Stability` holds one row for a capacitor, the tolerance nobody supplied, and
    # the category expects it. A Missing row is real content and a reader has to be able to reach
    # it - dropping a heading for having no VALUES would hide exactly the gaps this sheet exists
    # to show.
    groups = {
        group["id"]: group
        for group in component_dossier(records.capacitor())["specificationGroups"]
    }
    assert "tolerance_stability" in groups
    states = {
        item["key"]: item["verificationState"]
        for item in groups["tolerance_stability"]["specifications"]
    }
    assert states == {"tolerance": "missing"}


def test_an_inapplicable_row_still_renders_beside_real_ones():
    # A group is kept or dropped WHOLE; it is not filtered row by row. Where the heading is earned
    # by real content, the rows that do not apply stay visible under it, so a reader looking for
    # one learns it does not exist for this part instead of wondering whether it was dropped.
    # A connector with a stated Type earns `Functional`, and the gate function and logic family
    # the connector schema rules out are read there.
    record = records.connector()
    record.specs["Type"] = "Header"
    groups = {
        group["id"]: group for group in component_dossier(record)["specificationGroups"]
    }
    states = {
        item["key"]: item["verificationState"]
        for item in groups["functional"]["specifications"]
    }
    assert states["component_type"] == "unverified"
    assert states["gate_function"] == "not_applicable"
    assert states["logic_family"] == "not_applicable"


def test_the_rule_is_about_the_rows_and_never_about_the_group_itself():
    # Not a per-category blocklist of headings. Distributors do publish a termination count for a
    # passive, and the moment one is on record `Interface and Pinout` is a heading with something
    # under it - so the same group the bare capacitor could not earn is emitted here.
    record = records.capacitor()
    record.specs["Number of Pins"] = "2"
    groups = {
        group["id"]: group for group in component_dossier(record)["specificationGroups"]
    }
    assert "interface_pinout" in groups
    pins = records.by_key(groups["interface_pinout"]["specifications"])["pin_count"]
    assert pins["displayValue"] == "2"


def test_every_group_count_is_derived_from_its_own_rows():
    for group in component_dossier(records.connector())["specificationGroups"]:
        assert group["count"] == len(group["specifications"])


def test_a_pinout_is_a_table_and_never_a_specification_row():
    record = records.microcontroller()
    record.specs["pinout"] = [{"pin": "1", "name": "VBAT"}]
    dossier = component_dossier(record)
    assert dossier["diagnostics"]["pinout"] == [{"pin": "1", "name": "VBAT"}]
    assert "pinout" not in {item["key"] for item in dossier["keySpecifications"]}


# ------------------------------------------------------------------ completeness


def test_completeness_is_measured_against_this_categorys_own_expectations():
    resistor = component_dossier(records.resistor())["qualitySummary"]["completeness"]
    assert resistor["basis"] == "resistor"
    assert resistor["expectedTotal"] == len(SCHEMAS_BY_KEY["resistor"].expected)


def test_an_irrelevant_field_never_counts_against_completeness():
    connector = component_dossier(records.connector())["qualitySummary"]["completeness"]
    schema = SCHEMAS_BY_KEY["connector"]
    counted = set(schema.expected) | set(schema.recommended)
    assert not counted & set(schema.not_applicable)
    assert "program_memory_size" not in connector["missingExpected"]


def test_a_fully_described_part_scores_one_and_an_empty_one_scores_zero():
    schema = SCHEMAS_BY_KEY["resistor"]
    full = records.resistor(
        specs={key: "1" for key in (*schema.expected, *schema.recommended)}
    )
    assert component_dossier(full)["qualitySummary"]["completeness"]["score"] == 1.0
    empty = records.resistor(specs={})
    assert component_dossier(empty)["qualitySummary"]["completeness"]["score"] == 0.0


def test_the_same_part_scores_differently_under_two_categories():
    as_resistor = component_dossier(records.resistor())["qualitySummary"]["completeness"]
    as_connector = component_dossier(
        records.resistor(category="Connectors", description="terminal block")
    )["qualitySummary"]["completeness"]
    assert as_resistor["basis"] != as_connector["basis"]
    assert as_resistor["score"] != as_connector["score"]


# ------------------------------------------------------------------ constraints


def test_a_value_outside_the_categorys_constraint_is_reported_never_rewritten():
    record = records.resistor(specs={"Resistance": "-5 Ohms", "Package / Case": "0603"})
    item = records.by_key(_specs(record).records)["resistance"]
    assert item["constraintViolation"]
    assert item["preferredValue"] == "-5 Ohms"


def test_a_value_inside_the_constraint_reports_no_violation():
    assert _by_key(records.resistor())["resistance"]["constraintViolation"] is None


# ------------------------------------------------------------------ facets


def test_a_specification_says_whether_it_can_be_filtered_sorted_and_compared():
    item = _by_key(records.resistor())["resistance"]
    assert item["filterable"] is True
    assert item["sortable"] is True
    assert item["comparable"] is True
    unknown = records.by_key(
        _specs(records.resistor(specs={"Odd Vendor Note": "x"})).records
    )["odd_vendor_note"]
    assert unknown["filterable"] is False


def test_a_part_with_no_specifications_at_all_still_projects():
    dossier = component_dossier(PartRecord(id="x-0001", category="Other"))
    assert dossier["keySpecifications"] is not None
    assert dossier["qualitySummary"]["completeness"]["score"] >= 0.0
