"""Derive a clean human name and a real description for a part from its scraped specs.

The library was seeded with machine names (concatenated spec fields, e.g.
"1.10k 1% 0603 Panasonic ERJ-P03F1101V") and wrong descriptions (the KiCad SYMBOL's
description, e.g. "Resistor, small symbol"), while the records carry rich, correct
distributor specs. These pure helpers rebuild a readable name ("1.1 kOhm Resistor")
and a real description ("Thick Film Chip Resistor, 1.1 kOhm, 200 mW, 0603") from those
specs, for both new ingests and a migration of the existing library. They never
fabricate: when the specs do not support a clean name, the caller keeps what it had.
"""

from __future__ import annotations

import re

# Category -> the singular kind word used in a passive's name/description.
_KIND_FROM_CATEGORY: dict[str, str] = {
    "Resistors": "Resistor",
    "Capacitors": "Capacitor",
    "Inductors": "Inductor",
    "Ferrite Beads": "Ferrite Bead",
}

# The value spec key that carries a passive's headline number.
_VALUE_KEY: dict[str, str] = {
    "Resistor": "Resistance",
    "Capacitor": "Capacitance",
    "Inductor": "Inductance",
}

# Spec values that mean "the distributor did not fill this" (lowercased for compare).
_EMPTY_VALUES = frozenset(
    {"", "not available", "none", "n/a", "-", "unknown", "not applicable"}
)


def _is_empty(value: str) -> bool:
    return value.strip().lower() in _EMPTY_VALUES


def _first(specs: dict, *keys: str) -> str:
    """The first present, non-empty-in-disguise spec value across `keys`."""
    for key in keys:
        raw = specs.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text and not _is_empty(text):
            return text
    return ""


def format_value(raw: str) -> str:
    """Normalize a scraped value string to a compact human form using the real unit
    glyphs (the bundled interface + mono faces both carry them): "1.1 kOhms" -> "1.1
    kΩ", "100 Ohms" -> "100 Ω", "1 uF" -> "1 µF", "6.8 uH" -> "6.8 µH". The SI prefix
    (k / M / m / G) is preserved, the ohm unit becomes Ω, micro "u" becomes µ before a
    unit, and the magnitude is spaced from its unit."""
    if not raw:
        return ""
    value = raw.strip()
    # ohm word -> Ω, keeping any SI prefix and its case (kOhms -> kΩ, MOhms -> MΩ)
    value = re.sub(r"([kMmGµ]?)Ohms?\b", lambda m: (m.group(1) or "") + "Ω", value)
    # micro "u" -> µ when it prefixes a unit (uF -> µF, uH -> µH, incl. unspaced "1uF")
    value = re.sub(r"u(?=[FH])", "µ", value)
    # a single space between the magnitude and its unit ("1µF" -> "1 µF")
    value = re.sub(r"(?<=[0-9])(?=[a-zA-ZµΩ])", " ", value, count=1)
    return re.sub(r"\s+", " ", value).strip()


def _package(specs: dict) -> str:
    return _first(specs, "Package", "Case Code - in", "Case Code - mm")


def _singularize(product: str) -> str:
    """Singularize a distributor product string by its last word: "Thick Film Chip
    Resistors" -> "Thick Film Chip Resistor", "Green LEDs" -> "Green LED", "Headers"
    -> "Header". A trailing "s" only; irregulars are rare in this vocabulary."""
    product = product.strip()
    if not product:
        return ""
    words = product.split()
    last = words[-1]
    if re.search(r"(ch|sh|x|s|z)es$", last):
        words[-1] = last[:-2]  # sibilant plural: "Switches" -> "Switch", "Boxes" -> "Box"
    elif len(last) > 2 and last.endswith("s") and not last.endswith("ss"):
        words[-1] = last[:-1]  # regular plural: "Resistors" -> "Resistor", "LEDs" -> "LED"
    return " ".join(words)


def _led_label(specs: dict) -> str:
    """A clean LED name from the product string: "Green LEDs" -> "Green LED",
    "Bi-Color LEDs" -> "Bi-Color LED". Falls back to "LED" when no colour is stated."""
    product = _first(specs, "Product", "Product Category", "Subcategory")
    singular = _singularize(product)
    if re.search(r"\bLED\b", singular, flags=re.IGNORECASE):
        return singular
    return ""


def clean_display_name(specs: dict, category: str) -> str | None:
    """A readable name derived from the specs, or None when the specs cannot support a
    clean one (the caller then keeps the existing name rather than inventing a worse
    one). Passives read "1.1 kOhm Resistor"; LEDs read "Green LED"."""
    kind = _KIND_FROM_CATEGORY.get(category)
    if kind:
        value = format_value(_first(specs, _VALUE_KEY.get(kind, "")))
        if value:
            return f"{value} {kind}"
    if category == "Diodes":
        led = _led_label(specs)
        if led:
            return led
    return None


def _rating(specs: dict) -> str:
    """A concise electrical rating for the description: a resistor's power ("200 mW",
    dropping the "(1/5 W)" gloss) or a capacitor's rated voltage."""
    power = _first(specs, "Power Rating")
    if power:
        return re.sub(r"\s*\(.*\)\s*", "", power).strip()
    return _first(specs, "Voltage Rating", "Voltage - Rated", "Voltage")


def clean_description(specs: dict, category: str) -> str | None:
    """A real, spec-derived description, or None when the specs offer nothing usable.
    Passive: "<product>, <value>, <rating>, <package>[, <dielectric>]". Non-passive:
    the distributor product line, singularized ("Slide Switch", "MOSFET")."""
    kind = _KIND_FROM_CATEGORY.get(category)
    if kind:
        value = format_value(_first(specs, _VALUE_KEY.get(kind, "")))
        head = _singularize(_first(specs, "Product", "Product Category")) or kind
        parts = [head]
        if value:
            parts.append(value)
        rating = _rating(specs)
        if rating:
            parts.append(rating)
        package = _package(specs)
        if package:
            parts.append(package)
        dielectric = _first(specs, "Dielectric")
        if dielectric:
            parts.append(dielectric)
        # only worth writing when it says more than the bare kind
        return ", ".join(parts) if len(parts) >= 2 else None
    product = _first(specs, "Product", "Product Category", "Subcategory")
    # a logistics/packaging term is not a description of the part (a module whose only
    # "Product" spec is "Tapes" gets no description rather than a wrong one)
    if product.strip().lower() in _PACKAGING_TERMS:
        return None
    return _singularize(product) or None


# Logistics terms that describe how a part is shipped, not what it is.
_PACKAGING_TERMS = frozenset(
    {"tape", "tapes", "reel", "reels", "cut tape", "bulk", "tray", "trays", "tube", "tubes"}
)


# Descriptions that are noise, not information: the KiCad symbol's own blurb, a
# "script generated" stub, a bare kind word, or a pure number. Matched so a migration
# knows which stored descriptions are safe to overwrite.
_PLACEHOLDER_DESC = re.compile(
    r"small\s+(us\s+)?symbol|script[\s-]*generated|generic\s+connector", re.IGNORECASE
)
_BARE_KIND = frozenset({"resistor", "capacitor", "inductor", "diode", "led", "connector"})


def is_placeholder_description(desc: str | None) -> bool:
    """Whether a stored description is a placeholder safe to replace (the KiCad symbol
    blurb, a script stub, a bare kind word, a lone number, or empty)."""
    text = (desc or "").strip()
    if not text:
        return True
    if _PLACEHOLDER_DESC.search(text):
        return True
    if text.lower().rstrip("s") in {k.rstrip("s") for k in _BARE_KIND}:
        return True
    if re.fullmatch(r"[\d\W]+", text):
        return True
    return False


def is_machine_name(name: str, mpn: str = "", manufacturer: str = "") -> bool:
    """Whether a stored name is a machine-concatenated one, safe to replace: it embeds
    the MPN or names the manufacturer ("1.10k 1% 0603 Panasonic ERJ-P03F1101V"). A human
    name ("1.1 kΩ Resistor", "My Favourite Part") embeds neither, so it is left alone."""
    text = (name or "").lower()
    if not text:
        return True
    if mpn and mpn.lower() in text:
        return True
    if manufacturer and re.search(rf"\b{re.escape(manufacturer.lower())}\b", text):
        return True
    return False


def apply_clean_identity(
    specs: dict,
    category: str,
    *,
    display_name: str,
    description: str,
    mpn: str = "",
    manufacturer: str = "",
) -> tuple[str, str]:
    """The one rule both the migration and new-part ingestion share: replace a machine
    name with a clean spec-derived one, and a placeholder description with a real one,
    while leaving anything a human wrote untouched. Returns the (name, description) to
    persist. Idempotent: a clean name/description passes straight through."""
    name = display_name
    if is_machine_name(display_name, mpn, manufacturer):
        clean = clean_display_name(specs, category)
        if clean:
            name = clean
    desc = description
    if is_placeholder_description(description):
        clean = clean_description(specs, category)
        if clean:
            desc = clean
    return name, desc
