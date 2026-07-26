"""Normalize a component-value notation to one comparable number.

A passive's value is written differently on the two sides that need to be compared: a KiCad schematic
carries the terse engineering form in its `Value` property ("10k", "4k7", "100nF"), while a Stockroom
record carries the formatter's spelled-out form in its specs ("10 kOhm", "4.7 µF", straight out of
`enrich.passive._fmt_ohms` / `_fmt_farads`). ONE parser reads both, so the two sides can never
disagree by going through two different readers.

The rule is modeled on KiBoM's `units.compMatch` (github.com/SchrodingersGat/KiBoM, MIT), which is
the practitioner reference for exactly this problem in the KiCad ecosystem. Adopted as the ALGORITHM,
deliberately not as a dependency: KiBoM is an application rather than a published library, and every
packaged alternative was rejected on evidence (UliEngineering's own PyPI page says most of it needs
scipy, which is absurd weight for this; pint and quantiphy cannot read the RKM notation that real
schematics use). See the 2026-07-25 FINDING in the ledger.

What it handles, and why each part is needed:

  - SI prefixes, case-sensitive where it matters. `k` and `K` are both kilo because users type both,
    but `m` (milli) and `M` (mega) are NOT folded: folding them would read a 5 milliohm shunt as a
    5 megohm open circuit, the most dangerous possible misreading of a schematic. `meg` is accepted
    as the SPICE-style spelling of mega.
  - The micro sign in all three spellings actually found in the wild: `u`, `µ` (U+00B5 MICRO SIGN,
    what the record formatter emits) and `μ` (U+03BC GREEK SMALL LETTER MU, what pasted vendor text
    usually contains). They are different codepoints and both appear.
  - Unit words for the three passive kinds, so "10 kOhm" and "10k" compare equal while "10 kOhm" and
    "10 nF" never do.
  - RKM / IEC 60062, where the prefix letter stands in for the decimal point: "4k7" = 4700,
    "0R05" = 0.05, "1M0" = 1e6. This is why the parser cannot simply strip letters and call `float`.

Anything it cannot read confidently returns None, never 0.0 and never a guess: an unreadable value
must yield NO match candidate rather than a candidate that silently compares equal to something else.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import math
import re

# Case matters here. Ordered longest-first where one key prefixes another ("meg" before "m") so the
# regex alternation cannot match the short one and leave "eg" stranded.
_PREFIXES: dict[str, float] = {
    "meg": 1e6, "MEG": 1e6, "Meg": 1e6,
    "p": 1e-12, "P": 1e-12,
    "n": 1e-9, "N": 1e-9,
    "u": 1e-6, "U": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3,            # milli: lowercase ONLY, never folded with mega
    "k": 1e3, "K": 1e3,
    "M": 1e6,             # mega: uppercase ONLY
    "g": 1e9, "G": 1e9,
}

# The RKM decimal-point letter that is ALSO a unit on its own ("10R" is 10 ohms, "4R7" is 4.7 ohms).
# Kept separate from `_PREFIXES` because it scales by 1; it is not an SI prefix. Only `R` belongs here:
# RKM spells capacitance and inductance with real SI prefixes, so inventing an "L as decimal point"
# rule would be reading a notation nobody writes.
_UNIT_AS_POINT: dict[str, str] = {"R": "ohm", "r": "ohm"}

# Unit words -> the canonical unit name, looked up case-FOLDED (unlike prefixes, no unit word is
# ambiguous by case). Both omega codepoints -- U+03A9 GREEK CAPITAL OMEGA and U+2126 OHM SIGN, which
# are distinct characters that both appear in the wild -- lowercase to the same U+03C9, so the single
# key "ω" covers them. Longest-first in the pattern so "ohms" wins over "ohm".
_UNITS: dict[str, str] = {
    "ohms": "ohm", "ohm": "ohm", "r": "ohm", "ω": "ohm",
    "farads": "farad", "farad": "farad", "f": "farad",
    "henries": "henry", "henrys": "henry", "henry": "henry", "h": "henry",
}

_PREFIX_ALT = "|".join(re.escape(k) for k in sorted(_PREFIXES, key=len, reverse=True))
_POINT_ALT = "|".join(re.escape(k) for k in _UNIT_AS_POINT)
_UNIT_ALT = "|".join(
    re.escape(k) for k in sorted({*_UNITS, "Ω", "Ω"}, key=len, reverse=True)
)

# <number> [prefix-or-RKM-letter][trailing digits] [unit]. The trailing digit group is what makes RKM
# work: in "4k7" the 7 belongs after the decimal point the "k" stands in for. It sits IMMEDIATELY
# after the letter with no whitespace permitted between them, which is what makes "10k 0402" refuse to
# parse instead of being read as 10.0402k -- the unit is what may be separated by a space ("10 kOhm"),
# never the RKM fraction. Only the UNIT group is case-insensitive (an inline scoped flag): folding case
# over the PREFIX group would make milli and mega the same letter.
_VALUE = re.compile(
    rf"^\s*(\d+(?:\.\d+)?|\.\d+)\s*({_PREFIX_ALT}|{_POINT_ALT})?(\d*)\s*((?i:{_UNIT_ALT}))?\s*$",
    re.UNICODE,
)

# A trailing tolerance is dropped before parsing: real schematics carry "10k 1%" in Value, and the
# tolerance is not part of the magnitude. Nothing ELSE trailing is tolerated, so "10k 0402" still
# refuses to parse rather than being read as 10k.
_TRAILING_TOLERANCE = re.compile(r"\s*(?:\+/-|\+-|±)?\s*\d+(?:\.\d+)?\s*%\s*$")


def parse_component_value(text: str | None) -> tuple[float, str] | None:
    """Parse a component-value notation into `(magnitude_in_base_units, unit)`, or None.

    `unit` is one of "ohm" / "farad" / "henry", or "" when the notation carried no unit (a bare "10k",
    which is by far the most common schematic form). Returns None for anything not confidently a
    value, including "", "~", "DNP", a part number, and a bare prefix or unit letter with no number.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    raw = _TRAILING_TOLERANCE.sub("", raw).strip()
    if not raw:
        return None
    m = _VALUE.match(raw)
    if m is None:
        return None
    number, letter, trailing, unit_word = m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""
    if "." not in number and len(number) > 1 and number.startswith("0"):
        # A multi-digit integer with a leading zero is not a value anyone writes, but it IS how EIA
        # case codes look, so refusing it stops "0402" from being read as 402 ohms. A lone "0" (the
        # zero-ohm jumper) and "0.1" are unaffected, and RKM "0R05" reaches here with number == "0".
        return None
    # The letter is either an SI prefix (scales the number) or an RKM decimal-point letter that is
    # itself the unit (scales by 1 and names the unit).
    if letter in _PREFIXES:
        scale = _PREFIXES[letter]
        unit = _UNITS.get(unit_word.lower(), "") if unit_word else ""
    elif letter in _UNIT_AS_POINT:
        scale = 1.0
        unit = _UNIT_AS_POINT[letter]
    else:
        scale = 1.0
        unit = _UNITS.get(unit_word.lower(), "") if unit_word else ""
    value = float(number)
    if trailing:
        if "." in number:
            # "4.7k7" is not a notation anyone writes; refuse rather than invent a reading for it.
            return None
        if not letter:
            # Digits separated from digits by nothing meaningful ("10 5") is not a value.
            return None
        value += float(trailing) / (10 ** len(trailing))
    return value * scale, unit


def same_component_value(a: str | None, b: str | None) -> bool:
    """True when two value notations denote the same quantity.

    Both sides must parse (an unreadable value never matches, not even another unreadable one), the
    magnitudes must agree to within floating-point representation error, and the units must be
    compatible: equal, or one side carrying no unit at all (a schematic "10k" against a record's
    "10 kOhm" is a match, while "10k" against "10 nF" is not).
    """
    pa, pb = parse_component_value(a), parse_component_value(b)
    if pa is None or pb is None:
        return False
    (va, ua), (vb, ub) = pa, pb
    if ua and ub and ua != ub:
        return False
    return math.isclose(va, vb, rel_tol=1e-9, abs_tol=0.0)
