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


# --- M7f-A2: .kicad_pro settings (ERC/DRC severities, ERC pin-map, text-vars) --
# These live in the .kicad_pro (not the .kicad_pcb): ERC severities under erc.rule_severities,
# DRC severities under board.design_settings.rule_severities, the ERC pin-conflict matrix under
# erc.pin_map, project text variables at the top level. project_settings.py is the write engine
# (severities merge per-rule, pin_map replaces wholesale as a list, text_variables replaces
# wholesale so a deletion lands); this module shapes the catalogs and guards the input.

# A DRC/ERC rule severity is one of these three (KiCad's own severity set).
SEVERITY_LEVELS = ("error", "warning", "ignore")

# The 12 electrical pin types in KiCad's stored erc.pin_map row/column order. Labels are UI
# hints only; the file stores an index-addressed 12x12 matrix, so a mislabel cannot corrupt it.
ERC_PIN_TYPES = (
    "input", "output", "bidirectional", "tri_state", "passive", "free",
    "unspecified", "power_in", "power_out", "open_collector", "open_emitter",
    "no_connect",
)
ERC_PIN_MAP_SIZE = 12
# erc.pin_map / severity ints: 0 = OK, 1 = warning, 2 = error. 3 is KiCad's "unconnected"
# sentinel, tolerated on read/write so a real matrix that carries it is never rejected.
_PIN_MAP_MAX = 3

# Known KiCad-10 rule ids (verified present in a real KiCad-written project's severity maps).
# They are NOT the authoritative validation set: the file's own present keys are (a real file
# carries ~46 ERC / ~62 DRC ids and gains more across KiCad versions, so a curated subset would
# wrongly reject a real one). These only WIDEN the allowed set, so a known rule can be added even
# if a given file omits it; a submitted id must be in (file-present union this list).
ERC_RULE_IDS = (
    "bus_definition_conflict", "bus_entry_needed", "bus_to_bus_conflict", "bus_to_net_conflict",
    "different_unit_footprint", "different_unit_net", "duplicate_reference", "duplicate_sheet_names",
    "endpoint_off_grid", "extra_units", "field_name_whitespace", "footprint_filter",
    "footprint_link_issues", "four_way_junction", "ground_pin_not_ground", "hier_label_mismatch",
    "isolated_pin_label", "label_dangling", "label_multiple_wires", "lib_symbol_issues",
    "lib_symbol_mismatch", "missing_bidi_pin", "missing_input_pin", "missing_power_pin",
    "missing_unit", "multiple_net_names", "net_not_bus_member", "no_connect_connected",
    "no_connect_dangling", "pin_not_connected", "pin_not_driven", "pin_to_pin",
    "power_pin_not_driven", "same_local_global_label", "similar_label_and_power", "similar_labels",
    "similar_power", "simulation_model_issue", "single_global_label", "stacked_pin_name",
    "unannotated", "unconnected_wire_endpoint", "undefined_netclass", "unit_value_mismatch",
    "unresolved_variable", "wire_dangling",
)
DRC_RULE_IDS = (
    "annular_width", "clearance", "connection_width", "copper_edge_clearance", "copper_sliver",
    "courtyards_overlap", "creepage", "diff_pair_gap_out_of_range",
    "diff_pair_uncoupled_length_too_long", "drill_out_of_range", "duplicate_footprints",
    "extra_footprint", "footprint", "footprint_filters_mismatch", "footprint_symbol_field_mismatch",
    "footprint_symbol_mismatch", "footprint_type_mismatch", "hole_clearance", "hole_to_hole",
    "holes_co_located", "invalid_outline", "isolated_copper", "item_on_disabled_layer",
    "items_not_allowed", "length_out_of_range", "lib_footprint_issues", "lib_footprint_mismatch",
    "malformed_courtyard", "microvia_drill_out_of_range", "mirrored_text_on_front_layer",
    "missing_courtyard", "missing_footprint", "net_conflict", "npth_inside_courtyard", "padstack",
    "pth_inside_courtyard", "shorting_items", "silk_edge_clearance", "silk_over_copper",
    "silk_overlap", "skew_out_of_range", "solder_mask_bridge", "starved_thermal", "text_height",
    "text_thickness", "through_hole_pad_without_hole", "too_many_vias", "track_angle",
    "track_dangling", "track_width", "tracks_crossing", "unconnected_items", "unresolved_variable",
    "via_dangling", "zones_intersect",
)


def validate_severity_map(values: dict, allowed: set) -> None:
    """Raise ValueError (-> 400) when a submitted {rule_id: severity} map names a level KiCad
    does not know or a rule id not in `allowed` (the file's current severity keys, widened by
    the curated known-ids list). Guarding against `allowed` is what stops a typo'd id from
    injecting a junk key into the file's map on the per-rule merge. An empty map is valid
    (nothing to change)."""
    for rule, level in values.items():
        if level not in SEVERITY_LEVELS:
            raise ValueError(f"severity for {rule!r} must be one of {SEVERITY_LEVELS}, got {level!r}")
        if rule not in allowed:
            raise ValueError(f"unknown rule id: {rule!r}")


def validate_pin_map(matrix) -> None:
    """Raise ValueError (-> 400) when the submitted ERC pin-conflict matrix is not a 12x12 grid
    of severity ints in 0..3. KiCad addresses this matrix by index, so a wrong shape would map
    a value onto the wrong pin-type pair; a bool (an int in Python) is a severity index only by
    accident and is rejected."""
    if not isinstance(matrix, (list, tuple)) or len(matrix) != ERC_PIN_MAP_SIZE:
        raise ValueError(f"pin map must have {ERC_PIN_MAP_SIZE} rows")
    for row in matrix:
        if not isinstance(row, (list, tuple)) or len(row) != ERC_PIN_MAP_SIZE:
            raise ValueError(f"each pin-map row must have {ERC_PIN_MAP_SIZE} columns")
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int):
                raise ValueError(f"pin-map cell must be an integer severity, got {cell!r}")
            if not (0 <= cell <= _PIN_MAP_MAX):
                raise ValueError(f"pin-map severity must be 0..{_PIN_MAP_MAX}, got {cell}")


def reconcile_text_variables(values: dict) -> dict:
    """The complete desired text_variables map to write: every key coerced to a stripped str and
    every value coerced to str (KiCad serializes values as strings). A blank/whitespace key is a
    ValueError (-> 400). The returned map is authoritative: a key absent from it is a deletion,
    which is why project_ops writes it through the wholesale-replace path. An empty map is a valid
    'clear all'."""
    out: dict = {}
    for key, val in values.items():
        name = str(key).strip()
        if not name:
            raise ValueError("a text variable name must not be blank")
        out[name] = str(val)
    return out
