"""The record's home for every value a source offered but did not win with (Batch 3, punch 2/9).

Before this, enrichment resolved each single-slot field to whichever source ran first and
DROPPED the rest with no record anywhere - so a part could never show both distributors'
descriptions, and nothing said which distributor a stored value came from.
"""
from stockroom.model.part import PartRecord, SourcedValue


def _record(**kw) -> PartRecord:
    return PartRecord(id="p1", display_name="P", category="ICs", **kw)


def test_alternates_round_trip_through_json():
    rec = _record(
        description="3A Buck Converter",
        alternates={
            "description": [
                SourcedValue("3A Buck Converter", "mouser", "high"),
                SourcedValue("Step-Down Regulator, 3 A", "digikey", "high"),
            ],
            "Package": [
                SourcedValue("WSON-8", "mouser", "high"),
                SourcedValue("VSON-8", "digikey", "high"),
            ],
        },
    )
    back = PartRecord.loads(rec.dumps())
    assert [(a.value, a.source) for a in back.alternates["description"]] == [
        ("3A Buck Converter", "mouser"),
        ("Step-Down Regulator, 3 A", "digikey"),
    ]
    assert [a.value for a in back.alternates["Package"]] == ["WSON-8", "VSON-8"]


def test_a_record_with_no_alternates_carries_no_alternates_key():
    """Records are one JSON file per part and diffed by a human in git. A part that never
    saw a disagreement must not gain an empty key, or adopting this would rewrite every
    part in the owner's library for nothing."""
    import json

    assert "alternates" not in json.loads(_record().dumps())


def test_a_non_string_alternate_keeps_its_type():
    """tariff_rate is a float on the wire (the page's own DecTariffUnitPrice ratio) and
    0.0 is a MEANINGFUL value - a confirmed no-tariff part, not a missing one."""
    rec = _record(alternates={"tariff_rate": [SourcedValue(0.0, "mouser", "high")]})
    back = PartRecord.loads(rec.dumps())
    assert back.alternates["tariff_rate"][0].value == 0.0


def test_alternates_from_a_newer_peer_survive_our_write_including_keys_we_cannot_read():
    """The same guarantee `PartRecord.extra` gives the record, one level down. Peers share
    these files through git and BOTH write them, so rewriting a neighbour's entry must not
    quietly strip the half of it we could not read - `weight` here is a key this build has
    never heard of and must still be on disk afterwards."""
    import json

    raw = _record().to_dict()
    raw["alternates"] = {"some_future_field": [{"value": "x", "source": "vendor3",
                                               "confidence": "high", "weight": 7}]}
    back = PartRecord.from_dict(raw)
    again = json.loads(back.dumps())
    entry = again["alternates"]["some_future_field"][0]
    assert entry["value"] == "x" and entry["source"] == "vendor3"
    assert entry["weight"] == 7, "an unknown key on the entry was dropped on rewrite"
