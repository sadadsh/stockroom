"""Spec-aware component naming: each category names a part by what it IS, with the defining specs
(X7R dielectric + voltage for a cap, power for a resistor, impedance@frequency for a ferrite,
frequency for a crystal, color for an LED), leading with a concise function for actives. Cases use
the real distributor spec shapes (units, parentheticals, plurals) the library actually carries."""

from __future__ import annotations

import pytest

from stockroom.ingest.component_naming import _singular, propose_component_name


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
    # MPN dropped, same standing rule as the switch above: the title already shows it.
    assert propose_component_name("Transistors", specs, "2N7002") == "N-Channel MOSFET 60V SOT-23-3"


def test_connector_positions_are_per_row():
    specs = {"Number of Rows": "2 Row", "Number of Positions": "120 Position",
             "Contact Gender": "Pin (Male)", "Pitch": "0.5 mm (0.0197 in)", "Type": "Pin Strip"}
    assert propose_component_name("Connectors", specs, "QSH-060") == "Pin Header 2x60 0.5mm"


def test_switch_keeps_a_single_switch_suffix():
    # The trailing MPN is GONE, and that is the owner's standing rule rather than a regression:
    # "the MPN always shows under the title so u can humanize the name as much as possible".
    # Every other category had already dropped it; Switches and Transistors were the last two
    # branches still trailing it, so two categories named their parts unlike all the others.
    specs = {"Type": "Slide Switch", "Contact Form": "SPDT"}
    assert propose_component_name("Switches", specs, "EG1218") == "SPDT Slide Switch"


def test_ic_verbose_product_type_is_shortened():
    specs = {"Product Type": "Encoders, Decoders, Multiplexers & Demultiplexers", "Package": "TSSOP-16"}
    assert propose_component_name("ICs", specs, "SN74LVC138AQPWREP") == "Encoder TSSOP-16"


def test_junk_product_type_falls_back_to_type():
    specs = {"Product Type": "Tray", "Type": "Cylindrical Battery Contacts"}
    assert propose_component_name("Electromechanical", specs, "1043") == "Cylindrical Battery Contact"


def test_empty_specs_degrade_to_mpn():
    assert propose_component_name("ICs", {}, "STM32H753ZIT6") == "STM32H753ZIT6"


# -- the name is HUMAN, built from the richest category field (owner, 2026-07-26) ----------
#
# "the MPN always shows under the title so u can humanize the name as much as possible based off
# the description or specs".


def test_a_protection_diode_is_named_by_what_it_IS_not_by_a_parameter():
    """The owner's real part read "Steering TPD6E05U06RVZR USON-14".

    `Steering` is a fragment of `Type = "Steering (Rail to Rail)"`, which is a TVS PARAMETER rather
    than a function, while the SAME record carried `Product Category = "ESD Protection Diodes / TVS
    Diodes"` and `Number of Channels = 6` that nothing ever read. Ordering the descriptor sources so
    the category fields beat `Type` is the whole fix, and it is general: any part whose `Type` holds
    a parameter now falls through to a field that holds a purpose.
    """
    specs = {
        "Type": "Steering (Rail to Rail)",
        "Product Category": "ESD Protection Diodes / TVS Diodes",
        "Number of Channels": "6",
        "Package": "USON-14",
    }
    assert propose_component_name("Other", specs, "TPD6E05U06RVZR") == (
        "6-Channel ESD Protection Diode USON-14"
    )


def test_a_slash_separated_category_takes_its_FIRST_segment():
    """"ESD Protection Diodes / TVS Diodes" is two names for one thing. Only `&`, `,` and ` - `
    were treated as separators, so the whole string would have become the name."""
    specs = {"Product Category": "ESD Protection Diodes / TVS Diodes", "Package": "SOT-23"}
    assert propose_component_name("ICs", specs, "X") == "ESD Protection Diode SOT-23"


def test_a_single_channel_part_does_not_say_so():
    """"1-Channel" is noise; a channel count earns its place only when there is more than one."""
    specs = {"Product Category": "Op Amps", "Number of Channels": "1", "Package": "SOT-23-5"}
    assert propose_component_name("ICs", specs, "X") == "Op Amp SOT-23-5"


def test_a_junk_product_type_falls_THROUGH_to_a_real_one():
    """`Product Type = "Tray"` describes the packaging, not the part. It must not win over a `Type`
    that actually says what the thing is."""
    specs = {"Product Type": "Tray", "Type": "Cylindrical Battery Contacts"}
    assert propose_component_name("Electromechanical", specs, "1043") == "Cylindrical Battery Contact"


def test_a_record_with_no_usable_description_still_degrades_to_its_MPN():
    """The floor. Humanising must never make a part ANONYMOUS: with nothing to describe it, the
    name is the MPN exactly as before."""
    assert propose_component_name("ICs", {}, "STM32H753ZIT6") == "STM32H753ZIT6"


def test_the_human_description_is_the_last_resort_before_the_mpn():
    specs = {"Package": "SOT-23"}
    assert propose_component_name(
        "ICs", specs, "X", "Low-dropout regulator, 3.3V fixed"
    ) == "Low-dropout regulator SOT-23"


def test_a_PASSIVE_still_leads_with_its_VALUE_and_never_shows_an_mpn():
    """The half that must NOT change. A resistor's identity is its value, and the owner has
    consistently wanted "100kΩ 1% 0603"."""
    specs = {"Resistance": "100 kOhms", "Tolerance": "1%", "Power Rating": "0.1 W",
             "Case Code - in": "0603"}
    assert propose_component_name("Resistors", specs, "RC0603FR-07100KL") == "100kΩ 1% 0.1W 0603"


def test_an_LED_keeps_its_colour_lead():
    """A named colour is what a person scans an LED list for, so that branch keeps its lead."""
    specs = {"Illumination Color": "Green", "Vf - Forward Voltage": "3.2 V", "Package": "0603"}
    assert propose_component_name("Diodes", specs, "150060GS75000") == "Green LED 3.2V 0603"


@pytest.mark.parametrize(
    "word,expected",
    [
        ("Diodes", "Diode"), ("Op Amps", "Op Amp"), ("ESD Suppressors", "ESD Suppressor"),
        ("Thyristors", "Thyristor"), ("ESD Protection Diodes", "ESD Protection Diode"),
        # Singular words that merely END in "s". Each of these was measured breaking: "Lens"
        # became "Len" and "Series" became "Serie", and "Series" is a spec key on a real record.
        ("Bus", "Bus"), ("Class", "Class"), ("Chassis", "Chassis"), ("Gas", "Gas"),
        ("Lens", "Lens"), ("Series", "Series"),
        # A plural MODIFIER must survive; only the head noun is singularised.
        ("Communications Modules", "Communications Module"),
        ("Analog", "Analog"), ("IC", "IC"),
    ],
)
def test_the_generic_singulariser_only_touches_a_real_plural_head_noun(word, expected):
    """The explicit map cannot keep up with the vocabulary distributors invent, so a generic rule
    backs it. A generic rule is exactly where over-reach happens, hence the negative cases."""
    assert _singular(word) == expected


# --- Names measured on the owner's REAL library, 2026-07-26 -----------------------------------
#
# Owner, after adding five parts through the app: "names oversimplified". They were, and each had
# a distinct cause. Every spec bag below is copied from the record on their disk, not invented.

def test_a_compound_type_keeps_its_head_noun():
    """`INA226AIDGST` was named **"Current"**.

    Its Product Category is "Current & Power Monitors & Regulators". `_short_type` splits a list
    on "&" and keeps the first item - correct for "Buffers & Line Drivers", wrong here, because
    "Current" is a MODIFIER of the noun that follows, not a list entry. Splitting threw the head
    noun away and left an adjective as the part's name.

    The discriminator is exact and needs no word list: a real list of component types is written
    in the PLURAL ("Buffers & Line Drivers", "Encoders, Decoders"). A SINGULAR first segment is a
    modifier, so the phrase is kept whole.
    """
    name = propose_component_name("ICs", {
        "Product Category": "Current & Power Monitors & Regulators",
        "Supplier Device Package": "10-VSSOP",
    }, mpn="INA226AIDGST")
    assert "Current" in name and name != "Current"
    assert "Monitor" in name, f"the head noun was dropped: {name!r}"
    assert "10-VSSOP" in name


def test_a_genuine_list_still_takes_its_first_entry():
    """The behaviour the split exists for, which must not regress."""
    assert propose_component_name("ICs", {"Product Category": "Buffers & Line Drivers"},
                                  mpn="X") .startswith("Buffer")
    assert propose_component_name("ICs", {"Product Category": "Encoders, Decoders, Multiplexers"},
                                  mpn="X").startswith("Encoder")


def test_the_package_comes_from_the_keys_a_distributor_actually_uses():
    """Four of the owner's five parts had NO package in their name.

    `_pkg` read only "Case Code - in" or a bare "Package". A DigiKey record carries
    "Supplier Device Package" (the concise one: "SOT-23-5") and "Package / Case" (the verbose one:
    'SC-74A, SOT-753'), and only the one part whose record happened to have a bare "Package" key
    got a package in its name.
    """
    name = propose_component_name("ICs", {
        "Product Category": "Switching Voltage Regulators",
        "Package / Case": "14-PowerVFQFN",
        "Supplier Device Package": "14-VQFN-HR (2.5x3)",
    }, mpn="TPS62914RPYR")
    assert "Switching Voltage Regulator" in name
    assert "14-VQFN-HR" in name, f"no package in {name!r}"


def test_a_switch_reads_its_product_category_rather_than_falling_back_to_the_mpn():
    """`ADG714BRUZ` was named "ADG714BRUZ" - the namer produced nothing at all.

    The Switches branch consulted "Type", "Contact Form" and "Product Type"; this record states
    its function in "Product Category" ("Analog Switch ICs"), which that branch never read.
    """
    name = propose_component_name("Switches", {
        "Product Category": "Analog Switch ICs",
        "Supplier Device Package": "24-TSSOP",
    }, mpn="ADG714BRUZ")
    assert name != "ADG714BRUZ"
    assert "Switch" in name and "24-TSSOP" in name


def test_the_richest_record_is_unchanged():
    """The one part that was already named well must stay named exactly that."""
    assert propose_component_name("Diodes", {
        "Number of Channels": "6", "Product Category": "ESD Protection Diodes / TVS Diodes",
        "Package": "USON-14",
    }, mpn="TPD6E05U06RVZR") == "6-Channel ESD Protection Diode USON-14"
