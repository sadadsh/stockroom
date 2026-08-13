"""Category schemas: a logic gate is not an MCU is not a resistor is not a connector.

These tests hold the thing the old projection could not do. One universal substring rule gave
all four the same buckets and the same idea of complete; the registry gives each of them its
own, and that difference has to be provable rather than asserted in a docstring.
"""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.categories import (
    BASE_SCHEMA,
    CATEGORY_SCHEMAS,
    SCHEMAS_BY_KEY,
    resolve_schema,
)
from stockroom.dossier.fields import FIELDS_BY_KEY
from stockroom.dossier.specifications import build_specifications
from stockroom.dossier.vocabulary import GROUP_LABELS, UNIVERSAL_GROUPS
from stockroom.model.category import CATEGORIES
from stockroom.model.part import PartRecord
from tests.backend.dossier import records

# ------------------------------------------------------------------ resolution


def test_a_signal_inside_the_filed_category_picks_the_specific_schema():
    assert resolve_schema(records.logic_gate()).key == "logic_gate"
    assert resolve_schema(records.microcontroller()).key == "microcontroller"


def test_a_filed_category_with_no_signal_falls_back_to_its_own_default():
    plain = records.microcontroller(description="Integrated circuit", specs={})
    assert resolve_schema(plain).key == "integrated_circuit"


def test_an_unfiled_part_gets_the_base_schema_not_another_categorys():
    assert resolve_schema(PartRecord(id="x-0001", category="")).key == BASE_SCHEMA.key


def test_a_signal_word_cannot_refile_a_part_across_categories():
    # "Inverter" is a logic-gate signal. On a part filed as a resistor it must not reach for the
    # logic gate schema, because signals are only ever searched inside the filed category.
    confusing = records.resistor(description="Current sense resistor for an inverter design")
    assert resolve_schema(confusing).key == "resistor"


def test_every_filed_category_resolves_to_a_schema():
    for category in CATEGORIES:
        record = PartRecord(id="x-0001", category=category, description="")
        assert resolve_schema(record) is not None


# ------------------------------------------------------------------ key specs


def _key_specs(record) -> list[str]:
    return [
        item["key"]
        for item in build_specifications(record, resolve_schema(record)).key_specifications
    ]


def test_the_four_families_do_not_share_a_key_specification_set():
    gate = _key_specs(records.logic_gate())
    mcu = _key_specs(records.microcontroller())
    resistor = _key_specs(records.resistor())
    connector = _key_specs(records.connector())
    sets = [set(gate), set(mcu), set(resistor), set(connector)]
    for left in range(len(sets)):
        for right in range(left + 1, len(sets)):
            assert sets[left] != sets[right]


def test_each_familys_key_specifications_are_the_ones_that_decide_the_part():
    assert "gate_function" in _key_specs(records.logic_gate())
    assert "logic_family" in _key_specs(records.logic_gate())
    assert "program_memory_size" in _key_specs(records.microcontroller())
    assert "core_processor" in _key_specs(records.microcontroller())
    assert "resistance" in _key_specs(records.resistor())
    assert "power_rating" in _key_specs(records.resistor())
    assert "positions" in _key_specs(records.connector())
    assert "pitch" in _key_specs(records.connector())


def test_a_microcontrollers_headline_is_not_offered_to_a_resistor():
    resistor = _key_specs(records.resistor())
    assert "program_memory_size" not in resistor
    assert "core_processor" not in resistor


def test_key_specifications_keep_the_schemas_declared_order():
    schema = SCHEMAS_BY_KEY["resistor"]
    emitted = _key_specs(records.resistor())
    assert emitted == [key for key in schema.key_specs if key in set(emitted)]


# ------------------------------------------------------------------ groups


def test_every_schema_declares_only_groups_that_have_a_label():
    for schema in (*CATEGORY_SCHEMAS, BASE_SCHEMA):
        for group in schema.groups:
            assert group in GROUP_LABELS, f"{schema.key} declares an unlabelled group {group}"


def test_the_universal_groups_always_lead_in_the_same_order():
    for schema in (*CATEGORY_SCHEMAS, BASE_SCHEMA):
        universal = tuple(key for key, _ in UNIVERSAL_GROUPS)
        assert schema.group_order()[: len(universal)] == universal


def test_a_category_specific_group_is_rendered_for_the_category_that_earns_it():
    # "Earns it" is now two conditions, not one: the category's rows have to LAND in the group AND
    # there has to be more than one of them, because a heading over a single row is an index entry
    # rather than a grouping (see `GROUP_PARENT` and the fold in `build_specifications`). The
    # microcontroller's peripherals group carries three rows and stands on its own; the connector's
    # `mating_retention` and `electrical_ratings` hold one each and are read under the universal
    # headings they refine.
    mcu_groups = {
        item["id"]
        for item in component_dossier(
            records.microcontroller(
                specs={
                    **records.microcontroller().specs,
                    "ADC Channels": "16",
                    "DAC Channels": "2",
                    "Timers": "12",
                }
            )
        )["specificationGroups"]
    }
    assert "analog_digital_peripherals" in mcu_groups
    # The category boundary is still enforced: a resistor never grows a connector's heading, and its
    # rows never land in one either.
    resistor = component_dossier(records.resistor())
    assert "mating_retention" not in {item["id"] for item in resistor["specificationGroups"]}
    assert "analog_digital_peripherals" not in {
        item["id"] for item in resistor["specificationGroups"]
    }
    # And a connector's mating facts still reach the sheet, under the heading they refine.
    connector = component_dossier(
        records.connector(specs={**records.connector().specs, "Retention Type": "Friction"})
    )
    placed = {
        item["key"]: group["id"]
        for group in connector["specificationGroups"]
        for item in group["specifications"]
    }
    assert placed.get("retention_type") == "package_mechanical"


def test_a_schema_moves_a_field_into_its_own_group_rather_than_redefining_it():
    schema = SCHEMAS_BY_KEY["resistor"]
    assert FIELDS_BY_KEY["resistance"].group == "electrical"
    assert schema.group_for("resistance", "electrical") == "resistance"


# ------------------------------------------------------------------ registry hygiene


def test_every_schema_field_reference_names_a_defined_field():
    for schema in (*CATEGORY_SCHEMAS, BASE_SCHEMA):
        referenced = set(schema.key_specs) | set(schema.expected) | set(schema.recommended)
        referenced |= set(schema.applicable) | set(schema.not_applicable)
        referenced |= set(schema.facets) | set(schema.comparison)
        referenced |= {item.field_key for item in schema.cad_relationships}
        unknown = referenced - set(FIELDS_BY_KEY)
        assert not unknown, f"{schema.key} references undefined fields: {sorted(unknown)}"


def test_no_schema_both_expects_a_field_and_declares_it_inapplicable():
    for schema in (*CATEGORY_SCHEMAS, BASE_SCHEMA):
        contradiction = (set(schema.expected) | set(schema.recommended)) & set(
            schema.not_applicable
        )
        assert not contradiction, f"{schema.key} contradicts itself on {sorted(contradiction)}"


def test_every_schema_key_is_unique():
    keys = [schema.key for schema in CATEGORY_SCHEMAS]
    assert len(keys) == len(set(keys))
