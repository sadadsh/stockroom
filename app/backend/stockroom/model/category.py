"""Fixed component-category taxonomy and the library-naming rules.

Each category maps to exactly one KiCad symbol library and one footprint
library, named SR-<slug>. The slug keeps nicknames filesystem-safe and
self-documenting inside KiCad lib_ids (spec sections 3 and 4).
"""

from __future__ import annotations

import re

CATEGORIES: tuple[str, ...] = (
    "Resistors",
    "Capacitors",
    "Inductors",
    "Diodes",
    "Transistors",
    "ICs",
    "Connectors",
    "Switches",
    "Crystals & Oscillators",
    "Sensors",
    "Modules",
    "Electromechanical",
    "Other",
)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, collapse every non-alphanumeric run to a single underscore,
    strip leading/trailing underscores. Deterministic and reversible enough for
    stable ids and library nicknames."""
    return _SLUG_RE.sub("_", text).strip("_").lower()


def is_valid_category(name: str) -> bool:
    return name in CATEGORIES


def _require(name: str) -> None:
    if not is_valid_category(name):
        raise ValueError(f"unknown category: {name!r}")


def _lib_slug(name: str) -> str:
    """Category token for a library name: slugify but keep original casing of
    the alphanumerics (so ICs stays ICs, not ics)."""
    _require(name)
    token = _SLUG_RE.sub("_", name).strip("_")
    return token


def category_nickname(name: str) -> str:
    return f"SR-{_lib_slug(name)}"


def category_symbol_lib(name: str) -> str:
    return f"{category_nickname(name)}.kicad_sym"


def category_footprint_lib(name: str) -> str:
    return f"{category_nickname(name)}.pretty"
