"""Parametric facets derived from the free-form ``specs`` bag on part records.

The modular Mouser-style search filters parts by their parameters (resistance,
tolerance, voltage, ...). Those parameters are NOT a hardcoded per-category list: they
are whatever spec keys the parts actually carry (spec section 5.1 - the JSON record is
the source of truth, and ``specs`` is an open bag keyed by spec name). This module reads
a set of records and, for every spec key present, emits one facet:

* a key whose values are mostly numeric (``"10 kΩ"``, ``"0.25 W"``, ``"50 V"``) becomes a
  ``range`` facet with a normalized ``min``/``max`` and, where the values agree on one,
  a ``unit``. SI prefixes are normalized so ``1 kΩ`` sorts below ``10 kΩ``;
* any other key becomes an ``options`` facet: the top-N distinct values, most common
  first, each with its part count.

Deriving purely from the data is the whole point: a category that grows a brand-new spec
key produces a facet for it with zero code change. Pure Python, no Qt, no I/O - the
caller loads the records (scoped through the derived index) and passes them in.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

# SI decimal prefixes. A prefix only applies when a base unit follows it, so a bare
# ``"m"`` reads as metres (unit), never milli, and ``"k"`` alone is not a magnitude.
_SI = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,  # U+00B5 MICRO SIGN
    "μ": 1e-6,  # U+03BC GREEK SMALL LETTER MU
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}
# A leading signed number followed (after optional space) by a single unit token with no
# internal whitespace. Anchoring the unit to the end rejects prose like "10 to 20 V" (the
# leftover " 20 V" fails the match), so only a clean "<number><unit>" is read as numeric.
_NUM_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))\s*(\S*)$")

# How many distinct values an options facet lists, most common first.
_TOP_N = 24
# A key is a range when at least this fraction of its values parse as a number.
_NUMERIC_FRACTION = 0.6


@dataclass
class FacetOption:
    value: str
    count: int


@dataclass
class ParametricFacet:
    key: str
    label: str
    kind: str  # "options" | "range"
    count: int  # parts carrying this spec key
    options: list[FacetOption] | None = None
    min: float | None = None
    max: float | None = None
    unit: str | None = None


@dataclass
class ParametricFacets:
    category: str | None
    facets: list[ParametricFacet]
    total: int


def _split_prefix(unit: str) -> tuple[float, str]:
    """Peel a leading SI prefix off ``unit`` when a base unit follows it. ``"kΩ"`` ->
    ``(1e3, "Ω")``; ``"V"`` -> ``(1.0, "V")``; ``"m"`` (metres) -> ``(1.0, "m")``."""
    if len(unit) >= 2 and unit[0] in _SI:
        return _SI[unit[0]], unit[1:]
    return 1.0, unit


def _parse_numeric(value) -> tuple[float, str] | None:
    """``(magnitude, base_unit)`` when ``value`` is a leading number with an optional
    SI-prefixed unit, else ``None``. ``"10 kΩ"`` -> ``(10000.0, "Ω")``; ``"5%"`` ->
    ``(5.0, "%")``; a bare number -> ``(n, "")``; anything else -> ``None``. Booleans are
    never numeric (a ``bool`` is a discrete option, not a magnitude)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return (float(value), "") if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    m = _NUM_RE.match(value.strip())
    if not m:
        return None
    # A leading zero followed by another digit is a CODE, not a magnitude: real numbers never
    # carry a leading zero, so "0402"/"0603" (package/case sizes) are discrete options, not a
    # numeric range. This keeps the parametric facet data-driven - no per-key package list.
    if re.match(r"[+-]?0\d", m.group(1)):
        return None
    magnitude = float(m.group(1))
    mult, base = _split_prefix(m.group(2).strip())
    return magnitude * mult, base


def _is_scalar(value) -> bool:
    """A spec value that can seed a facet: a non-empty string, or a number/bool. The
    structured values in the bag (a pinout list, a nested dict) are not parameters and
    are skipped."""
    if isinstance(value, str):
        return value.strip() != ""
    return isinstance(value, (int, float, bool))


def _build_facet(key: str, values: list) -> ParametricFacet:
    numeric = [n for n in (_parse_numeric(v) for v in values) if n is not None]
    if values and len(numeric) >= _NUMERIC_FRACTION * len(values):
        mags = [m for m, _ in numeric]
        units = Counter(base for _, base in numeric if base)
        unit = units.most_common(1)[0][0] if units else None
        return ParametricFacet(
            key=key,
            label=key,
            kind="range",
            count=len(values),
            min=min(mags),
            max=max(mags),
            unit=unit,
        )
    counts = Counter(v if isinstance(v, str) else str(v) for v in values)
    # most common first; ties broken by the value text so the order is deterministic.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    options = [FacetOption(value=val, count=n) for val, n in ranked[:_TOP_N]]
    return ParametricFacet(key=key, label=key, kind="options", count=len(values), options=options)


# --- the server-side spec filter --------------------------------------------
#
# The facets above tell the UI which dimensions exist; a SpecConstraint is how a selection
# narrows the parts list. The filter must AGREE with the facet it came from: option values
# compare as text (the options facet), a numeric range compares SI-normalized magnitudes via
# the SAME _parse_numeric as the range facet, so a checkbox never disagrees with the list it
# produces.


@dataclass
class SpecConstraint:
    """One parsed filter on a spec key: an OR-set of option values and/or a numeric range.
    A record must satisfy EVERY constraint (AND across keys); within a key the option values
    OR together. A bound of ``None`` is open on that side."""

    key: str
    values: list[str] = field(default_factory=list)
    min: float | None = None
    max: float | None = None


def _to_bound(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_spec_filters(tokens) -> list[SpecConstraint]:
    """Parse ``["Dielectric:X7R", "Resistance:1000~10000"]`` into one SpecConstraint per key.
    A token is ``"<key>:<value>"`` (an option) or ``"<key>:<min>~<max>"`` (a range; either
    bound may be blank for open-ended). Repeated keys merge: option values OR together, a
    range sets that key's bounds. A malformed token is skipped, never raised - the filter is
    fed from a URL, so garbage must degrade to no-constraint, not a 500."""
    by_key: dict[str, SpecConstraint] = {}
    for token in tokens:
        if not isinstance(token, str) or ":" not in token:
            continue
        raw_key, rest = token.split(":", 1)
        key = raw_key.strip()
        rest = rest.strip()
        if not key or not rest:
            continue
        c = by_key.setdefault(key, SpecConstraint(key=key))
        if "~" in rest:
            lo, hi = rest.split("~", 1)
            lo_b, hi_b = _to_bound(lo), _to_bound(hi)
            if lo_b is not None:
                c.min = lo_b
            if hi_b is not None:
                c.max = hi_b
        else:
            c.values.append(rest)
    return list(by_key.values())


def _specs_match(specs: dict, constraints: list[SpecConstraint]) -> bool:
    for c in constraints:
        value = specs.get(c.key)
        if not _is_scalar(value):
            return False  # a constraint on a spec the record lacks excludes it
        if c.values:
            text = value if isinstance(value, str) else str(value)
            if text not in c.values:
                return False
        if c.min is not None or c.max is not None:
            parsed = _parse_numeric(value)
            if parsed is None:
                return False  # a numeric range on a non-numeric value never matches
            mag, _ = parsed
            if c.min is not None and mag < c.min:
                return False
            if c.max is not None and mag > c.max:
                return False
    return True


def matches_spec_filters(record, constraints: list[SpecConstraint]) -> bool:
    """True when ``record`` satisfies EVERY constraint. No constraints -> a vacuous True, so
    an unfiltered search keeps every record. Reads ``record.specs`` (the open bag)."""
    if not constraints:
        return True
    return _specs_match(record.specs or {}, constraints)


def aggregate_parametric(records, category: str | None = None) -> ParametricFacets:
    """Aggregate the spec bags of ``records`` (already scoped by the caller) into one
    facet per spec key. ``category`` is echoed back on the result; it does not filter
    (the caller scopes the records). Insertion order of keys as first seen is preserved
    so a stable, data-driven ordering reaches the UI."""
    buckets: dict[str, list] = {}
    total = 0
    for rec in records:
        total += 1
        for raw_key, value in (rec.specs or {}).items():
            if not _is_scalar(value):
                continue
            buckets.setdefault(raw_key, []).append(value)
    facets = [_build_facet(key, values) for key, values in buckets.items()]
    return ParametricFacets(category=category, facets=facets, total=total)
