"""Part identity from KiCad symbol properties, Qt-free.

Reimplemented (behavior-for-behavior) from the retired app's LibraryManager
identity helpers so the projects audit (M7a) and the projects BOM (M7c) can read a
component's manufacturer / part number the same way the old library did, without
importing the PyQt LibraryManager. Pure dict-in.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

# A REAL manufacturer part number lives in one of these dedicated fields; `value` is
# deliberately NOT here so a generic passive that only carries a Value is not treated
# as orderable. Keys are matched after folding case/space/underscore/hyphen away.
_MPN_KEYS_STRICT = (
    "manufacturerpartnumber",
    "mpn",
    "mouserpartnumber",
    "mouserpartno",
    "partnumber",
    "partno",
)
_MPN_KEYS = _MPN_KEYS_STRICT + ("value",)
_MFR_KEYS = ("manufacturer", "mfr", "mfg", "brand", "vendor")
# Case-folded values treated as "no real identity" and dropped. "value" is here because
# KiCad's default Value field is literally the string "Value".
_PLACEHOLDERS = {"", "~", "*", "-", "n/a", "na", "none", "value"}


def _normalize_keys(props: dict) -> dict:
    return {
        k.lower().replace(" ", "").replace("_", "").replace("-", ""): (v or "").strip()
        for k, v in (props or {}).items()
    }


def _pick(norm: dict, keys) -> str | None:
    for k in keys:
        v = norm.get(k, "")
        if v and v.lower() not in _PLACEHOLDERS:
            return v
    return None


def strict_mpn(props: dict) -> str | None:
    """A REAL manufacturer part number from a dedicated property (never the Value
    fallback). None for a generic passive that only carries a value."""
    return _pick(_normalize_keys(props), _MPN_KEYS_STRICT)


def part_identity(props: dict, fallback: str = "") -> dict:
    """Canonical identity from symbol properties: the manufacturer part number, the
    manufacturer, and the datasheet/description/category. `mpn` falls back to the loose
    Value field and then to `fallback` (e.g. a footprint stem); the rest are None when
    absent. Mirrors the retired LibraryManager.part_identity."""
    norm = _normalize_keys(props)
    return {
        "mpn": _pick(norm, _MPN_KEYS) or (fallback or None),
        "manufacturer": _pick(norm, _MFR_KEYS),
        "datasheet": _pick(norm, ("datasheet",)),
        "description": _pick(norm, ("description", "ki_description")),
        "category": _pick(norm, ("category",)),
    }


def has_real_mpn(row: dict) -> bool:
    """True only when the part carries a REAL manufacturer part number, never the
    Value/name fallback. Prefers the row's explicit `has_real_mpn` flag; otherwise
    infers from a bare {name, mpn} row (a real MPN differs from the humanized name)."""
    if "has_real_mpn" in row:
        return bool(row.get("has_real_mpn"))
    mpn = (row.get("mpn") or "").strip()
    if not mpn:
        return False
    name = (row.get("name") or "").strip()
    return mpn.lower() != name.lower() if name else True
