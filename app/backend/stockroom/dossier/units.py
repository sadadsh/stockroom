"""Unit normalization: one comparable magnitude behind every engineering value.

Distributors state the same quantity in whatever scale their page uses - `0.5 V` and `500 mV`,
`1.1 kOhms` and `1100 ohm`, `62.5 mW` and `0.063 W`. Compared as strings those are four
disagreements; compared as base-unit magnitudes they are two agreements. Sorting, filtering and
conflict detection all need the magnitude, and the person still needs the source's own wording,
so both are kept: `display` is what the source said and `normalized` is what it means.

Nothing here invents precision. A value this module cannot read returns a `text` result with no
magnitude, which is honest - a fabricated number would make an unreadable value look filterable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# SI prefixes, including both micro spellings and the `K` some distributors use for kilo.
_SI_SCALE: dict[str, float] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}

# Unit spellings -> the canonical symbol. Case-folded on lookup except where case is the only
# thing separating two units, which is why the prefix is split off before this is consulted.
_BASE_UNITS: dict[str, str] = {
    "ohm": "Ω",
    "ohms": "Ω",
    "Ω": "Ω",
    # `Ω`.casefold() is `ω`, so the lower-cased lookup below never sees the capital form.
    "ω": "Ω",
    "r": "Ω",
    "f": "F",
    "farad": "F",
    "farads": "F",
    "h": "H",
    "henry": "H",
    "henries": "H",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "ampere": "A",
    "amperes": "A",
    "w": "W",
    "watt": "W",
    "watts": "W",
    "hz": "Hz",
    "hertz": "Hz",
    "s": "s",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "j": "J",
    "joule": "J",
    "va": "VA",
    "b": "B",
    "byte": "B",
    "bytes": "B",
    "bit": "bit",
    "bits": "bit",
}

# Units carrying no SI prefix of their own. Kept apart so `mm` is a millimetre and not a
# milli-metre-of-something-else, and so `%` never acquires a prefix.
_LITERAL_UNITS: dict[str, str] = {
    "%": "%",
    "percent": "%",
    "ppm": "ppm",
    "°c": "°C",
    "degc": "°C",
    "c": "°C",
    "celsius": "°C",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "in": "in",
    "inch": "in",
    "inches": "in",
    "mil": "mil",
    "mils": "mil",
    "g": "g",
    "kg": "kg",
    "mhz": "Hz",
    "khz": "Hz",
    "ghz": "Hz",
}

# Length units expressed in millimetres, so a pitch stated in inches is comparable with one
# stated in millimetres without either being rewritten on screen.
_LENGTH_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "mil": 0.0254,
}

# A leading signed number, optionally in exponent form, then whatever unit text follows it.
_QUANTITY = re.compile(
    r"^\s*([+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\s(,;/]*)",
)

# The separators a range is written with: `-40C to 85C`, `-40 ~ +85`, `2.5V .. 5.5V`.
_RANGE_SPLIT = re.compile(r"\s*(?:~|\.\.\.?|\bto\b|–|—)\s*", re.IGNORECASE)

_TRUE_WORDS: frozenset[str] = frozenset({"yes", "true", "y"})
_FALSE_WORDS: frozenset[str] = frozenset({"no", "false", "n"})

# Values that mean "the source left this blank". Dropped rather than rendered, because an
# empty-in-disguise value takes a row while proving nothing.
EMPTY_VALUES: frozenset[str] = frozenset(
    {"", "-", "--", "n/a", "na", "none", "not available", "unknown", "not applicable", "tbd"}
)


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """One value, read two ways: what the source wrote, and what it measures."""

    value_type: str
    # A float for a quantity/integer, a two-item list for a range, a bool, or None when the
    # value carries no magnitude this module can honestly extract.
    normalized: object
    unit: str
    display: str


def is_empty(value: object) -> bool:
    """True when a value is absent, or present only as a distributor's placeholder."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return str(value).strip().casefold() in EMPTY_VALUES


def _canonical_unit(token: str) -> tuple[str, float] | None:
    """(canonical symbol, multiplier to the base unit) for one unit token, or None."""
    text = token.strip()
    if not text:
        return None
    folded = text.casefold()
    literal = _LITERAL_UNITS.get(folded)
    if literal is not None:
        # A prefixed frequency spelling (`kHz`, `MHz`) carries its own scale.
        if folded in {"mhz", "khz", "ghz"}:
            return literal, {"khz": 1e3, "mhz": 1e6, "ghz": 1e9}[folded]
        return literal, 1.0
    base = _BASE_UNITS.get(folded)
    if base is not None:
        return base, 1.0
    prefix, rest = text[0], text[1:]
    scale = _SI_SCALE.get(prefix)
    if scale is None or not rest:
        return None
    base = _BASE_UNITS.get(rest.casefold())
    if base is None:
        return None
    return base, scale


def parse_quantity(text: str) -> tuple[float, str] | None:
    """(base-unit magnitude, canonical unit) for a leading engineering quantity, or None.

    A bare number with no unit is a real quantity - a pin count, a tolerance already scaled -
    and comes back with an empty unit rather than being refused.
    """
    match = _QUANTITY.match(text)
    if match is None:
        return None
    try:
        magnitude = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    token = match.group(2)
    if not token:
        return magnitude, ""
    resolved = _canonical_unit(token)
    if resolved is None:
        return None
    unit, scale = resolved
    if unit in _LENGTH_TO_MM:
        return magnitude * _LENGTH_TO_MM[unit], "mm"
    return magnitude * scale, unit


def _parse_range(text: str) -> tuple[list[float], str] | None:
    parts = [part for part in _RANGE_SPLIT.split(text) if part.strip()]
    if len(parts) != 2:
        return None
    low = parse_quantity(parts[0])
    high = parse_quantity(parts[1])
    if low is None or high is None:
        return None
    # A range states its unit once as often as twice (`-40 to 85 C`); the stated one wins.
    unit = low[1] or high[1]
    if low[1] and high[1] and low[1] != high[1]:
        return None
    return [low[0], high[0]], unit


def normalize(value: object, *, expected_unit: str = "", value_type: str = "") -> NormalizedValue:
    """Read one stored spec value into its comparable form.

    `expected_unit` is the category schema's canonical unit for the field. It only ever fills a
    gap - a bare `100` under a field measured in ohms - and never overrides a unit the value
    carried itself, because the source's own unit is the measured one.

    `value_type` is the schema's declared type and is honoured where the value supports it; a
    field declared `enum` is not turned into a number just because its value happens to parse.
    """
    if isinstance(value, bool):
        return NormalizedValue("boolean", value, "", "Yes" if value else "No")
    if isinstance(value, (list, tuple)):
        return NormalizedValue("list", [item for item in value], "", "")
    if isinstance(value, dict):
        return NormalizedValue("list", [], "", "")
    if isinstance(value, (int, float)):
        return NormalizedValue(
            "integer" if isinstance(value, int) else "quantity",
            float(value),
            expected_unit,
            str(value),
        )

    text = str(value).strip()
    if not text:
        return NormalizedValue("text", None, "", "")
    if value_type in {"enum", "text"}:
        return NormalizedValue(value_type, None, "", text)
    folded = text.casefold()
    if folded in _TRUE_WORDS:
        return NormalizedValue("boolean", True, "", text)
    if folded in _FALSE_WORDS:
        return NormalizedValue("boolean", False, "", text)

    ranged = _parse_range(text)
    if ranged is not None:
        bounds, unit = ranged
        return NormalizedValue("range", bounds, unit or expected_unit, text)

    quantity = parse_quantity(text)
    if quantity is not None:
        magnitude, unit = quantity
        resolved_unit = unit or expected_unit
        kind = "integer" if value_type == "integer" and magnitude.is_integer() else "quantity"
        return NormalizedValue(kind, magnitude, resolved_unit, text)

    return NormalizedValue(value_type or "text", None, "", text)


def comparable_key(normalized: NormalizedValue) -> object:
    """The value two candidates are compared BY when deciding whether they disagree.

    Two answers that mean the same measurement must not read as a conflict just because one
    page wrote `500 mV` and the other `0.5 V`. Where no magnitude could be read, the case-folded
    text is the only honest comparison available.
    """
    if normalized.normalized is None:
        return normalized.display.strip().casefold()
    if isinstance(normalized.normalized, float):
        # A one-percent window absorbs the rounding a page applies beside an exact fraction
        # (`0.063 W` beside `62.5 mW`) without merging two materially different answers.
        rounded = round(normalized.normalized, 12)
        if rounded == 0:
            return (normalized.unit, 0.0)
        exponent = f"{abs(rounded):.3e}"
        return (normalized.unit, exponent, rounded < 0)
    if isinstance(normalized.normalized, list):
        return (normalized.unit, tuple(str(item) for item in normalized.normalized))
    return (normalized.unit, normalized.normalized)


__all__ = [
    "EMPTY_VALUES",
    "NormalizedValue",
    "comparable_key",
    "is_empty",
    "normalize",
    "parse_quantity",
]
