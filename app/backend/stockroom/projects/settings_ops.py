"""Project-settings compute for the M7f Editor (board setup + thickness).

Pure, Qt-free helpers that describe the editable board-setup surface and validate
editor input BEFORE it reaches the byte-preserving Board writer. The keys and their
kinds come from kicad/board.py (the one source of truth for what a `.kicad_pcb
(setup ...)` block supports); this module only shapes them for the API/editor and
guards the input, so an unsupported key is an honest error instead of a silent
no-op and a malformed value is a clean 400 instead of a raw float() crash deeper in.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import math

from stockroom.kicad import board as _board

# The board-setup fields the editor exposes, in display order, each tagged with the
# input kind the frontend renders. Real (setup) keys are edited directly (friendly
# aliases are not duplicated here); the sided via-protection family is expanded into
# per-side booleans (tenting_front, ...) matching Board.setup()'s read shape. Labels
# are Title Case per the design contract.
BOARD_SETUP_FIELDS: list[dict] = [
    {"key": "pad_to_mask_clearance", "kind": "length", "label": "Solder Mask Clearance"},
    {"key": "solder_mask_min_width", "kind": "length", "label": "Solder Mask Minimum Width"},
    {"key": "pad_to_paste_clearance", "kind": "length", "label": "Solder Paste Clearance"},
    {"key": "pad_to_paste_clearance_ratio", "kind": "ratio", "label": "Solder Paste Clearance Ratio"},
    {"key": "allow_soldermask_bridges_in_footprints", "kind": "bool",
     "label": "Allow Soldermask Bridges in Footprints"},
    {"key": "tenting_front", "kind": "bool", "label": "Tent Vias Front"},
    {"key": "tenting_back", "kind": "bool", "label": "Tent Vias Back"},
    {"key": "covering_front", "kind": "bool", "label": "Cover Vias Front"},
    {"key": "covering_back", "kind": "bool", "label": "Cover Vias Back"},
    {"key": "plugging_front", "kind": "bool", "label": "Plug Vias Front"},
    {"key": "plugging_back", "kind": "bool", "label": "Plug Vias Back"},
    {"key": "capping", "kind": "bool", "label": "Cap Vias"},
    {"key": "filling", "kind": "bool", "label": "Fill Vias"},
    {"key": "aux_axis_origin", "kind": "coord", "label": "Auxiliary Axis Origin"},
    {"key": "grid_origin", "kind": "coord", "label": "Grid Origin"},
]

_KIND_BY_KEY = {f["key"]: f["kind"] for f in BOARD_SETUP_FIELDS}

# KiCad's effective default for each editable BOOL field when it is ABSENT from the
# (setup) block, sourced from board.py so the two can never drift: the flat bools
# (capping/filling/allow_soldermask_bridges) default OFF; the sided via-protection family
# uses board.SIDED_DEFAULTS (tenting ON, covering/plugging OFF). Filling these on read means
# the editor shows the true state a user sees in KiCad (an absent tenting reads as ON, not a
# misleading OFF that a save would then write and flip).
BOOL_DEFAULTS: dict = {k: False for k in _board.SETUP_BOOL_KEYS}
BOOL_DEFAULTS.update(
    {
        f"{k}_{side}": _board.SIDED_DEFAULTS[k]
        for k in _board.SETUP_SIDED_KEYS
        for side in ("front", "back")
    }
)


def effective_board_setup(setup: dict) -> dict:
    """The board-setup dict the editor renders: every PRESENT key exactly as read, plus any
    absent BOOL field filled with KiCad's effective default (so an absent tenting shows ON,
    never a misleading OFF the form would let a save write and flip). Absent numeric/coord
    keys stay absent, so the form shows them blank rather than a manufactured zero."""
    out = dict(setup)
    for key, default in BOOL_DEFAULTS.items():
        out.setdefault(key, default)
    return out


def _is_number(v) -> bool:
    # A JSON bool is an int in Python; a clearance is never a boolean, so reject it.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_board_setup(values: dict) -> None:
    """Raise ValueError (mapped to a 400) when the submitted board-setup dict names an
    unsupported key or carries a malformed value. Every accepted key is one Board can
    write; a length/ratio must be a real number, a coordinate a pair of numbers, a bool
    anything Board can coerce. An empty dict is valid (nothing to write)."""
    for key, val in values.items():
        kind = _KIND_BY_KEY.get(key)
        if kind is None:
            raise ValueError(f"unsupported board-setup key: {key!r}")
        if kind in ("length", "ratio"):
            if not _is_number(val):
                raise ValueError(f"{key} must be a number, got {val!r}")
        elif kind == "coord":
            seq = list(val) if isinstance(val, (list, tuple)) else None
            if seq is None or len(seq) != 2 or not all(_is_number(x) for x in seq):
                raise ValueError(f"{key} must be a pair of numbers, got {val!r}")
        # kind == "bool": Board coerces yes/no/true/1; nothing to reject here.


def validate_thickness(value) -> None:
    """Raise ValueError when the board thickness is not a finite positive number. A zero or
    negative thickness is never valid; a non-finite one (Infinity/NaN, which stdlib json.loads
    accepts from a raw token) must be caught here as a clean 400 rather than crashing _fmt_num's
    int(inf) with an OverflowError that would map to a 500."""
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"board thickness must be a positive number, got {value!r}")


# Drift guard: every field the editor exposes must be a key Board can actually write
# (a real flat/coord key, or a per-side name of a sided via-protection key), so this
# catalog can never silently list a key that Board would ignore. Runs at import.
def _writable_keys() -> set:
    flat = set(_board.SETUP_NUMERIC_KEYS) | set(_board.SETUP_COORD_KEYS) | set(_board.SETUP_BOOL_KEYS)
    sided = {f"{k}_{side}" for k in _board.SETUP_SIDED_KEYS for side in ("front", "back")}
    return flat | sided


_unknown = {f["key"] for f in BOARD_SETUP_FIELDS} - _writable_keys()
if _unknown:  # pragma: no cover - a guard that fails loud at import if the two drift
    raise RuntimeError(f"BOARD_SETUP_FIELDS names keys Board cannot write: {sorted(_unknown)}")
