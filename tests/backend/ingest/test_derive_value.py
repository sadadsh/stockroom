from stockroom.ingest.component_naming import derive_display_value, derive_value
from stockroom.model.part import PartRecord


def _rec(category, specs=None, mpn="MPN1"):
    return PartRecord(id="x", display_name="n", category=category, mpn=mpn, specs=specs or {})


def test_resistor_value_drops_ohm_symbol():
    r = _rec("Resistors", {"Resistance": "5.05 kOhms"})
    assert derive_value(r) == "5.05k"


def test_capacitor_value_keeps_farad_unit():
    r = _rec("Capacitors", {"Capacitance": "1 uF"})
    assert derive_value(r) == "1µF"


def test_inductor_value_from_inductance():
    r = _rec("Inductors", {"Inductance": "4.7 uH"})
    assert derive_value(r) == "4.7µH"


def test_ferrite_bead_value_from_impedance():
    r = _rec("Inductors", {"Impedance": "600 Ohms"})
    assert derive_value(r) == "600Ω"


def test_active_value_is_mpn():
    r = _rec("ICs", {}, mpn="BQ24074RGTT")
    assert derive_value(r) == "BQ24074RGTT"


def test_passive_with_no_defining_spec_is_blank_not_guessed():
    r = _rec("Resistors", {}, mpn="CRCW06035K05FKEA")
    assert derive_value(r) == ""


# -- derive_display_value: the human-facing value that KEEPS the Ω unit (FIX-07 backend) --


def test_display_value_resistor_keeps_ohm_while_derive_value_strips_it():
    r = _rec("Resistors", {"Resistance": "5.05 kOhms"})
    assert derive_display_value(r) == "5.05kΩ"  # human display keeps the unit
    assert derive_value(r) == "5.05k"  # schematic/BOM convention still strips it


def test_display_value_capacitor_matches_derive_value():
    r = _rec("Capacitors", {"Capacitance": "1 uF"})
    assert derive_display_value(r) == derive_value(r) == "1µF"


def test_display_value_inductor_matches_derive_value():
    r = _rec("Inductors", {"Inductance": "4.7 uH"})
    assert derive_display_value(r) == derive_value(r) == "4.7µH"


def test_display_value_ferrite_bead_matches_derive_value():
    r = _rec("Inductors", {"Impedance": "600 Ohms"})
    assert derive_display_value(r) == derive_value(r) == "600Ω"


def test_display_value_active_matches_derive_value():
    r = _rec("ICs", {}, mpn="BQ24074RGTT")
    assert derive_display_value(r) == derive_value(r) == "BQ24074RGTT"


def test_display_value_resistor_without_spec_is_blank():
    r = _rec("Resistors", {}, mpn="CRCW06035K05FKEA")
    assert derive_display_value(r) == derive_value(r) == ""
