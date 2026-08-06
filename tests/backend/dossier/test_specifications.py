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
    CATEGORY_GROUPS,
    GROUP_PARENT,
    IMPORTANCE_LEVELS,
    OTHER_GROUP,
    UNIVERSAL_GROUPS,
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


def test_one_value_holds_the_slot_and_the_owners_distributor_order_decides_which():
    """Three distributors, one row, one displayed answer - and the other two still there.

    Mouser first, DigiKey second, LCSC third is the owner's order (2026-08-05), carried by the
    provider registry's own position rather than by three tiers.
    """
    record = records.resistor()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.3 kOhms", source="lcsc"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
            SourcedValue(value="1.1 kOhms", source="mouser"),
        ]
    }
    item = _by_key(record)["resistance"]
    assert item["preferredValue"] == "1.1 kOhms"
    assert item["preferredSource"]["sourceId"] == "mouser"
    assert [entry["sourceId"] for entry in item["sourceCandidates"]] == [
        "mouser",
        "digikey",
        "lcsc",
    ]
    # One answer is SHOWN; nothing is discarded, and the disagreement is still named.
    assert item["conflictState"] == "conflicting"
    assert item["verificationState"] == "conflicting"


def test_a_field_only_lcsc_reports_is_shown_and_attributed_to_lcsc():
    record = records.resistor()
    record.alternates = {"Tolerance": [SourcedValue(value="1%", source="lcsc")]}
    item = _by_key(record)["tolerance"]
    assert item["preferredValue"] == "1%"
    assert item["preferredSource"]["sourceId"] == "lcsc"
    assert item["preferredSource"]["sourceLabel"] == "LCSC"
    # A distributor answer, no longer `Parsed Or Inferred`, which is what it read as while the
    # provider registry did not know LCSC existed.
    assert item["preferredSource"]["tier"] == "authorized_distributor"
    assert item["preferredSource"]["tierLabel"] == "Trusted Authorized Distributor"
    assert item["conflictState"] == "none"


def test_the_datasheet_still_holds_the_slot_against_all_three_distributors():
    record = records.resistor()
    record.alternates = {
        "Resistance": [
            SourcedValue(value="1.1 kOhms", source="mouser"),
            SourcedValue(value="1.2 kOhms", source="digikey"),
            SourcedValue(value="1.3 kOhms", source="lcsc"),
            SourcedValue(value="1.0 kOhms", source="datasheet"),
        ]
    }
    item = _by_key(record)["resistance"]
    assert item["preferredValue"] == "1.0 kOhms"
    assert item["preferredSource"]["tier"] == "manufacturer_datasheet"
    assert item["preferredSource"]["sourceId"] == "datasheet"
    assert {entry["sourceId"] for entry in item["sourceCandidates"]} >= {
        "mouser",
        "digikey",
        "lcsc",
    }


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


def test_a_key_specification_is_moved_into_the_headline_block_and_not_copied():
    # THIS TEST WAS THE OPPOSITE ASSERTION, deliberately reversed on the owner's decision.
    #
    # It used to read `test_a_key_specification_also_appears_in_its_own_engineering_group`, on the
    # reasoning that resistance is a key fact ABOUT a resistor and an electrical parameter OF it, so
    # a reader working down the engineering groups had to find it there too. The reasoning is sound
    # in isolation and was measured to be wrong in aggregate: on the seeded 100 nF capacitor ALL
    # SEVEN key specifications were also their groups' only rows, so eleven distinct fields rendered
    # as eighteen rows under ten headings and `Capacitance` appeared twice on one screen about a
    # capacitor. The reader scrolling the groups was re-reading the block they had just read.
    #
    # Promotion is a MOVE now. Nothing is lost: the value is on screen, above the groups, and the
    # row object is unchanged - `Specifications.records` still carries every field, so completeness,
    # search, the evidence levels and the raw projection are all untouched.
    dossier = component_dossier(records.resistor())
    key_specs = {item["key"] for item in dossier["keySpecifications"]}
    listed = {
        item["key"]
        for group in dossier["specificationGroups"]
        for item in group["specifications"]
    }
    assert key_specs
    assert key_specs.isdisjoint(listed)
    # And every one of them is still reachable, which is the half the reversal must not break.
    for record in (records.resistor(), records.capacitor(), records.microcontroller()):
        projected = component_dossier(record)
        promoted = {item["key"] for item in projected["keySpecifications"]}
        assert promoted, "a category with key specifications must present them"
        every_row = {item["key"] for item in _specs(record).records}
        assert promoted <= every_row


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
    #
    # The undeclared group is no longer necessarily the HEADING it is read under: `mounting` holds one
    # row, so it folds into `Package and Mechanical` (see `GROUP_PARENT`). What this test protects is
    # that the row REACHES the sheet, so it is asserted about the row rather than about the heading -
    # a heading is a presentation decision and the missing row was the actual bug.
    dossier = component_dossier(records.resistor())
    on_screen = {item["key"] for item in dossier["keySpecifications"]} | {
        item["key"]
        for group in dossier["specificationGroups"]
        for item in group["specifications"]
    }
    assert "mounting_type" in on_screen
    # A resistor's case code is in `construction_termination`, which the resistor schema also never
    # declares, and it is not a key specification - so it is the undeclared-group case with nothing
    # else carrying it. It is read under the universal heading that group refines.
    package = next(
        group for group in dossier["specificationGroups"] if group["id"] == "package_mechanical"
    )
    assert "case_code" in {item["key"] for item in package["specifications"]}


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
    # `Environmental and Reliability` holds one row for a capacitor, the operating temperature nobody
    # supplied, and the category expects it. A Missing row is real content and a reader has to be
    # able to reach it - dropping a heading for having no VALUES would hide exactly the gaps this
    # sheet exists to show.
    #
    # It used to be stated on `Tolerance and Stability`, whose one row was the capacitor's tolerance.
    # That row is a key specification and is now read in the headline block instead, so the same rule
    # is stated on the universal group that still demonstrates it. A universal group never folds - see
    # `GROUP_PARENT` - so one Missing row under it is exactly the case being protected.
    groups = {
        group["id"]: group
        for group in component_dossier(records.capacitor())["specificationGroups"]
    }
    assert "environmental_reliability" in groups
    states = {
        item["key"]: item["verificationState"]
        for item in groups["environmental_reliability"]["specifications"]
    }
    assert states == {"operating_temperature": "missing"}


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


def test_a_refinement_holding_one_row_is_read_under_the_heading_it_refines():
    # MEASURED on the seeded 100 nF 0402 capacitor: seven headings held exactly one row each -
    # `Package and Mechanical`, `Environmental and Reliability`, `Capacitance`,
    # `Tolerance and Stability`, `Temperature Characteristics`, `Construction and Termination` and
    # `Mounting` - so the sheet spent one header line per line of data and the anchor strip offered
    # seven destinations that were each a single row. One header per row is an index, not a grouping.
    dossier = component_dossier(records.capacitor())
    ids = {group["id"] for group in dossier["specificationGroups"]}
    assert not ids & {
        "capacitance",
        "tolerance_stability",
        "temperature_characteristics",
        "construction_termination",
        "mounting",
    }
    # And the row is HOMED, not dropped: the capacitor's case code is a package-and-mechanical fact
    # and is read there rather than under a heading invented for it alone.
    package = next(
        group for group in dossier["specificationGroups"] if group["id"] == "package_mechanical"
    )
    assert "case_code" in {item["key"] for item in package["specifications"]}
    assert package["count"] == len(package["specifications"])


def test_a_refinement_with_enough_under_it_keeps_its_own_heading():
    # The fold is about ONE row, not about category groups being unwelcome. The microcontroller's
    # peripherals group carries three rows, which is a grouping worth separating, so it stands.
    groups = {
        group["id"]: group
        for group in component_dossier(records.microcontroller())["specificationGroups"]
    }
    assert "analog_digital_peripherals" in groups
    assert groups["analog_digital_peripherals"]["count"] >= 2


def test_a_universal_group_never_folds_even_holding_one_row():
    # A universal group IS the parent. `Environmental and Reliability` holds one row on a capacitor
    # and keeps its heading, because there is no more general place for it to be read and a reader
    # navigating the anchor strip for the temperature range has to have somewhere to land.
    groups = {
        group["id"]: group
        for group in component_dossier(records.capacitor())["specificationGroups"]
    }
    assert groups["environmental_reliability"]["count"] == 1


def test_every_category_group_declares_the_universal_heading_it_refines():
    # The fold target is a static declaration, which is what makes a row's section deterministic. A
    # new category group therefore cannot ship without saying where its single row belongs, and it can
    # never point at the headline region or at the `other` bucket - folding into either would hide a
    # row rather than home it.
    universal = {key for key, _ in UNIVERSAL_GROUPS}
    for group_id, _ in CATEGORY_GROUPS:
        assert group_id in GROUP_PARENT, f"{group_id} declares no parent heading"
        parent = GROUP_PARENT[group_id]
        assert parent in universal, f"{group_id} folds into {parent}, which is not universal"
        assert parent != "key_specifications"
    # And no universal group declares one: they are the parents, not the children.
    assert not (universal & set(GROUP_PARENT))
    assert OTHER_GROUP[0] not in set(GROUP_PARENT.values())


def test_the_same_record_always_puts_a_row_in_the_same_section():
    # A row must not move between renders. The fold is a pure function of one group's own readable
    # row count, taken in one pass over a fixed ordering, so projecting the same record twice has to
    # produce the same section for every row - and it is asserted rather than argued.
    def placement(record):
        dossier = component_dossier(record)
        return {
            item["key"]: group["id"]
            for group in dossier["specificationGroups"]
            for item in group["specifications"]
        }

    for factory in (records.capacitor, records.resistor, records.connector, records.microcontroller):
        assert placement(factory()) == placement(factory())


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
