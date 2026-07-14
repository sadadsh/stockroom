"""KiBoM-derived grouping rules (MIT, SchrodingersGat/KiBoM), reimplemented Qt-free.

Layered onto the retired app's MPN-primary BOM grouping (projects/bom.py, Decision 5)
so that, without replacing MPN-primary + manufacturer-in-key + value-as-MPN promotion:

  - values that mean the same thing share one BOM line: 4.7k == 4700 == 4k7,
    0.1uF == 100n == 100nF (units.compMatch / compareValues);
  - a testpoint / fiducial / mounting hole / solder bridge is excluded from the BOM
    (preferences.regExcludes + component.testRegExclude);
  - a "do not fit / do not populate" part is excluded (component.DNF + isFitted).

Reproduced from kibom/units.py, kibom/component.py, and kibom/preferences.py; see
docs/research/2026-07-13-kicad-ecosystem-learnings.md #10.

Two faithful departures from KiBoM, both because Stockroom groups by a hashable KEY
(normalize_value, footprint, manufacturer) rather than KiBoM's pairwise compare to a
group's first member:
  1. normalize_value returns a number-only canonical token (the unit is dropped),
     because the footprint already discriminates part type in the key, so keeping the
     unit would wrongly keep "4.7k" and "4.7kohm" apart. This mirrors KiBoM's
     compareValues, which treats a unitless side as compatible.
  2. KiBoM's symbol-name alias table (C == C_Small) is NOT reproduced: Stockroom keys
     on footprint, not symbol name, so two same-footprint parts already merge whatever
     their symbol is, and two different-footprint parts must stay apart. An alias map
     would be unreachable code. The merge it targets is delivered (and tested) by
     footprint + normalize_value grouping.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re

# -- value normalization (kibom/units.py) -------------------------------------
# Two micro glyphs: U+03BC GREEK SMALL LETTER MU and U+00B5 MICRO SIGN. UNIT_R
# carries U+03C9 (lowercase omega). Order preserved from the master-branch lists so
# the built alternation matches KiBoM byte-for-byte.
_PREFIX_MICRO = ["μ", "µ", "u", "micro"]
_PREFIX_MILLI = ["milli", "m"]
_PREFIX_NANO = ["nano", "n"]
_PREFIX_PICO = ["pico", "p"]
_PREFIX_KILO = ["kilo", "k"]
_PREFIX_MEGA = ["mega", "meg", "M"]
_PREFIX_GIGA = ["giga", "g"]
_PREFIX_ALL = (
    _PREFIX_PICO + _PREFIX_NANO + _PREFIX_MICRO + _PREFIX_MILLI
    + _PREFIX_KILO + _PREFIX_MEGA + _PREFIX_GIGA
)

_UNIT_R = ["r", "ohms", "ohm", "ω"]
_UNIT_C = ["farad", "f"]
_UNIT_L = ["henry", "h"]
_UNIT_ALL = _UNIT_R + _UNIT_C + _UNIT_L


def _get_prefix(prefix: str | None) -> float:
    """Numeric multiplier for a metric prefix. 'M' is mega, 'm' is milli: that single
    case distinction is decided here, NOT in the IGNORECASE match, so the caller must
    hand the original-case capture through unchanged (kibom/units.getPrefix)."""
    if not prefix:
        return 1
    if prefix != "M":
        prefix = prefix.lower()
    if prefix in _PREFIX_PICO:
        return 1.0e-12
    if prefix in _PREFIX_NANO:
        return 1.0e-9
    if prefix in _PREFIX_MICRO:
        return 1.0e-6
    if prefix in _PREFIX_MILLI:
        return 1.0e-3
    if prefix in _PREFIX_KILO:
        return 1.0e3
    if prefix in _PREFIX_MEGA:
        return 1.0e6
    if prefix in _PREFIX_GIGA:
        return 1.0e9
    return 1


def _get_unit(unit: str | None) -> str | None:
    """Canonical unit symbol (R / F / H) for comparison, or None (kibom/units.getUnit)."""
    if not unit:
        return None
    unit = unit.lower()
    if unit in _UNIT_R:
        return "R"
    if unit in _UNIT_C:
        return "F"
    if unit in _UNIT_L:
        return "H"
    return None


# Built the same way KiBoM builds it: join the prefix and unit lists with '|', star
# both groups (an empty prefix/unit is allowed), anchored, IGNORECASE. Group 1 =
# number, 2 = prefix, 3 = unit, 4 = trailing post-digits (the "0R05" == 0.05 case).
_MATCH = re.compile(
    r"^([0-9\.]+)\s*(" + "|".join(_PREFIX_ALL) + ")*("
    + "|".join(_UNIT_ALL) + r")*(\d*)$",
    flags=re.IGNORECASE,
)


def _comp_match(component: str) -> tuple[float, float, str | None] | None:
    """Parse a value string into (number, prefix_multiplier, unit) or None when it is
    not a metric value (an MPN, a label, a blank). Ported from kibom/units.compMatch,
    including the "unit in the middle" case (0R05 -> 0.05 ohm) via the post group."""
    component = (component or "").strip().replace(",", "")
    result = _MATCH.search(component)
    if not result or len(result.groups()) != 4:
        return None
    value, prefix, units, post = result.groups()
    if post and "." not in value:
        try:
            value = float(int(value))
            post_value = float(int(post)) / (10 ** len(post))
            value = value * 1.0 + post_value
        except (TypeError, ValueError):
            return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return (val, _get_prefix(prefix), _get_unit(units))


def normalize_value(value: str) -> str:
    """A canonical grouping token so equivalent values share a BOM line. A parseable
    metric value collapses to its number x prefix product formatted to 15 dp (the unit
    is dropped, see the module note): 4.7k and 4700 both give '4700.000000000000000',
    100nF / 0.1uF / 100n all give '0.000000100000000'. A value KiBoM cannot parse (an
    MPN, a blank, '3V3') falls back to its case-folded, stripped self, so grouping still
    works and never merges two genuinely unlike strings."""
    r = _comp_match(value or "")
    if r is None:
        return (value or "").strip().lower()
    val, mult, _unit = r
    return "{0:.15f}".format(val * 1.0 * mult)


# -- do-not-fit + regex exclude (kibom/component.py, kibom/preferences.py) -----
# Exact-membership DNF spelling set (component.DNF). Matched case-folded.
_DNF = {
    "dnf", "dnl", "dnp", "do not fit", "do not place", "do not load",
    "nofit", "nostuff", "noplace", "noload", "not fitted", "not loaded",
    "not placed", "no stuff",
}

# The default REGEX_EXCLUDE table (preferences.regExcludes), each (field, pattern).
# re.search + IGNORECASE, so '^TP'/'^FID' are prefix-anchored and the rest are
# unanchored substring searches. A single hit excludes the component.
_REG_EXCLUDES: list[tuple[str, "re.Pattern[str]"]] = [
    ("reference", re.compile(r"^TP[0-9]*", re.IGNORECASE)),
    ("reference", re.compile(r"^FID", re.IGNORECASE)),
    ("part", re.compile(r"mount.*hole", re.IGNORECASE)),
    ("part", re.compile(r"solder.*bridge", re.IGNORECASE)),
    ("part", re.compile(r"test.*point", re.IGNORECASE)),
    ("footprint", re.compile(r"test.*point", re.IGNORECASE)),
    ("footprint", re.compile(r"mount.*hole", re.IGNORECASE)),
    ("footprint", re.compile(r"fiducial", re.IGNORECASE)),
]


def is_excluded(reference: str, part_name: str, footprint: str) -> bool:
    """Whether a component matches the default REGEX_EXCLUDE table (testpoints,
    fiducials, mounting holes, solder bridges) and must be dropped from the BOM.
    `part_name` is the symbol name (the lib_id after its colon), `footprint` the full
    footprint id. Ported from kibom/component.testRegExclude with the default table."""
    fields = {
        "reference": reference or "",
        "part": part_name or "",
        "footprint": footprint or "",
    }
    for field_name, pattern in _REG_EXCLUDES:
        if pattern.search(fields[field_name]):
            return True
    return False


def is_do_not_fit(props: dict) -> bool:
    """Whether a component's fields mark it do-not-fit / do-not-populate: a DNF spelling
    in the Value field, or in a Config field (space or comma separated). Ported from
    kibom/component.isFitted (the field-based half). The KiCad (dnp yes) and
    (exclude_from_bom) s-expression tokens are handled by the schematic reader in
    projects/bom.py; this covers the property/value spellings KiBoM recognizes."""
    norm = {(k or "").strip().lower(): (v or "").strip() for k, v in (props or {}).items()}
    if norm.get("value", "").lower() in _DNF:
        return True
    config = norm.get("config", "")
    if config:
        for opt in re.split(r"[ ,]+", config):
            if opt.strip().lower() in _DNF:
                return True
    return False
