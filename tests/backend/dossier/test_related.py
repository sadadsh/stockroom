"""Related parts, each carrying why it is related."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.categories import resolve_schema
from stockroom.dossier.related import REASON_LABELS, build_related_parts
from stockroom.dossier.specifications import build_specifications
from tests.backend.dossier import records


def _related(record) -> list[dict]:
    schema = resolve_schema(record)
    return build_related_parts(record, build_specifications(record, schema))


def test_every_related_part_states_a_reason():
    record = records.logic_gate()
    record.catalog = {
        "digikey": {
            "alternate_packaging": [{"manufacturer_product_number": "SN74LVC1G08DBVT"}],
            "substitutions": [{"manufacturer_product_number": "NC7SZ08M5X"}],
            "recommended_products": [{"manufacturer_product_number": "SN74LVC1G32DBVR"}],
            "associations": [{"manufacturer_product_number": "CAP-0402"}],
        }
    }
    related = _related(record)
    assert related
    assert all(item["reason"] in REASON_LABELS for item in related)
    assert all(item["reasonLabel"] for item in related)


def test_a_different_logic_family_at_the_same_type_number_is_named_as_such():
    record = records.logic_gate()
    record.catalog = {
        "digikey": {"substitutions": [{"manufacturer_product_number": "SN74HC08DBVR"}]}
    }
    item = _related(record)[0]
    assert item["reason"] == "same_function_different_logic_family"
    assert {entry["field"] for entry in item["evidence"]} == {"logic_family", "gate_function"}
    assert [entry for entry in item["evidence"] if entry["field"] == "logic_family"][0] == {
        "field": "logic_family",
        "ours": "LVC",
        "theirs": "HC",
    }


def test_a_different_package_on_the_same_base_part_is_named_as_such():
    record = records.logic_gate()
    record.catalog = {
        "digikey": {
            "substitutions": [
                {
                    "manufacturer_product_number": "SN74LVC1G08DCKR",
                    "description": "Single AND gate, SC-70 package",
                }
            ]
        }
    }
    item = _related(record)[0]
    assert item["reason"] == "same_function_different_package"
    assert item["evidence"][0]["field"] == "package"


def test_alternate_packaging_keeps_its_own_reason():
    record = records.resistor()
    record.catalog = {
        "digikey": {
            "alternate_packaging": [{"manufacturer_product_number": "ERJ-P03F1101V-CT"}]
        }
    }
    assert _related(record)[0]["reason"] == "alternate_packaging"


def test_a_distributor_suggestion_says_it_is_a_distributor_suggestion():
    record = records.resistor()
    record.catalog = {
        "digikey": {"recommended_products": [{"manufacturer_product_number": "RC0603FR-071K1L"}]}
    }
    item = _related(record)[0]
    assert item["reason"] == "distributor_recommendation"
    assert item["providerLabel"] == "DigiKey"


def test_no_related_row_ever_claims_equivalence():
    record = records.resistor()
    record.catalog = {
        "digikey": {"substitutions": [{"manufacturer_product_number": "RC0603FR-071K1L"}]}
    }
    assert _related(record)[0]["validated"] is False


def test_a_part_with_no_catalogue_relationships_reports_an_empty_list():
    assert component_dossier(records.resistor())["relatedParts"] == []


def test_the_provider_that_suggested_a_row_travels_with_it():
    record = records.resistor()
    record.catalog = {
        "mouser": {"substitutions": [{"manufacturer_product_number": "X", "url": "https://m"}]}
    }
    item = _related(record)[0]
    assert item["provider"] == "mouser"
    assert item["url"] == "https://m"
