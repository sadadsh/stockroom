"""Derive a proper, spec-aware component name from a part's scraped data — "what it IS", not an
opaque MPN (owner directive 2026-07-19). Passives lead with value + the defining specs (X7R
dielectric + voltage for a cap, power for a resistor, impedance@frequency for a ferrite); actives
lead with a concise function (from the `Type`/`Product Type` spec) + MPN; the package always trails.

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


def _singular(t: str) -> str:
    t = _PAREN.sub("", str(t or "")).strip()
    for a, b in _SINGULAR.items():
        t = re.sub(rf"\b{a}\b", b, t)
    return t


def _short_type(v: str) -> str:
    """A concise functional descriptor from a verbose distributor Product Type: keep the first
    segment before an "&"/","/" - " list, then singularize ("Encoders, Decoders, ..." -> "Encoder",
    "Buffers & Line Drivers" -> "Buffer", "ARM Microcontrollers - MCU" -> "ARM Microcontroller")."""
    v = re.split(r"\s*[&,]\s*| - ", str(v or ""))[0]
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
        return _join(_singular(g("Type", "") or "Diode"), _tight(g("Vf - Forward Voltage", "")), P) or mpn

    if category == "Transistors":
        return _join(g("Transistor Polarity", ""), _singular(g("Product Category", "") or "Transistor"),
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

    # ICs, Modules, Electromechanical, and anything else: a concise function + MPN + package.
    t = _short_type(g("Product Type", "") or g("Type", ""))
    if t in _JUNK:
        alt = _singular(g("Type", ""))
        t = alt if alt not in _JUNK else ""
    if not t:  # last resort: the leading clause of the human description
        t = (description or "").split(",")[0][:24].strip()
    return _join(t, mpn, P) or mpn


def propose_component_name_from_record(record) -> str:
    """Convenience over a PartRecord: reads its category, specs, mpn, and description."""
    return propose_component_name(
        getattr(record, "category", "") or "",
        getattr(record, "specs", {}) or {},
        getattr(record, "mpn", "") or "",
        getattr(record, "description", "") or "",
    )
