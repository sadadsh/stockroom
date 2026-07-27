"""`sourced/<id>/<vendor>.json`: the raw pull, byte for byte, as evidence.

Spec decision D1. SOURCED is immutable: exactly what each source returned, per source, never
normalized, never overwritten, never merged. DERIVED is disposable, because recomputing it
destroys nothing - which is only true while the evidence it was computed from still exists.

Device parity (spec section 10) settles the last open question: `sourced/` MUST BE COMMITTED.
A per-machine cache would let two devices derive different `display_name`, `category` and
`specs` for the same part, breaking "same info" by construction.
"""

import json

import pytest

from stockroom.model.sourced import (
    SOURCED_DIRNAME,
    SourcedPayloadExists,
    SourceEntry,
    list_sources,
    read_json,
    read_payload,
    source_rel_path,
    sourced_dir,
    sourced_file,
    write_payload,
)

# A payload shaped exactly like a distributor's: unsorted keys, four-space indent, a unicode
# micro sign, a meaningful 0.0, and a trailing newline. Every one of those is destroyed by a
# re-serialize, which is why the bytes are what is stored.
RAW = (
    '{\n'
    '    "ProductDetail": {\n'
    '        "MouserPartNumber": "595-TPS62130RGTR",\n'
    '        "Description":     "Switching Voltage Regulators 3µA 17V",\n'
    '        "TariffRate": 0.0,\n'
    '        "AvailabilityInStock": "1420"\n'
    '    }\n'
    '}\n'
)


def test_the_path_is_sourced_slash_id_slash_source_json():
    assert source_rel_path("tps62130rgtr-8c1d", "mouser") == (
        "sourced/tps62130rgtr-8c1d/mouser.json"
    )
    assert SOURCED_DIRNAME == "sourced"


def test_the_payload_is_stored_BYTE_FOR_BYTE(tmp_path):
    rel = write_payload(tmp_path, "tps62130rgtr-8c1d", "mouser", RAW)
    assert rel == "sourced/tps62130rgtr-8c1d/mouser.json"
    on_disk = (tmp_path / rel).read_bytes()
    assert on_disk == RAW.encode("utf-8"), "a re-serialize would lose spacing, order and µ"
    assert read_payload(tmp_path, "tps62130rgtr-8c1d", "mouser") == RAW


def test_bytes_go_in_untouched_too(tmp_path):
    payload = b'{"a": 1}\r\n'  # CRLF must survive: it is what the source returned
    write_payload(tmp_path, "p-0000", "digikey", payload)
    assert sourced_file(tmp_path, "p-0000", "digikey").read_bytes() == payload


def test_the_parsed_payload_is_available_for_deriving(tmp_path):
    write_payload(tmp_path, "p-0000", "mouser", RAW)
    assert read_json(tmp_path, "p-0000", "mouser")["ProductDetail"]["TariffRate"] == 0.0


def test_every_source_a_part_has_is_discoverable(tmp_path):
    write_payload(tmp_path, "p-0000", "mouser", RAW)
    write_payload(tmp_path, "p-0000", "digikey", "{}")
    assert list_sources(tmp_path, "p-0000") == ["digikey", "mouser"]
    assert list_sources(tmp_path, "nothing-here") == []


def test_the_directory_is_per_part(tmp_path):
    assert sourced_dir(tmp_path, "p-0000") == tmp_path / "sourced" / "p-0000"


# ------------------------------------------------- append-only


def test_an_existing_payload_is_never_silently_overwritten(tmp_path):
    write_payload(tmp_path, "p-0000", "mouser", RAW)
    with pytest.raises(SourcedPayloadExists):
        write_payload(tmp_path, "p-0000", "mouser", '{"different": true}')
    assert read_payload(tmp_path, "p-0000", "mouser") == RAW, "the evidence must be intact"


def test_a_deliberate_RE_PULL_rewrites_exactly_one_file(tmp_path):
    write_payload(tmp_path, "p-0000", "mouser", RAW)
    write_payload(tmp_path, "p-0000", "digikey", "{}")
    write_payload(tmp_path, "p-0000", "mouser", '{"fresh": true}', refetch=True)
    assert read_payload(tmp_path, "p-0000", "mouser") == '{"fresh": true}'
    assert read_payload(tmp_path, "p-0000", "digikey") == "{}"


def test_rewriting_identical_bytes_is_a_no_op_not_an_error(tmp_path):
    write_payload(tmp_path, "p-0000", "mouser", RAW)
    write_payload(tmp_path, "p-0000", "mouser", RAW)  # same evidence, nothing changed
    assert read_payload(tmp_path, "p-0000", "mouser") == RAW


# ------------------------------------------------- safety


def test_a_source_name_can_never_escape_its_directory(tmp_path):
    for bad in ("../etc", "a/b", "", "Mouser Inc", "..", "\\x"):
        with pytest.raises(ValueError):
            write_payload(tmp_path, "p-0000", bad, "{}")


def test_a_part_id_that_is_not_a_valid_id_is_refused(tmp_path):
    for bad in ("../x", "a/b", "", "CON"):
        with pytest.raises(ValueError):
            write_payload(tmp_path, bad, "mouser", "{}")


def test_reading_a_source_a_part_does_not_have_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_payload(tmp_path, "p-0000", "mouser")


# ------------------------------------------------- the record's index of it


def test_a_source_entry_round_trips():
    e = SourceEntry(fetched_at="2026-07-27T21:04:00Z", file="sourced/p-0000/mouser.json")
    assert SourceEntry.from_dict(e.to_dict()) == e


def test_a_source_entry_key_from_a_newer_build_survives():
    e = SourceEntry.from_dict({"fetched_at": "t", "file": "f", "http_status": 200})
    assert e.to_dict()["http_status"] == 200
    assert json.loads(json.dumps(e.to_dict()))["file"] == "f"
