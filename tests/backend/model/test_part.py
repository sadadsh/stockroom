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


def _passive_sample() -> PartRecord:
    # A file-less passive: symbol/footprint reference KiCad STOCK libs (Device:R,
    # Resistor_SMD:R_0603_1608Metric), no owned 3D model, a datasheet URL (no PDF),
    # and a Mouser purchase link. This is the "drop the MPN, no files" record.
    return PartRecord(
        id="erj-p03f1101v",
        display_name="ERJ-P03F1101V",
        category="Resistors",
        description="Resistor, 1.1 kOhm, 1%, 0603",
        mpn="ERJ-P03F1101V",
        manufacturer="Panasonic",
        passive=True,
        symbol=LibRef(lib="Device", name="R"),
        footprint=LibRef(lib="Resistor_SMD", name="R_0603_1608Metric"),
        datasheet=Datasheet(source_url="https://mouser.com/erj.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V")],
        specs={"Resistance": "1.1 kOhm", "Tolerance": "1%", "Package": "0603", "Power": "0.2 W"},
    )


def test_passive_is_complete_with_stock_refs_url_datasheet_and_no_owned_model():
    p = _passive_sample()
    assert p.model is None  # no owned 3D file; the stock footprint carries its own
    assert p.missing_fields() == []
    assert p.is_complete()


def test_passive_flag_round_trips():
    p = _passive_sample()
    again = PartRecord.from_dict(p.to_dict())
    assert again.passive is True
    assert again == p


def test_datasheet_url_alone_satisfies_the_gate_for_any_part():
    p = _sample()
    p.datasheet = Datasheet(source_url="https://ti.com/x.pdf")  # URL, no downloaded PDF
    assert "datasheet" not in " ".join(p.missing_fields())


def test_assets_no_longer_gate_a_non_passive_part():
    # owner 2026-07-16: symbol/footprint/3D model no longer gate entry. A non-passive
    # with full identity + datasheet + purchase is COMPLETE even with no owned model,
    # and missing_assets() reports what can still be attached after the fact.
    p = _sample()
    p.model = None
    assert p.passive is False
    assert p.missing_fields() == []
    assert p.is_complete()
    assert p.missing_assets() == ["3D model"]  # symbol+footprint present, model not


def test_missing_assets_lists_every_unattached_asset():
    p = PartRecord(id="x", display_name="X", category="ICs")
    assert p.missing_assets() == ["symbol", "footprint", "3D model"]
    p.symbol = LibRef(lib="SR-ICs", name="X")
    assert p.missing_assets() == ["footprint", "3D model"]


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


def test_is_complete_true_without_owned_assets():
    # a part with identity + description + datasheet + purchase is complete even with
    # no symbol/footprint/3D model (assets are attached after entry now).
    p = _sample()
    assert p.model is None
    assert p.missing_fields() == []
    assert p.is_complete()


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
