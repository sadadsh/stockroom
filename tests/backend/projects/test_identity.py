from stockroom.projects.identity import has_real_mpn, part_identity, strict_mpn


def test_strict_mpn_reads_a_dedicated_part_number_field():
    assert strict_mpn({"MPN": "TPS62130RGTR"}) == "TPS62130RGTR"
    assert strict_mpn({"Manufacturer Part Number": "LM358"}) == "LM358"
    assert strict_mpn({"Mouser Part No": "595-LM358"}) == "595-LM358"


def test_strict_mpn_never_falls_back_to_value():
    # a generic passive that only carries a Value has no real MPN
    assert strict_mpn({"Value": "10k", "Reference": "R1"}) is None


def test_strict_mpn_ignores_placeholders():
    for placeholder in ("~", "-", "n/a", "None", ""):
        assert strict_mpn({"MPN": placeholder}) is None


def test_strict_mpn_is_key_normalization_insensitive():
    # keys are matched case/space/underscore/hyphen-folded
    assert strict_mpn({"mpn": "A"}) == "A"
    assert strict_mpn({"Part_Number": "B"}) == "B"
    assert strict_mpn({"PART-NO": "C"}) == "C"


def test_part_identity_picks_manufacturer_and_mpn():
    ident = part_identity({"Manufacturer": "Texas Instruments", "MPN": "TPS62130"})
    assert ident["manufacturer"] == "Texas Instruments"
    assert ident["mpn"] == "TPS62130"


def test_part_identity_mpn_falls_back_to_value_then_to_the_fallback():
    # Value is an MPN fallback (loose), unlike strict_mpn
    assert part_identity({"Value": "10k"})["mpn"] == "10k"
    # nothing usable => the caller's fallback (e.g. a footprint stem)
    assert part_identity({}, fallback="R_0402")["mpn"] == "R_0402"
    assert part_identity({})["mpn"] is None


def test_part_identity_drops_placeholder_manufacturer():
    assert part_identity({"Manufacturer": "~"})["manufacturer"] is None


def test_has_real_mpn_prefers_an_explicit_flag():
    assert has_real_mpn({"has_real_mpn": True, "mpn": "X"}) is True
    assert has_real_mpn({"has_real_mpn": False, "mpn": "X"}) is False


def test_has_real_mpn_infers_when_no_flag():
    assert has_real_mpn({"mpn": "TPS62130"}) is True
    assert has_real_mpn({"mpn": ""}) is False
