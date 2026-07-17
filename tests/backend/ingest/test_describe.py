"""Clean name + description derivation from a part's scraped specs (describe.py)."""

from __future__ import annotations

from stockroom.ingest.describe import (
    apply_clean_identity,
    clean_description,
    clean_display_name,
    format_value,
    is_machine_name,
    is_placeholder_description,
)

# specs sampled from the owner's real library records
RESISTOR = {
    "Resistance": "1.1 kOhms",
    "Power Rating": "200 mW (1/5 W)",
    "Package": "0603",
    "Product": "Thick Film Chip Resistors",
    "Qualification": "AEC-Q200",
}
CAPACITOR = {
    "Capacitance": "1 uF",
    "Dielectric": "X5R",
    "Package": "0603",
    "Product": "Multilayer Ceramic Capacitors MLCC - SMD/SMT",
}
INDUCTOR = {"Inductance": "6.8 uH", "Package": "0805", "Product": "Fixed Inductors"}
LED = {"Package": "0805", "Product": "Green LEDs"}


class TestFormatValue:
    def test_ohms_take_the_omega_glyph_keeping_the_prefix(self):
        assert format_value("1.1 kOhms") == "1.1 kΩ"
        assert format_value("100 Ohms") == "100 Ω"
        assert format_value("255 kOhms") == "255 kΩ"

    def test_micro_farads_and_henries_take_the_mu_glyph(self):
        assert format_value("1 uF") == "1 µF"
        assert format_value("6.8 uH") == "6.8 µH"
        assert format_value("0.1 uF") == "0.1 µF"

    def test_picofarads_pass_through_spaced(self):
        assert format_value("1000 pF") == "1000 pF"

    def test_unspaced_magnitude_gets_a_space(self):
        assert format_value("1uF") == "1 µF"

    def test_empty_is_empty(self):
        assert format_value("") == ""


class TestCleanDisplayName:
    def test_resistor_reads_value_plus_kind(self):
        assert clean_display_name(RESISTOR, "Resistors") == "1.1 kΩ Resistor"

    def test_capacitor_and_inductor(self):
        assert clean_display_name(CAPACITOR, "Capacitors") == "1 µF Capacitor"
        assert clean_display_name(INDUCTOR, "Inductors") == "6.8 µH Inductor"

    def test_led_reads_colour_plus_led(self):
        assert clean_display_name(LED, "Diodes") == "Green LED"

    def test_no_clean_name_for_a_valueless_non_led(self):
        # a connector carries no headline value and is not an LED -> keep the old name
        assert clean_display_name({"Product": "Headers"}, "Connectors") is None

    def test_no_clean_name_when_the_value_spec_is_missing(self):
        assert clean_display_name({"Package": "0603"}, "Resistors") is None


class TestCleanDescription:
    def test_resistor_description_is_built_from_specs(self):
        assert (
            clean_description(RESISTOR, "Resistors")
            == "Thick Film Chip Resistor, 1.1 kΩ, 200 mW, 0603"
        )

    def test_capacitor_description_includes_the_dielectric(self):
        desc = clean_description(CAPACITOR, "Capacitors")
        assert desc.startswith("Multilayer Ceramic Capacitor")
        assert "1 µF" in desc and "0603" in desc and desc.endswith("X5R")

    def test_non_passive_uses_the_singularized_product(self):
        assert clean_description({"Product": "Slide Switches"}, "Switches") == "Slide Switch"
        assert clean_description({"Product Category": "MOSFETs"}, "Transistors") == "MOSFET"

    def test_nothing_usable_returns_none(self):
        assert clean_description({}, "Connectors") is None

    def test_a_packaging_term_is_not_a_description(self):
        # a module whose only "Product" is a shipping term gets no description, not "Tape"
        assert clean_description({"Product": "Tapes"}, "Modules") is None


class TestIsPlaceholderDescription:
    def test_kicad_symbol_blurbs_are_placeholders(self):
        assert is_placeholder_description("Resistor, small symbol")
        assert is_placeholder_description("capacitor, small US symbol")
        assert is_placeholder_description(
            "Generic connector, single row, 01x04, script generated"
        )

    def test_bare_kind_words_and_numbers_and_empty_are_placeholders(self):
        assert is_placeholder_description("Resistor")
        assert is_placeholder_description("capacitor")
        assert is_placeholder_description("358")
        assert is_placeholder_description("")
        assert is_placeholder_description(None)

    def test_a_real_description_is_not_a_placeholder(self):
        assert not is_placeholder_description("Thick Film Chip Resistor, 1.1 kΩ, 200 mW, 0603")
        assert not is_placeholder_description("Slide Switches")
        assert not is_placeholder_description("Light emitting diode")


class TestIsMachineName:
    def test_a_name_embedding_the_mpn_or_manufacturer_is_machine(self):
        assert is_machine_name("1.10k 1% 0603 Panasonic ERJ-P03F1101V", "ERJ-P03F1101V", "Panasonic")
        assert is_machine_name("Conn_01x04_Pin Wurth 61300411121", "61300411121", "Wurth")

    def test_a_clean_or_custom_name_is_not_machine(self):
        assert not is_machine_name("1.1 kΩ Resistor", "ERJ-P03F1101V", "Panasonic")
        assert not is_machine_name("My Favourite Part", "ERJ-P03F1101V", "Panasonic")


class TestApplyCleanIdentity:
    def test_new_scraped_passive_gets_clean_name_and_description(self):
        name, desc = apply_clean_identity(
            RESISTOR,
            "Resistors",
            display_name="1.10k 1% 0603 Panasonic ERJ-P03F1101V",
            description="Resistor, small symbol",
            mpn="ERJ-P03F1101V",
            manufacturer="Panasonic",
        )
        assert name == "1.1 kΩ Resistor"
        assert desc == "Thick Film Chip Resistor, 1.1 kΩ, 200 mW, 0603"

    def test_custom_name_and_real_description_pass_through(self):
        name, desc = apply_clean_identity(
            RESISTOR,
            "Resistors",
            display_name="My Favourite Resistor",
            description="A hand-written note",
            mpn="ERJ-P03F1101V",
            manufacturer="Panasonic",
        )
        assert name == "My Favourite Resistor"
        assert desc == "A hand-written note"
