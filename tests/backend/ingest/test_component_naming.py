"""Spec-aware component naming: each category names a part by what it IS, with the defining specs
(X7R dielectric + voltage for a cap, power for a resistor, impedance@frequency for a ferrite,
frequency for a crystal, color for an LED), leading with a concise function for actives. Cases use
the real distributor spec shapes (units, parentheticals, plurals) the library actually carries."""

from __future__ import annotations

from stockroom.ingest.component_naming import propose_component_name


def test_resistor_value_tolerance_power_package():
    specs = {"Resistance": "100 kOhms", "Tolerance": "1%",
             "Power Rating": "100 mW (1/10 W)", "Case Code - in": "0603"}
    assert propose_component_name("Resistors", specs, "560112116004") == "100kΩ 1% 100mW 0603"


def test_capacitor_includes_dielectric_and_voltage():
    specs = {"Capacitance": "1 uF", "Dielectric": "X5R", "Voltage Rating DC": "50 VDC",
             "Tolerance": "10%", "Case Code - in": "0603"}
    assert propose_component_name("Capacitors", specs, "CC0603") == "1µF X5R 50V 10% 0603"


def test_capacitor_c0g_strips_the_np0_parenthetical():
    specs = {"Capacitance": "10 pF", "Dielectric": "C0G (NP0)", "Voltage Rating DC": "50 VDC",
             "Tolerance": "5%", "Case Code - in": "0402"}
    assert propose_component_name("Capacitors", specs, "x") == "10pF C0G 50V 5% 0402"


def test_ferrite_bead_is_impedance_at_test_frequency():
    specs = {"Impedance": "220 Ohms", "Test Frequency": "100 MHz",
             "Maximum DC Current": "2 A", "Package": "0805 (2012 metric)"}
    assert propose_component_name("Inductors", specs, "742792022") == "Ferrite Bead 220Ω@100MHz 2A 0805"


def test_power_inductor_value_tolerance_current():
    specs = {"Inductance": "1 uH", "Tolerance": "20%", "Maximum DC Current": "10.25 A"}
    assert propose_component_name("Inductors", specs, "74438357010") == "1µH 20% 10.25A Power Inductor"


def test_crystal_leads_with_frequency():
    specs = {"Frequency": "25 MHz", "Load Capacitance": "18 pF", "Package": "3.2 mm x 2.5 mm"}
    assert propose_component_name("Crystals & Oscillators", specs, "ABM8") == "25MHz Crystal 18pF 3.2x2.5mm"


def test_led_uses_illumination_color():
    specs = {"Illumination Color": "Green", "Vf - Forward Voltage": "3.2 V",
             "Package": "0603 (1608 metric)"}
    assert propose_component_name("Diodes", specs, "150060GS75000") == "Green LED 3.2V 0603"


def test_transistor_polarity_type_voltage_mpn():
    specs = {"Transistor Polarity": "N-Channel", "Product Category": "MOSFETs",
             "Vds - Drain-Source Breakdown Voltage": "60 V", "Package": "SOT-23-3"}
    assert propose_component_name("Transistors", specs, "2N7002") == "N-Channel MOSFET 60V 2N7002 SOT-23-3"


def test_connector_positions_are_per_row():
    specs = {"Number of Rows": "2 Row", "Number of Positions": "120 Position",
             "Contact Gender": "Pin (Male)", "Pitch": "0.5 mm (0.0197 in)", "Type": "Pin Strip"}
    assert propose_component_name("Connectors", specs, "QSH-060") == "Pin Header 2x60 0.5mm"


def test_switch_keeps_a_single_switch_suffix():
    specs = {"Type": "Slide Switch", "Contact Form": "SPDT"}
    assert propose_component_name("Switches", specs, "EG1218") == "SPDT Slide Switch EG1218"


def test_ic_verbose_product_type_is_shortened():
    specs = {"Product Type": "Encoders, Decoders, Multiplexers & Demultiplexers", "Package": "TSSOP-16"}
    assert propose_component_name("ICs", specs, "SN74LVC138AQPWREP") == "Encoder SN74LVC138AQPWREP TSSOP-16"


def test_junk_product_type_falls_back_to_type():
    specs = {"Product Type": "Tray", "Type": "Cylindrical Battery Contacts"}
    assert propose_component_name("Electromechanical", specs, "1043") == "Cylindrical Battery Contact 1043"


def test_empty_specs_degrade_to_mpn():
    assert propose_component_name("ICs", {}, "STM32H753ZIT6") == "STM32H753ZIT6"
