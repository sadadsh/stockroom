from stockroom.dossier.official_evidence import build_official_evidence, flatten_payload
from stockroom.model.sourced import SourceEntry


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
