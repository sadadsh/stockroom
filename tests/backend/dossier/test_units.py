"""Unit normalization: one comparable magnitude behind every engineering value."""

from __future__ import annotations

from stockroom.dossier.categories import resolve_schema
from stockroom.dossier.specifications import build_specifications
from stockroom.dossier.units import comparable_key, is_empty, normalize, parse_quantity
from tests.backend.dossier import records


def test_si_prefixes_scale_to_the_base_unit():
    assert parse_quantity("1.1 kOhms") == (1100.0, "Ω")
    assert parse_quantity("200 mW") == (0.2, "W")
    assert parse_quantity("2.2uF") == (2.2e-6, "F")
    assert parse_quantity("480 MHz") == (480_000_000.0, "Hz")


def test_a_spelled_out_unit_and_its_symbol_are_the_same_unit():
    assert parse_quantity("100 ohm") == parse_quantity("100 Ω")
    assert parse_quantity("5 volts") == (5.0, "V")


def test_length_is_normalized_so_inches_and_millimetres_compare():
    assert parse_quantity("2.54mm") == (2.54, "mm")
    assert parse_quantity("0.1 in") == (2.54, "mm")


def test_a_range_keeps_both_bounds_and_its_unit():
    result = normalize("-40C to 125C")
    assert result.value_type == "range"
    assert result.normalized == [-40.0, 125.0]
    assert result.unit == "°C"


def test_a_range_written_with_a_tilde_reads_the_same_way():
    assert normalize("1.65V ~ 5.5V").normalized == [1.65, 5.5]


def test_the_sources_own_wording_survives_normalization():
    assert normalize("1.1 kOhms").display == "1.1 kOhms"


def test_a_value_with_no_readable_magnitude_is_text_not_a_fabricated_number():
    result = normalize("Thick Film")
    assert result.value_type == "text"
    assert result.normalized is None


def test_two_scales_of_one_measurement_do_not_read_as_a_disagreement():
    assert comparable_key(normalize("0.5 V")) == comparable_key(normalize("500 mV"))
    assert comparable_key(normalize("1.1 kOhms")) == comparable_key(normalize("1100 ohm"))


def test_two_genuinely_different_values_still_read_as_a_disagreement():
    assert comparable_key(normalize("1.1 kOhms")) != comparable_key(normalize("1.2 kOhms"))


def test_a_distributors_empty_in_disguise_value_is_empty():
    assert is_empty("N/A")
    assert is_empty("Not Available")
    assert is_empty("")
    assert not is_empty("0")
    assert not is_empty(0.0)


def test_the_expected_unit_only_ever_fills_a_gap():
    with_own_unit = normalize("200 mW", expected_unit="W")
    assert with_own_unit.unit == "W" and with_own_unit.normalized == 0.2
    bare = normalize("100", expected_unit="Ω")
    assert bare.unit == "Ω" and bare.normalized == 100.0


def test_the_category_unit_reaches_the_projected_specification():
    record = records.resistor(specs={"Resistance": "1.1 kOhms"})
    specifications = build_specifications(record, resolve_schema(record))
    item = records.by_key(specifications.records)["resistance"]
    assert item["unit"] == "Ω"
    assert item["normalizedValue"] == 1100.0
    assert item["displayValue"] == "1.1 kOhms"


def test_a_declared_enum_is_not_turned_into_a_number_because_it_parses():
    assert normalize("0603", value_type="enum").value_type == "enum"
