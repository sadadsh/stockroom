"""Derive a proper, spec-aware component name from a part's scraped data — "what it IS", not an
opaque MPN (owner directive 2026-07-19). Passives lead with value + the defining specs (X7R
dielectric + voltage for a cap, power for a resistor, impedance@frequency for a ferrite); actives
lead with a HUMAN description built from the richest category field the distributors gave us; the
package always trails.

**The name carries no MPN and should be as human as the data allows (owner, 2026-07-26): "the MPN
always shows under the title so u can humanize the name as much as possible based off the
description or specs".** A real part read "Steering TPD6E05U06RVZR USON-14": `Steering` is a
fragment of `Type = "Steering (Rail to Rail)"`, which is a TVS PARAMETER, not a function, and the
same record carried `Product Category = "ESD Protection Diodes / TVS Diodes"` and
`Number of Channels = 6` that nothing read. It now reads "6-Channel ESD Protection Diode USON-14".

THE TRADEOFF, STATED: two parts with the same function and package now share a name. That is
deliberate, because the detail sheet prints the MPN on its own line directly beneath the headline
and the list carries it too. A part whose data yields no real descriptor still degrades to its MPN,
so nothing becomes anonymous.

Pure + deterministic: same specs -> same name. Used by the rebuild to re-name the library
consistently, and by ingest so new parts are named the same way. The MPN stays the stable anchor
in the record's `mpn` field, so a name is a readable label, never an identity."""

from __future__ import annotations

import re

# Unit tokens normalized to their symbol form, longest-first so "kOhms" wins before "Ohms".
_UNITS: tuple[tuple[str, str], ...] = (
    ("kOhms", "kΩ"), ("kOhm", "kΩ"), ("MOhms", "MΩ"), ("MOhm", "MΩ"),
    ("mOhms", "mΩ"), ("Ohms", "Ω"), ("Ohm", "Ω"),
    ("uF", "µF"), ("uH", "µH"), ("VDC", "V"),
)

# Plurals -> singular for functional descriptors (distributor `Product Type` strings are plural).
_SINGULAR: dict[str, str] = {
    "Switches": "Switch", "MOSFETs": "MOSFET", "LEDs": "LED", "Beads": "Bead",
    "Diodes": "Diode", "ICs": "IC", "Housings": "Housing", "Oscillators": "Oscillator",
    "Crystals": "Crystal", "Sockets": "Socket", "Gates": "Gate", "Buffers": "Buffer",
    "Encoders": "Encoder", "Inverters": "Inverter", "Flops": "Flop", "Controllers": "Controller",
    "Regulators": "Regulator", "Circuits": "Circuit", "Drivers": "Driver",
    "Microcontrollers": "Microcontroller", "Converters": "Converter", "Contacts": "Contact",
}

# Descriptors too generic/garbled to name a part by (bad scraped Product Type); fall back instead.
_JUNK = {"Tray", "Barricade Tape", "Labels", "Label", ""}

_PAREN = re.compile(r"\s*\(.*?\)")


def _flat(specs: dict) -> dict:
    """Spec bag flattened to {key: str}: a value may be a Sourced (.value), a dict ({'value':..}),
    or a bare scalar."""
    out: dict[str, str] = {}
    for k, v in (specs or {}).items():
        if hasattr(v, "value"):
            out[k] = "" if v.value is None else str(v.value)
        elif isinstance(v, dict):
            out[k] = "" if v.get("value") is None else str(v.get("value"))
        else:
            out[k] = "" if v is None else str(v)
    return out


def _tight(s: str) -> str:
    """A spec value tightened for a name: drop parentheticals, symbolize units, and glue a number
    to its unit — "100 kOhms" -> "100kΩ", "50 VDC" -> "50V", "1 uF" -> "1µF"."""
    s = _PAREN.sub("", str(s or "")).strip()
    for a, b in _UNITS:
        s = s.replace(a, b)
    return re.sub(r"([\d.]+)\s+([a-zA-ZµΩ%°]+)", r"\1\2", s).strip()


def _pkg(f: dict) -> str:
    """The package/case token: prefer the imperial case code (0603), strip the metric parenthetical,
    and collapse a physical size ("3.2 mm x 2.5 mm" -> "3.2x2.5mm")."""
    p = _PAREN.sub("", str(f.get("Case Code - in") or f.get("Package") or "")).strip()
    p = re.sub(r"\s*mm\s*x\s*", "x", p)
    return re.sub(r"\s*mm\b", "mm", p)


# Endings where a trailing "s" is NOT a plural, so the generic rule below must leave them alone:
# "Bus", "Class", "Chassis", "Bias", "Gas". Checked against the WHOLE word, not just its last two
# letters, so a genuine plural ending in one of these letter pairs still singularises.
_NOT_PLURAL_ENDINGS = ("ss", "us", "is", "as")

# Words the ending rule gets WRONG, because they are singular and end in a bare "s". Measured, not
# imagined: "Lens" became "Len" and "Series" became "Serie", and both appear in real distributor
# fields ("Series" is a spec key on the owner's own record).
_NOT_PLURAL_WORDS = frozenset({"lens", "series", "news", "means", "species"})


def _singular(t: str) -> str:
    t = _PAREN.sub("", str(t or "")).strip()
    for a, b in _SINGULAR.items():
        t = re.sub(rf"\b{a}\b", b, t)
    # Then a conservative generic rule on the HEAD NOUN only, because the explicit map above cannot
    # keep up with the vocabulary distributors invent ("Op Amps", "ESD Suppressors", "Thyristors").
    # Only the last word is touched: in "ESD Protection Diodes" the head noun is what pluralises,
    # and a modifier such as "Communications" is legitimately plural.
    words = t.split()
    if words:
        head = words[-1]
        low = head.lower()
        if (
            low.endswith("s")
            and not low.endswith(_NOT_PLURAL_ENDINGS)
            and low not in _NOT_PLURAL_WORDS
            and len(head) > 3
        ):
            words[-1] = head[:-1]
            t = " ".join(words)
    return t


# Where a FUNCTION description can be found, best first. Ordered deliberately: the category fields
# say what a part IS, while `Type` is often a parameter of the part rather than its purpose. Reading
# `Type` first is what produced "Steering" for an ESD protection array whose own `Product Category`
# said "ESD Protection Diodes / TVS Diodes".
_DESCRIPTOR_KEYS: tuple[str, ...] = (
    "Product Category", "Product Type", "Product", "Subcategory",
    "LCSC Category", "LCSC Warehouse Category", "Type",
)


def _descriptor(g, description: str = "") -> str:
    """The most human function name the record can support, or "" if it can support none."""
    for key in _DESCRIPTOR_KEYS:
        candidate = _short_type(g(key, ""))
        if candidate and candidate not in _JUNK:
            return candidate
    # Last resort: the leading clause of the human description.
    return (description or "").split(",")[0][:32].strip()


def _channels(g) -> str:
    """"6-Channel" for a multi-channel part. A single channel is not worth saying."""
    raw = re.sub(r"\D", "", str(g("Number of Channels", "") or ""))
    return f"{raw}-Channel" if raw and raw != "1" else ""


def _short_type(v: str) -> str:
    """A concise functional descriptor from a verbose distributor Product Type: keep the first
    segment before an "&"/","/" - " list, then singularize ("Encoders, Decoders, ..." -> "Encoder",
    "Buffers & Line Drivers" -> "Buffer", "ARM Microcontrollers - MCU" -> "ARM Microcontroller")."""
    v = re.split(r"\s*[&,/]\s*| - ", str(v or ""))[0]
    return _singular(v)


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def propose_component_name(category: str, specs: dict, mpn: str = "", description: str = "") -> str:
    """The proper name for a part in `category` with this scraped `specs` bag. Empty specs degrade
    to the MPN (never a crash)."""
    f = _flat(specs)
    g = f.get
    P = _pkg(f)

    if category == "Resistors":
        return _join(_tight(g("Resistance", "")), g("Tolerance", ""), _tight(g("Power Rating", "")), P) or mpn

    if category == "Capacitors":
        die = _PAREN.sub("", str(g("Dielectric", "") or "")).strip()  # "C0G (NP0)" -> "C0G"
        return _join(_tight(g("Capacitance", "")), die, _tight(g("Voltage Rating DC", "")),
                     g("Tolerance", ""), P) or mpn

    if category == "Inductors":
        if g("Impedance"):  # a ferrite bead is specified by impedance @ its test frequency
            tf = _tight(g("Test Frequency", ""))
            imp = _tight(g("Impedance", ""))
            return _join("Ferrite Bead", f"{imp}@{tf}" if tf else imp,
                         _tight(g("Maximum DC Current", "")), P) or mpn
        return _join(_tight(g("Inductance", "")), g("Tolerance", ""),
                     _tight(g("Maximum DC Current", "")), "Power Inductor", P) or mpn

    if category == "Crystals & Oscillators":
        return _join(_tight(g("Frequency", "")), "Crystal", _tight(g("Load Capacitance", "")), P) or mpn

    if category == "Diodes":
        color = g("Illumination Color", "")
        if color or "LED" in str(g("Product Type", "") or ""):
            return _join(color, "LED", _tight(g("Vf - Forward Voltage", "")), P) or mpn
        # An LED is looked up by COLOUR, so that branch above keeps its lead. Every other diode
        # takes the richest available description rather than its `Type`, which for a protection
        # diode is a parameter ("Steering (Rail to Rail)") and not a function.
        return _join(_channels(g), _descriptor(g, description) or "Diode",
                     _tight(g("Vf - Forward Voltage", "")), P) or mpn

    if category == "Transistors":
        return _join(g("Transistor Polarity", ""),
                     _singular(g("Product Category", "") or "Transistor"),
                     _tight(g("Vds - Drain-Source Breakdown Voltage", "")), mpn, P) or mpn

    if category == "Connectors":
        rows = int(re.sub(r"\D", "", str(g("Number of Rows", "") or "1")) or 1)
        pos = re.sub(r"\D", "", str(g("Number of Positions", "") or ""))
        base = "Pin Header" if "Pin" in str(g("Contact Gender", "") or g("Type", "") or "") \
            else (_singular(g("Type", "")) or "Connector")
        if base in _JUNK or "Mount" in base:
            base = "Connector"
        grid = f"{rows}x{int(int(pos) / rows):02d}" if pos and rows else ""
        return _join(base, grid, _tight(g("Pitch", "")), P) or mpn

    if category == "Switches":
        typ = _singular(g("Type", "") or "")
        if typ and not any(t in typ for t in ("Switch", "MUX", "Limit")):
            typ = f"{typ} Switch"
        return _join(g("Contact Form", ""), typ or _short_type(g("Product Type", "")), mpn, P) or mpn

    # ICs, Modules, Electromechanical, and anything else: the most human function the record can
    # support, plus a channel count where the part has one, plus the package.
    return _join(_channels(g), _descriptor(g, description), P) or mpn


def propose_component_name_from_record(record) -> str:
    """Convenience over a PartRecord: reads its category, specs, mpn, and description."""
    return propose_component_name(
        getattr(record, "category", "") or "",
        getattr(record, "specs", {}) or {},
        getattr(record, "mpn", "") or "",
        getattr(record, "description", "") or "",
    )


def _resistor_value(record, *, keep_ohm: bool) -> str:
    """The tightened Resistance for a resistor record. The schematic/BOM convention strips a
    trailing Ω ("5.05kΩ" -> "5.05k"); the human display keeps it ("5.05kΩ")."""
    f = _flat(getattr(record, "specs", {}) or {})
    r = _tight(f.get("Resistance", ""))
    if keep_ohm:
        return r
    return r[:-1] if r.endswith("Ω") else r


def derive_value(record) -> str:
    """The schematic/BOM Value for a part: a passive's parametric value ("5.05k", "1µF",
    "4.7µH") from its normalized specs; an active's MPN. Blank for a passive whose defining
    spec is missing (never a guess). Pure + deterministic (reuses _flat/_tight)."""
    category = getattr(record, "category", "") or ""
    f = _flat(getattr(record, "specs", {}) or {})
    g = f.get
    if category == "Resistors":
        return _resistor_value(record, keep_ohm=False)  # schematic convention: strip the Ω
    if category == "Capacitors":
        return _tight(g("Capacitance", ""))
    if category == "Inductors":
        return _tight(g("Impedance", "")) or _tight(g("Inductance", ""))
    return getattr(record, "mpn", "") or ""


def derive_display_value(record) -> str:
    """The HUMAN-FACING value for a part (the Altium status modal, any UI): identical to
    derive_value EXCEPT a resistor keeps its Ω unit ("5.05kΩ", not "5.05k"). One source of
    truth: only the resistor branch differs; every other category delegates to derive_value.
    Pure + deterministic."""
    category = getattr(record, "category", "") or ""
    if category == "Resistors":
        return _resistor_value(record, keep_ohm=True)
    return derive_value(record)
