import pytest

from stockroom.dossier.official_evidence import (
    build_official_evidence,
    flatten_payload,
    validate_official_payloads,
)
from stockroom.model.sourced import SourceEntry


def _binding(mpn: str, selected_values: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        "mouser": {
            "provider": "mouser",
            "queried_mpn": mpn,
            "canonical_mpn": mpn,
            "selected_values": selected_values,
        }
    }


def test_flatten_payload_keeps_every_scalar_null_and_empty_container_in_source_order():
    payload = {
        "SearchResults": {
            "Parts": [
                {
                    "MouserPartNumber": "123-X",
                    "Stock": 42,
                    "FactoryStock": None,
                    "Active": True,
                    "PriceBreaks": [],
                    "Compliance": {},
                }
            ]
        }
    }

    rows = flatten_payload(payload)
    assert [row["path"] for row in rows] == [
        "/SearchResults/Parts/0/MouserPartNumber",
        "/SearchResults/Parts/0/Stock",
        "/SearchResults/Parts/0/FactoryStock",
        "/SearchResults/Parts/0/Active",
        "/SearchResults/Parts/0/PriceBreaks",
        "/SearchResults/Parts/0/Compliance",
    ]
    assert [row["displayValue"] for row in rows] == ["123-X", "42", "null", "true", "[]", "{}"]
    assert all(row["endpoint"] == "SearchResults" for row in rows)


def test_official_evidence_keeps_both_provider_payloads_and_source_identity():
    entries = {
        "mouser": SourceEntry(
            fetched_at="2026-08-14T12:00:00+00:00",
            file="sourced/id/mouser.json",
            extra={"state": "success"},
        ),
        "digikey": SourceEntry(
            fetched_at="2026-08-14T12:01:00+00:00",
            file="sourced/id/digikey.json",
            extra={"state": "failed"},
        ),
    }
    view = build_official_evidence(
        {
            "mouser": {"Errors": [], "SearchResults": {"NumberOfResult": 1}},
            "digikey": {"schema_version": 1, "media": {"MediaLinks": []}},
        },
        source_entries=entries,
    )

    assert view["providerCount"] == 2
    assert view["fieldCount"] == 4
    assert [provider["provider"] for provider in view["providers"]] == ["mouser", "digikey"]
    assert view["providers"][0]["payloadRef"] == "sourced/id/mouser.json"
    assert view["providers"][1]["state"] == "failed"
    assert {row["path"] for row in view["providers"][1]["rows"]} == {
        "/schema_version",
        "/media/MediaLinks",
    }


def test_json_pointer_paths_keep_dotted_slash_and_nested_keys_distinct():
    rows = flatten_payload({"a.b": 1, "a": {"b": 2}, "a/b": 3, "a~b": 4})

    assert [(row["path"], row["value"]) for row in rows] == [
        ("/a.b", 1),
        ("/a/b", 2),
        ("/a~1b", 3),
        ("/a~0b", 4),
    ]


def test_official_binding_rejects_a_selected_value_absent_from_the_exact_result():
    payload = {
        "SearchResults": {
            "Parts": [
                {
                    "ManufacturerPartNumber": "PART-A",
                    "Manufacturer": "Acme",
                    "ProductAttributes": [
                        {"AttributeName": "Resistance", "AttributeValue": "10 kOhm"}
                    ],
                }
            ]
        }
    }

    with pytest.raises(ValueError, match="selected value Resistance"):
        validate_official_payloads(
            "PART-A",
            {"mouser": payload},
            _binding("PART-A", {"mpn": "PART-A", "Resistance": "1 kOhm"}),
        )


def test_official_binding_cannot_take_fields_from_an_unrelated_result_row():
    payload = {
        "SearchResults": {
            "Parts": [
                {"ManufacturerPartNumber": "PART-A", "Manufacturer": "Exact Manufacturer"},
                {"ManufacturerPartNumber": "PART-B", "Manufacturer": "Neighbor Manufacturer"},
            ]
        }
    }

    with pytest.raises(ValueError, match="selected value manufacturer"):
        validate_official_payloads(
            "PART-A",
            {"mouser": payload},
            _binding("PART-A", {"manufacturer": "Neighbor Manufacturer"}),
        )


def test_official_binding_preserves_slash_and_hyphen_as_distinct_mpn_identities():
    payload = {
        "SearchResults": {"Parts": [{"ManufacturerPartNumber": "ABC-DEF"}]}
    }

    with pytest.raises(ValueError, match="ABC-DEF.*ABC/DEF"):
        validate_official_payloads(
            "ABC/DEF",
            {"mouser": payload},
            _binding("ABC/DEF", {"mpn": "ABC/DEF"}),
        )


def test_official_binding_returns_the_server_parsed_value_not_the_client_encoding():
    payload = {
        "SearchResults": {
            "Parts": [
                {
                    "ManufacturerPartNumber": "PART-A",
                    "AvailabilityInStock": 17,
                }
            ]
        }
    }

    validated = validate_official_payloads(
        "part-a",
        {"mouser": payload},
        _binding("part-a", {"mpn": "part-a", "stock": "17"}),
    )

    assert validated["mouser"]["selected_values"] == {"mpn": "PART-A", "stock": 17}


def test_digikey_binding_selects_the_punctuation_exact_result_among_neighbors():
    payload = {
        "Products": [
            {
                "ManufacturerProductNumber": "ABC-DEF",
                "Manufacturer": {"Name": "Neighbor Manufacturer"},
            },
            {
                "ManufacturerProductNumber": "ABC/DEF",
                "Manufacturer": {"Name": "Exact Manufacturer"},
            },
        ]
    }
    binding = {
        "digikey": {
            "provider": "digikey",
            "queried_mpn": "ABC/DEF",
            "canonical_mpn": "ABC/DEF",
            "selected_values": {
                "mpn": "ABC/DEF",
                "manufacturer": "Exact Manufacturer",
            },
        }
    }

    validated = validate_official_payloads(
        "ABC/DEF",
        {"digikey": payload},
        binding,
    )

    assert validated["digikey"]["selected_values"] == {
        "mpn": "ABC/DEF",
        "manufacturer": "Exact Manufacturer",
    }
