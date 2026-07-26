"""Component-value normalization: turn the notation a schematic and a part record each use for a
passive's value into one comparable number, so the two sides can never disagree through different
parsers.

The rule is modeled on KiBoM's `units.compMatch` (the de facto KiCad BOM tool, MIT), which is the
practitioner reference for this exact problem: SI prefixes including the `u`/`µ`/`μ` spellings and
`meg`, the unit words for ohms/farads/henries, and the RKM / IEC 60062 convention where the prefix
letter stands in for the decimal point ("4k7" = 4700, "0R05" = 0.05). Adopted as the ALGORITHM, not
as a dependency: KiBoM is an application, and every packaged alternative was either far heavier than
50 lines of parsing (UliEngineering wants scipy) or could not read RKM at all (pint, quantiphy).
"""

from __future__ import annotations

import pytest

from stockroom.component_value import parse_component_value, same_component_value

# -- plain engineering notation ------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("10k", 10_000.0),
    ("10K", 10_000.0),          # users type either case for kilo
    ("4.7k", 4_700.0),
    ("1M", 1_000_000.0),        # a schematic "1M" resistor is 1 megohm, never 1 milliohm
    ("1meg", 1_000_000.0),
    ("100", 100.0),             # no prefix, no unit
    ("0.5", 0.5),
    ("2G", 2e9),
])
def test_parses_prefixes(text, expected):
    got = parse_component_value(text)
    assert got is not None and got[0] == pytest.approx(expected)


def test_milli_is_lowercase_and_mega_is_uppercase():
    # The one genuinely case-SENSITIVE prefix pair. Folding case here would turn a 5 milliohm shunt
    # into a 5 megohm open circuit, which is the most dangerous possible misread of a schematic.
    lo = parse_component_value("5m")
    hi = parse_component_value("5M")
    assert lo is not None and lo[0] == pytest.approx(5e-3)
    assert hi is not None and hi[0] == pytest.approx(5e6)


# -- units ---------------------------------------------------------------------


@pytest.mark.parametrize("text,value,unit", [
    ("100nF", 100e-9, "farad"),
    ("4.7uF", 4.7e-6, "farad"),
    ("4.7 µF", 4.7e-6, "farad"),      # the micro sign the record formatter emits
    ("4.7 μF", 4.7e-6, "farad"),  # and the Greek mu users paste
    ("10 kOhm", 10_000.0, "ohm"),      # exactly what `_fmt_ohms` writes onto a record
    ("10kohms", 10_000.0, "ohm"),
    ("470 Ω", 470.0, "ohm"),      # the ohm sign
    ("10uH", 10e-6, "henry"),
    ("2.2 nH", 2.2e-9, "henry"),
])
def test_parses_units(text, value, unit):
    got = parse_component_value(text)
    assert got is not None
    assert got[0] == pytest.approx(value) and got[1] == unit


# -- RKM / IEC 60062: the prefix letter stands in for the decimal point --------


@pytest.mark.parametrize("text,expected", [
    ("4k7", 4_700.0),
    ("4R7", 4.7),
    ("0R05", 0.05),
    ("1M0", 1_000_000.0),
    ("10R", 10.0),        # a bare trailing R is the unit, not a decimal point
    ("2n2", 2.2e-9),
])
def test_parses_rkm_notation(text, expected):
    got = parse_component_value(text)
    assert got is not None and got[0] == pytest.approx(expected)


# -- what must NOT parse -------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "~", "DNP", "n/a", "TBD", "LM358", "R", "k",
                                  "0402", "see BOM", None])
def test_unparseable_returns_none(text):
    # An honest None, never a 0.0 or a guess: a value the parser cannot read must produce NO candidate
    # rather than a candidate that silently compares equal to something.
    assert parse_component_value(text) is None


def test_a_trailing_tolerance_does_not_defeat_the_parse():
    # Real schematics carry "10k 1%" in Value. The tolerance is dropped (the value is what identifies
    # the component's magnitude); anything else trailing still refuses to parse.
    got = parse_component_value("10k 1%")
    assert got is not None and got[0] == pytest.approx(10_000.0)
    assert parse_component_value("10k 0402") is None


# -- comparison ----------------------------------------------------------------


@pytest.mark.parametrize("a,b", [
    ("10k", "10 kOhm"),          # schematic form vs the form a record stores
    ("4k7", "4.7 kOhm"),
    ("100nF", "0.1 uF"),         # same magnitude across prefixes
    ("100n", "100 nF"),          # a unitless side is compatible with a united one
    ("1M", "1000k"),
])
def test_same_component_value_matches_equivalent_notations(a, b):
    assert same_component_value(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("10k", "47k"),
    ("10k", "10 nF"),            # same magnitude, INCOMPATIBLE units
    ("5m", "5M"),
    ("10k", "DNP"),              # an unparseable side never matches
    ("", "10k"),
])
def test_same_component_value_rejects_mismatches(a, b):
    assert same_component_value(a, b) is False
