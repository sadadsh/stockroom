"""A part record must survive a round trip through a DIFFERENT build of Stockroom.

Peers share these JSON records through git and both write them. The Kubernetes API
conventions state the rule this locks: patching a resource at schema version N-1 must not
erase fields defined at version N. Stockroom's records had no such protection -- `from_dict`
built from known keys only and `to_dict` emitted known keys only, so an older build that
edited one field would silently DELETE every field a newer build had added, and git would
record that deletion as a deliberate change.

Two mechanisms, both tested here:
  1. `schema_version` -- so a build can KNOW it is looking at a record it may not fully
     understand, and say so instead of pretending.
  2. unknown-key preservation -- so it round-trips that record without destroying anything.
"""
import json

from stockroom.model.part import SCHEMA_VERSION, AssetRef, PartRecord


def _rec(**kw) -> PartRecord:
    return PartRecord(id="x", display_name="n", category="ICs", **kw)


def test_a_new_record_carries_the_current_schema_version():
    assert _rec().schema_version == SCHEMA_VERSION
    assert json.loads(_rec().dumps())["schema_version"] == SCHEMA_VERSION


def test_a_versionless_legacy_record_is_upgraded_in_place():
    # Version 1 is the pre-cutover shape: flat `symbol`/`footprint`/`model` + `altium_*`.
    # Reading it folds those into the v2 `eda` map, so the in-memory record IS a v2 record
    # and says so -- `schema_version` is the version this record will be WRITTEN at, not a
    # record of where it came from.
    rec = PartRecord.from_dict({
        "id": "x", "display_name": "n", "category": "ICs",
        "symbol": {"lib": "SR-ICs", "name": "A"},
    })
    assert rec.assets_for("kicad").symbol.ref == AssetRef(lib="SR-ICs", name="A")
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.is_future_schema() is False


def test_a_legacy_record_is_rewritten_at_the_current_version():
    rec = PartRecord.from_dict({"id": "x", "display_name": "n", "category": "ICs"})
    assert json.loads(rec.dumps())["schema_version"] == SCHEMA_VERSION


# ------------------------------------------------- forward compatibility


# A record from a build SEVEN versions ahead of ours. It is written in the shape we know (v3),
# plus fields we have never heard of - which is the realistic case: a newer peer ADDS fields, it
# does not usually rewrite the whole record. A record whose SHAPE we do not know is a different
# problem, and `is_future_schema` is what tells a caller not to restructure it.
FUTURE = {
    "id": "x",
    "schema_version": SCHEMA_VERSION + 7,
    "derived": {"display_name": "n", "category": "ICs"},
    "lifecycle": {"status": "active", "checked_at": "2027-01-01"},
    "compliance_docs": ["rohs.pdf"],
    "assets": {"kicad": {"symbol": {"ref": {"lib": "SR-ICs", "name": "A"}}}},
}


def test_a_field_this_build_does_not_know_survives_a_round_trip():
    out = json.loads(PartRecord.from_dict(dict(FUTURE)).dumps())
    assert out["lifecycle"] == {"status": "active", "checked_at": "2027-01-01"}
    assert out["compliance_docs"] == ["rohs.pdf"]


def test_an_unknown_field_survives_an_EDIT_to_a_known_field():
    # The real scenario: an older build opens a newer peer's part and changes one field.
    rec = PartRecord.from_dict(dict(FUTURE))
    rec.description = "edited by an older build"
    out = json.loads(rec.dumps())
    assert out["derived"]["description"] == "edited by an older build"
    assert out["lifecycle"]["status"] == "active", "the edit must not erase the unknown field"


def test_a_future_record_keeps_its_own_version_rather_than_being_downgraded():
    # Claiming to have written the current version would tell the next reader this record is
    # fully understood by builds at that version, which is false.
    out = json.loads(PartRecord.from_dict(dict(FUTURE)).dumps())
    assert out["schema_version"] == SCHEMA_VERSION + 7


def test_a_record_from_the_future_is_flagged_not_silently_accepted():
    assert PartRecord.from_dict(dict(FUTURE)).is_future_schema() is True
    assert _rec().is_future_schema() is False
    assert PartRecord.from_dict({"id": "x", "display_name": "n", "category": "ICs"}).is_future_schema() is False


def test_a_known_field_is_never_duplicated_into_the_unknown_bag():
    rec = PartRecord.from_dict(dict(FUTURE))
    assert "derived" not in rec.extra
    assert "assets" not in rec.extra
    assert set(rec.extra) == {"lifecycle", "compliance_docs"}


def test_the_legacy_flat_fields_are_consumed_not_preserved_as_unknown():
    # They are folded into `eda`; re-emitting them too would leave the record carrying two
    # contradictory copies of its assets.
    rec = PartRecord.from_dict({
        "id": "x", "display_name": "n", "category": "ICs",
        "symbol": {"lib": "SR-ICs", "name": "A"},
        "altium_symbol": {"lib": "a.SchLib", "name": "A"},
    })
    out = json.loads(rec.dumps())
    assert "symbol" not in out and "altium_symbol" not in out
    assert rec.extra == {}


def test_dumps_stays_canonical_with_unknown_fields_present():
    text = PartRecord.from_dict(dict(FUTURE)).dumps()
    parsed = json.loads(text)
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert text.endswith("\n")
