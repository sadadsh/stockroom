from stockroom.model.part import AltiumRef, PartRecord, altium_assets_ready


def test_altium_ref_defaults_tool_altium():
    assert AltiumRef(lib="BQ24074RGTT.SchLib", name="BQ24074RGTT").tool == "altium"


def test_altium_refs_round_trip():
    r = PartRecord(
        id="x", display_name="n", category="ICs",
        altium_symbol=AltiumRef(lib="BQ24074RGTT.SchLib", name="BQ24074RGTT"),
        altium_footprint=AltiumRef(lib="BQ24074RGTT.PcbLib", name="VQFN-16"),
    )
    r2 = PartRecord.loads(r.dumps())
    assert r2.altium_symbol == r.altium_symbol
    assert r2.altium_footprint == r.altium_footprint


def test_altium_refs_default_none_and_round_trip():
    r2 = PartRecord.loads(PartRecord(id="x", display_name="n", category="ICs").dumps())
    assert r2.altium_symbol is None and r2.altium_footprint is None


def test_assets_ready_requires_both_named_refs():
    base = PartRecord(id="x", display_name="n", category="ICs")
    assert altium_assets_ready(base) is False
    base.altium_symbol = AltiumRef(lib="a.SchLib", name="A")
    assert altium_assets_ready(base) is False  # footprint still missing
    base.altium_footprint = AltiumRef(lib="a.PcbLib", name="FP")
    assert altium_assets_ready(base) is True
    base.altium_footprint = AltiumRef(lib="a.PcbLib", name="")  # unnamed = not ready
    assert altium_assets_ready(base) is False
