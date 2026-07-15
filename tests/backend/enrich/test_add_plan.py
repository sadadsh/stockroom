"""The passive-determination step of the unified "Add A Part" flow.

`passive_add_plan` reads the fields a product page (or an MPN lookup) yielded and
decides whether the part is an addable file-less passive, and if so extracts the
{kind, package, value, tolerance} the file-less passive add needs. It is the "is
this passive or not" gate the owner's one-paste-a-link workflow branches on, so a
false positive (a MOSFET read as a resistor) would wrongly tell the user "no files
needed" - the detection is deliberately conservative.
"""

from __future__ import annotations

from stockroom.enrich.passive import passive_add_plan


def test_non_decoding_mouser_resistor_gets_a_resistor_plan():
    # A Wurth / Panasonic catalog number that no offline decoder knows, but whose
    # Mouser page gave the parametric specs: it must still resolve to a resistor plan
    # (the owner's real BOM is mostly parts exactly like this).
    plan = passive_add_plan(
        mpn="560112116151",
        category="",
        package="0603 (1608 Metric)",
        specs={
            "Resistance": "118 Ohms",
            "Tolerance": "1%",
            "Package / Case": "0603 (1608 Metric)",
        },
        description="Thick Film Resistors - SMD 118 Ohms 1% 0603",
    )
    assert plan == {
        "kind": "resistor",
        "package": "0603",
        "value": "118 Ohms",
        "tolerance": "1%",
    }


def test_capacitor_from_capacitance_spec():
    plan = passive_add_plan(
        mpn="GRM188R71H104KA93D",
        category="",
        package="",
        specs={"Capacitance": "100 nF", "Tolerance": "10%", "Package / Case": "0603"},
        description="Multilayer Ceramic Capacitors MLCC - SMD/SMT 0603 100nF",
    )
    assert plan is not None
    assert plan["kind"] == "capacitor"
    assert plan["package"] == "0603"
    assert plan["value"] == "100 nF"
    assert plan["tolerance"] == "10%"


def test_inductor_from_inductance_spec():
    plan = passive_add_plan(
        mpn="LQW18AN10NJ00D",
        category="Inductors",
        package="0603",
        specs={"Inductance": "10 nH", "Tolerance": "5%"},
        description="",
    )
    assert plan is not None
    assert plan["kind"] == "inductor"
    assert plan["value"] == "10 nH"


def test_decoding_mpn_is_passive_even_with_no_page_specs():
    # A Yageo RC part decodes offline, so it is a resistor by MPN family alone; the
    # plan can leave package blank (the file-less add decodes it from the MPN).
    plan = passive_add_plan(
        mpn="RC0402FR-0710KL", category="", package="", specs={}, description=""
    )
    assert plan is not None
    assert plan["kind"] == "resistor"


def test_passive_category_alone_is_enough():
    plan = passive_add_plan(
        mpn="UNKNOWN123", category="Resistors", package="0805", specs={}, description=""
    )
    assert plan is not None
    assert plan["kind"] == "resistor"
    assert plan["package"] == "0805"


def test_mosfet_on_resistance_is_not_a_resistor():
    # "On-Resistance" / "RDS(on)" is a MOSFET spec, NOT a resistor: an exact-key match
    # on "Resistance" must not fire, or the flow would tell the user a MOSFET needs no
    # symbol/footprint/3D.
    plan = passive_add_plan(
        mpn="IRLML6344TRPBF",
        category="Transistors",
        package="SOT-23",
        specs={
            "Drain to Source Voltage (Vdss)": "30 V",
            "On-Resistance (RDS(on)) @ 10V": "29 mOhms",
        },
        description="MOSFET N-Ch 30V 5A SOT-23",
    )
    assert plan is None


def test_connector_is_not_passive():
    plan = passive_add_plan(
        mpn="TSW-108-07-G-S",
        category="Connectors",
        package="",
        specs={"Number of Positions": "8", "Pitch": "2.54 mm"},
        description="Headers & Wire Housings 8 POS",
    )
    assert plan is None


def test_ferrite_bead_is_not_file_less_passive():
    # A ferrite bead is detected as passive by category but has no R/C/L stock
    # footprint family here, so it is routed to the asset-drop path (None), honestly.
    plan = passive_add_plan(
        mpn="BLM18PG221SN1D",
        category="Ferrite Beads",
        package="0603",
        specs={"Impedance": "220 Ohms", "Package / Case": "0603"},
        description="Ferrite Beads 220 Ohm",
    )
    assert plan is None


def test_package_forms_normalize_to_eia_case():
    for raw in ("0402 (1005 Metric)", "0402", "R0402", "0402 (1005)"):
        plan = passive_add_plan(
            mpn="X", category="Resistors", package=raw, specs={}, description=""
        )
        assert plan is not None
        assert plan["package"] == "0402", raw


def test_package_read_from_specs_when_arg_blank():
    plan = passive_add_plan(
        mpn="X",
        category="Resistors",
        package="",
        specs={"Package / Case": "1206 (3216 Metric)"},
        description="",
    )
    assert plan is not None
    assert plan["package"] == "1206"


def test_unresolvable_package_left_blank_but_still_passive():
    # A detected passive whose page package is not a stock EIA case still returns a
    # plan (kind known) with a blank package, so the UI can reveal a package picker
    # rather than silently dropping the part.
    plan = passive_add_plan(
        mpn="X",
        category="Resistors",
        package="Nonstandard",
        specs={"Resistance": "10 kOhms"},
        description="",
    )
    assert plan is not None
    assert plan["kind"] == "resistor"
    assert plan["package"] == ""
    assert plan["value"] == "10 kOhms"


def test_empty_inputs_are_not_passive():
    assert passive_add_plan(mpn="", category="", package="", specs={}, description="") is None
