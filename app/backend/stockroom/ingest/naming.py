"""Propose an entry name, display name, and category for a staged part (spec
section 5, stage 3). Proposals only; the user confirms or overrides in review."""

from __future__ import annotations

import re

# Keyword -> category, checked in order; first hit wins. Ordered so specific
# terms (regulator, oscillator) are not shadowed by generic ones.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("resistor", "Resistors"),
    ("capacitor", "Capacitors"),
    ("inductor", "Inductors"),
    ("ferrite", "Inductors"),
    ("crystal", "Crystals & Oscillators"),
    ("oscillator", "Crystals & Oscillators"),
    ("resonator", "Crystals & Oscillators"),
    ("diode", "Diodes"),
    ("led", "Diodes"),
    ("transistor", "Transistors"),
    ("mosfet", "Transistors"),
    ("connector", "Connectors"),
    ("receptacle", "Connectors"),
    ("header", "Connectors"),
    ("switch", "Switches"),
    ("button", "Switches"),
    ("relay", "Electromechanical"),
    ("motor", "Electromechanical"),
    ("buzzer", "Electromechanical"),
    ("sensor", "Sensors"),
    ("accelerometer", "Sensors"),
    ("gyroscope", "Sensors"),
    ("module", "Modules"),
    ("regulator", "ICs"),
    ("microcontroller", "ICs"),
    ("amplifier", "ICs"),
    ("ic", "ICs"),
)

_FORBIDDEN = re.compile(r"[{}\s]+")


def _sanitize(name: str) -> str:
    return _FORBIDDEN.sub("_", name).strip("_")


def propose_entry_name(symbol_name: str, mpn: str = "") -> str:
    base = mpn.strip() or symbol_name.strip()
    cleaned = _sanitize(base)
    return cleaned or "Part"


def propose_display_name(symbol_name: str, mpn: str = "") -> str:
    return mpn.strip() or symbol_name.strip() or "Part"


def propose_category(text: str) -> str:
    low = text.lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        # Tolerate a trailing plural 's' so a distributor's plural "Product Category" string
        # ("Resistors", "Ceramic Capacitors", "Connectors") classifies, not just singular text.
        if re.search(rf"\b{re.escape(keyword)}s?\b", low):
            return category
    return "Other"
