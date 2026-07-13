import json

from stockroom.model.part import (
    Datasheet,
    LibRef,
    ModelRef,
    PartRecord,
    Provenance,
    Purchase,
    new_part_id,
)


def _sample() -> PartRecord:
    return PartRecord(
        id="tps62130rgtr",
        display_name="TPS62130 buck regulator",
        category="ICs",
        description="3-17V 3A step-down converter",
        tags=["buck", "regulator", "dcdc"],
        mpn="TPS62130RGTR",
        manufacturer="Texas Instruments",
        datasheet=Datasheet(file="tps62130rgtr.pdf", source_url="https://ti.com/x.pdf", fetched_at="2026-07-12T00:00:00Z"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/x", price_breaks=[[1, "3.21"]], stock=42, currency="USD", fetched_at="2026-07-12T00:00:00Z")],
        symbol=LibRef(lib="SR-ICs", name="TPS62130RGTR"),
        footprint=LibRef(lib="SR-ICs", name="VQFN-16"),
        provenance=Provenance(source="samacsys", source_url="https://componentsearchengine.com/x", original_zip_sha256="abc123", ingested_at="2026-07-12T00:00:00Z"),
    )


def test_round_trip_preserves_every_field():
    p = _sample()
    again = PartRecord.from_dict(p.to_dict())
    assert again == p


def test_dumps_is_canonical_json():
    text = _sample().dumps()
    assert text.endswith("\n")
    parsed = json.loads(text)
    # sort_keys => top-level keys are alphabetical, so diffs stay stable.
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert parsed["mpn"] == "TPS62130RGTR"
    assert parsed["purchase"][0]["stock"] == 42


def test_is_complete_false_when_model_missing():
    p = _sample()  # has full identity + assets + sourcing EXCEPT a 3D model
    assert p.model is None
    assert p.missing_fields() == ["3D model"]
    assert not p.is_complete()


def test_is_complete_true_with_full_passport():
    p = _sample()
    p.model = ModelRef(file="models/TPS62130RGTR.step")
    assert p.missing_fields() == []
    assert p.is_complete()


def test_missing_fields_lists_all_gaps_in_passport_order():
    p = PartRecord(id="x", display_name="", category="ICs")
    assert p.missing_fields() == [
        "name",
        "MPN",
        "manufacturer",
        "value/description",
        "symbol",
        "footprint",
        "3D model",
        "datasheet",
        "purchase link",
    ]


def test_loads_round_trip():
    p = _sample()
    assert PartRecord.loads(p.dumps()) == p


def test_defaults_are_empty_not_none():
    p = PartRecord(id="x", display_name="X", category="Other")
    d = p.to_dict()
    assert d["tags"] == []
    assert d["purchase"] == []
    assert d["datasheet"] is None
    assert d["model"] is None
    assert d["enrichment"] == {}


def test_specs_defaults_to_empty_dict():
    p = PartRecord(id="x", display_name="X", category="Other")
    assert p.specs == {}
    assert p.to_dict()["specs"] == {}


def test_specs_round_trips():
    p = _sample()
    p.specs = {"pinout": [{"pin": "1", "name": "VIN"}, {"pin": "2", "name": "GND"}]}
    again = PartRecord.from_dict(p.to_dict())
    assert again == p
    assert again.specs["pinout"][0]["name"] == "VIN"


def test_specs_is_not_a_gate_field():
    # a pinout (or any spec) is optional: adding it never changes completeness, and
    # a complete part with no specs stays complete.
    p = _sample()
    p.model = ModelRef(file="models/x.step")
    assert p.is_complete()
    p.specs = {"pinout": [{"pin": "1", "name": "VIN"}]}
    assert p.is_complete()
    assert "pinout" not in " ".join(p.missing_fields())
    incomplete = PartRecord(id="y", display_name="", category="ICs")
    before = incomplete.missing_fields()
    incomplete.specs = {"pinout": [{"pin": "1", "name": "A"}]}
    assert incomplete.missing_fields() == before


def test_new_part_id_slugifies(tmp_path):
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr"


def test_new_part_id_never_reuses(tmp_path):
    (tmp_path / "tps62130rgtr.json").write_text("{}")
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr-2"
    (tmp_path / "tps62130rgtr-2.json").write_text("{}")
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr-3"


def test_new_part_id_handles_empty_base(tmp_path):
    # a base that slugifies to empty still yields a usable id
    got = new_part_id(tmp_path, "///")
    assert got == "part"
