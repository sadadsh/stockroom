"""Canonical hygiene for the free-form ``specs`` bag on a :class:`PartRecord`.

Distributor pages hand us spec keys and values with cosmetic defects that the
detail panel exposes verbatim once it lists every stored spec (backlog F2):
a space before a percent (``"1 %"``), a spaced temperature-coefficient unit
(``"100 PPM / C"``), and a duplicated label baked into the key itself
(``"Factory Pack Quantity: Factory Pack Quantity"``). This module is the single,
pure, dependency-free place that turns those into their clean canonical form.

Design rules, deliberately surgical so a broad rewrite can never corrupt real
data (there are legitimate ``" / "`` values like ``"Decoders / Demultiplexers"``
and a non-string ``"US Tariff %": 37.0``):

* leading/trailing whitespace is trimmed and internal runs collapse to one space;
  beyond that only two targeted value fixes fire — space-before-percent and the
  ``PPM / C`` unit — no other characters are rewritten, and non-string values pass
  through untouched (never mutated, returned by identity);
* a key ``"X: X"`` (both sides equal) collapses to ``"X"``; a key whose colon
  sides differ is a real key and is preserved;
* whitespace is trimmed and internal runs collapsed to a single space;
* every function is idempotent, so applying it on ingest AND on serialize (as
  ``PartRecord`` does) can never drift.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
# A space (or run) before a percent that follows a digit: "1 %" -> "1%". Anchored on
# a preceding digit so a value like "Grade A % test" (no number) is never touched.
_SPACE_PCT = re.compile(r"(?<=\d)\s+%")
# Temperature-coefficient unit written with spaces around the slash: "100 PPM / C"
# -> "100 PPM/C". ONLY the spacing is collapsed. Case (PPM/ppm), a present degree
# symbol, and the bare "C" are all preserved via backrefs, because the library's own
# convention is bare "C" (0 degree symbols across every record) and inventing a "°"
# would both diverge from that AND derive data the source never had. Scoped to the
# PPM unit so general " / " values (category and manufacturer names) are untouched;
# a following "Celsius" is not a bare "C" (word boundary) and stays put.
_PPM_C = re.compile(r"\b(ppm)\s*/\s*(°?)\s*(c)\b", re.IGNORECASE)
# "Label: Label" -> "Label": the two colon-separated sides are equal after trimming.
_DUP_LABEL = re.compile(r"^(.+?):\s*(.+)$")


def normalize_spec_value(value):
    """Return ``value`` cleaned. Non-strings pass through by identity (a float
    tariff, a pinout list) so structured spec values are never coerced."""
    if not isinstance(value, str):
        return value
    v = _WS.sub(" ", value).strip()
    v = _SPACE_PCT.sub("%", v)
    v = _PPM_C.sub(r"\1/\2\3", v)
    return v


def normalize_spec_key(key):
    """Return ``key`` trimmed/whitespace-collapsed, collapsing a duplicated
    ``"Label: Label"`` to ``"Label"``. A key whose colon sides differ is a real
    key and is returned unchanged."""
    if not isinstance(key, str):
        return key
    k = _WS.sub(" ", key).strip()
    m = _DUP_LABEL.match(k)
    if m and m.group(1).strip() == m.group(2).strip():
        return m.group(1).strip()
    return k


def normalize_specs(specs: dict) -> dict:
    """Return a new dict with every key and value canonicalized, insertion order
    preserved. A key or string value empty after cleaning is dropped.

    Two raw keys can canonicalize to the same key (a duplicated-label twin like
    ``"Factory Pack Quantity: Factory Pack Quantity"`` and its clean ``"Factory Pack
    Quantity"``). On such a collision the surviving value is chosen DETERMINISTICALLY,
    independent of insertion order: a value from an already-canonical raw key (one that
    needed no cleaning) beats one from a malformed twin, and a non-blank value beats a
    blank one; only when neither side is canonical is the first seen kept. This is a
    best-effort collapse of what the source labelled twice - it does NOT promise that
    two genuinely different values BOTH survive; a real conflict resolves to the
    canonical-key value and the other is dropped. The spec-merge callers (set_specs,
    _copy_specs) normalize the key BEFORE their own dedup, so this last-resort collision
    is rarely reached in practice."""
    out: dict = {}
    from_canon: dict = {}
    for raw_key, raw_val in specs.items():
        key = normalize_spec_key(raw_key)
        if key == "":
            continue
        val = normalize_spec_value(raw_val)
        canon = raw_key == key
        if key not in out:
            out[key] = val
            from_canon[key] = canon
            continue
        existing = out[key]
        existing_blank = isinstance(existing, str) and existing.strip() == ""
        new_blank = isinstance(val, str) and val.strip() == ""
        if existing_blank and not new_blank:
            out[key], from_canon[key] = val, canon
        elif not new_blank and canon and not from_canon[key]:
            out[key], from_canon[key] = val, True
        # else keep the value already present (deterministic: canonical/first wins)
    return out
