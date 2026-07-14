"""Object-conform compute for the M7f-B Editor: the category catalog the editor renders and the
validators that guard editor input BEFORE it reaches the byte-preserving conform writer.

Pure, Qt-free. The categories come from kicad/conform.py (the one source of truth for what a
conform can touch); this module only shapes them for the API/editor with Title Case labels +
suggested starting sizes, and guards a submitted target so an unknown category or a non-positive
size/thickness is a clean 400 rather than a silent no-op.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import math

from stockroom.kicad import conform

# The PCB / schematic conform categories the editor exposes, each with a Title Case label (design
# contract) and a one-line hint of what it covers. Keys mirror conform.PCB_CATEGORIES /
# SCH_CATEGORIES exactly (a drift guard at import fails loud if the two ever diverge).
PCB_CONFORM_CATEGORIES: list[dict] = [
    {"key": "silk", "label": "Silk Text", "hint": "Front and back silkscreen text (F/B.SilkS)"},
    {"key": "fab", "label": "Fab Text", "hint": "Front and back fabrication text (F/B.Fab)"},
    {"key": "copper", "label": "Copper Text", "hint": "Front and back copper text (F/B.Cu)"},
]
SCH_CONFORM_CATEGORIES: list[dict] = [
    {"key": "text", "label": "Schematic Text", "hint": "Sheet graphic text notes"},
    {"key": "labels", "label": "Net Labels", "hint": "Local, global, and hierarchical labels"},
]

# Suggested starting size/thickness (mm) per category, KiCad's own defaults, offered by the editor
# as a starting point (the user can change them). PCB silk/fab/copper default to 1.0mm / 0.15mm;
# schematic text and labels default to KiCad's 1.27mm text size (labels carry no thickness atom).
SUGGESTED: dict[str, dict] = {
    "silk": {"size": 1.0, "thickness": 0.15},
    "fab": {"size": 1.0, "thickness": 0.15},
    "copper": {"size": 1.0, "thickness": 0.15},
    "text": {"size": 1.27, "thickness": None},
    "labels": {"size": 1.27, "thickness": None},
}

_PCB_KEYS = set(conform.PCB_CATEGORIES)
_SCH_KEYS = set(conform.SCH_CATEGORIES)


def _is_number(v) -> bool:
    # A JSON bool is an int in Python; a size/thickness is never a boolean, so reject it.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_dimension(cat: str, label: str, v) -> None:
    if not _is_number(v) or not math.isfinite(float(v)) or float(v) <= 0:
        raise ValueError(f"{cat} {label} must be a positive number, got {v!r}")


def _validate_spec(cat: str, spec) -> None:
    if not isinstance(spec, dict):
        raise ValueError(f"{cat}: a conform target must be a size/thickness object")
    size = spec.get("size")
    thickness = spec.get("thickness")
    if size is None and thickness is None:
        raise ValueError(f"{cat}: set a size or a thickness to conform this type")
    if size is not None:
        _validate_dimension(cat, "size", size)
    if thickness is not None:
        _validate_dimension(cat, "thickness", thickness)


def validate_targets(pcb_targets: dict | None, sch_targets: dict | None) -> None:
    """Raise ValueError (-> 400) when a submitted conform target names an unknown category, is not
    a size/thickness object, sets neither dimension, or carries a non-positive/non-finite size or
    thickness. An empty selection is valid here (project_ops rejects 'nothing selected' with its
    own message so the two concerns stay separate)."""
    for cat, spec in (pcb_targets or {}).items():
        if cat not in _PCB_KEYS:
            raise ValueError(f"unknown PCB conform category: {cat!r}")
        _validate_spec(cat, spec)
    for cat, spec in (sch_targets or {}).items():
        if cat not in _SCH_KEYS:
            raise ValueError(f"unknown schematic conform category: {cat!r}")
        _validate_spec(cat, spec)


def any_targets(pcb_targets: dict | None, sch_targets: dict | None) -> bool:
    """True when at least one conform category is selected across the PCB and schematic targets."""
    return bool(pcb_targets) or bool(sch_targets)


# Drift guard: every catalog category must be a category the writer knows, and every writer
# category must be catalogued (so the editor can never offer or omit one the engine disagrees on).
# Runs at import.
_cat_keys = {c["key"] for c in PCB_CONFORM_CATEGORIES} | {c["key"] for c in SCH_CONFORM_CATEGORIES}
_writer_keys = _PCB_KEYS | _SCH_KEYS
if _cat_keys != _writer_keys:  # pragma: no cover - a guard that fails loud at import on drift
    raise RuntimeError(
        f"conform category catalog {sorted(_cat_keys)} != writer categories {sorted(_writer_keys)}"
    )
if set(SUGGESTED) != _writer_keys:  # pragma: no cover - every category needs a suggested size
    raise RuntimeError(f"SUGGESTED {sorted(SUGGESTED)} != writer categories {sorted(_writer_keys)}")
