"""Fab-preset catalog + stackup validators for the M7f-C editor: the physical-stackup presets the
editor offers, and the guards that reject bad editor input BEFORE it reaches the byte-preserving
`kicad/stackup.py` writer.

Pure, Qt-free. Ported by behavior from the retired `nd_fab_presets.py` (OSH Park 2/4-layer), the two
presets whose numbers OSH Park publishes; I do NOT fabricate presets (e.g. JLCPCB) whose exact stack
I cannot verify, so each preset carries a `verify_note` telling the user to confirm the dielectric
constants / thicknesses against the fab's current published stackup before an impedance-controlled
production order (the retired app's honest posture). This module owns ONLY the physical stack; the
design-rule fab FLOORS (min track / clearance / via) are a separate concern in `projects/standards.py`
(M7e), so the two never duplicate.

The dielectric epsilon_r / loss_tangent carry KiCad's generic FR4 defaults (4.5 / 0.02) as the
retired app ships them; a user who needs impedance accuracy sets the exact per-dielectric values
through the per-field editor (they are surfaced and editable), which is why the verify_note matters.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import math

# KiCad's generic FR4 dielectric constants, the neutral default the retired presets ship. Surfaced
# and per-dielectric-editable in the editor; the verify_note tells the user to confirm them.
_FR4_ER = 4.5
_FR4_DF = 0.02

# 1 oz outer / 0.5 oz inner copper, in mm (OSH Park's clad+plated weights, from nd_fab_presets).
_CU_1OZ = 0.0432
_CU_HALF_OZ = 0.0175


def _diel(kind: str, thickness: float, material: str, er: float = _FR4_ER, df: float = _FR4_DF) -> dict:
    return {"kind": "dielectric", "type": kind, "thickness": thickness, "material": material,
            "epsilon_r": er, "loss_tangent": df}


def _cu(thickness: float) -> dict:
    return {"kind": "copper", "thickness": thickness}


# The physical-stackup presets (copper count + dielectric geometry + finish + soldermask colour +
# overall board thickness). `physical` is the ordered copper/dielectric core the stackup writer wraps
# with the fixed silk/paste/mask frame; the copper NAMES come from the board being edited, so a
# preset is layer-count-guarded (a mismatch is refused, never silently desynced from the board).
FAB_PRESETS: dict[str, dict] = {
    "oshpark_2": {
        "key": "oshpark_2",
        "label": "OSH Park 2-Layer",
        "layers": 2,
        "board_thickness_mm": 1.6,
        "finish": "ENIG",
        "soldermask_color": "Purple",
        "physical": [
            _cu(_CU_1OZ),
            _diel("core", 1.51, "FR4"),
            _cu(_CU_1OZ),
        ],
        "verify_note": (
            "OSH Park 2-layer: 1.6 mm FR4, 1 oz copper, ENIG, purple mask (docs.oshpark.com). "
            "Confirm the dielectric constant / loss tangent against the fab's current stackup "
            "before an impedance-controlled order."
        ),
    },
    "oshpark_4": {
        "key": "oshpark_4",
        "label": "OSH Park 4-Layer",
        "layers": 4,
        "board_thickness_mm": 1.6,
        "finish": "ENIG",
        "soldermask_color": "Purple",
        "physical": [
            _cu(_CU_1OZ),
            _diel("prepreg", 0.1999, "FR408HR 2113"),
            _cu(_CU_HALF_OZ),
            _diel("core", 0.9906, "FR408HR"),
            _cu(_CU_HALF_OZ),
            _diel("prepreg", 0.1999, "FR408HR 2113"),
            _cu(_CU_1OZ),
        ],
        "verify_note": (
            "OSH Park 4-layer: 1.6 mm FR408HR (190Tg), 1 oz outer / 0.5 oz inner copper, ENIG, "
            "purple mask (docs.oshpark.com/services/four-layer). The per-dielectric thicknesses and "
            "the FR408HR dielectric constant / loss tangent (shipped here as generic FR4 defaults) "
            "MUST be confirmed against the fab's current published stackup before an "
            "impedance-controlled order."
        ),
    },
}

# Catalog metadata keys surfaced to the editor's preset picker (the `physical` core stays server-side;
# the editor previews the resulting stack through the preview endpoint instead).
_CATALOG_KEYS = ("key", "label", "layers", "board_thickness_mm", "finish", "soldermask_color",
                 "verify_note")


def preset_catalog() -> list[dict]:
    """The fab presets as lean, API-shaped catalog entries (Title Case labels + the board summary +
    the verify_note), in a stable order, for the editor's preset picker."""
    return [{k: FAB_PRESETS[key][k] for k in _CATALOG_KEYS} for key in FAB_PRESETS]


def get_preset(key: str):
    """The full preset dict (including its physical stack) for `key`, or None."""
    return FAB_PRESETS.get(key)


def validate_preset_apply(preset_key: str, board_copper_count: int) -> dict:
    """Return the preset for `preset_key`, or raise ValueError (-> 400) when it is unknown or its
    copper-layer count does not match the board's. The stackup's copper layers MUST match the
    board's own `(layers ...)` copper definition, so a mismatched preset is refused rather than
    written (which would desync the stackup from the board)."""
    p = FAB_PRESETS.get(preset_key)
    if p is None:
        raise ValueError(f"unknown fab preset: {preset_key!r}")
    if p["layers"] != board_copper_count:
        raise ValueError(
            f"the {p['label']} preset is {p['layers']}-layer but this board has "
            f"{board_copper_count} copper layer(s); pick a preset that matches the board"
        )
    return p


def _is_number(v) -> bool:
    # a JSON bool is an int in Python; a thickness / dk / df is never a boolean, so reject it
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_positive(name: str, v) -> None:
    if not _is_number(v) or not math.isfinite(float(v)) or float(v) <= 0:
        raise ValueError(f"{name} must be a positive number, got {v!r}")


_NUMERIC_FIELDS = ("thickness", "epsilon_r", "loss_tangent")
_STRING_FIELDS = ("material",)
_LAYER_FIELDS = _NUMERIC_FIELDS + _STRING_FIELDS


def validate_field_edits(copper_finish=None, dielectric_constraints=None, layer_edits=None) -> None:
    """Raise ValueError (-> 400) when a submitted per-field stackup edit is malformed: a blank
    copper_finish, a non-bool dielectric_constraints, an unknown layer field, a non-positive /
    non-finite thickness / epsilon_r / loss_tangent, or a blank material. An empty edit set is valid
    here (project_ops rejects 'nothing to change' with its own message)."""
    if copper_finish is not None:
        if not isinstance(copper_finish, str) or not copper_finish.strip():
            raise ValueError("copper finish must be a non-empty string")
    if dielectric_constraints is not None and not isinstance(dielectric_constraints, bool):
        raise ValueError("dielectric constraints must be a boolean")
    for lname, fields in (layer_edits or {}).items():
        if not isinstance(fields, dict):
            raise ValueError(f"{lname}: a layer edit must be a field object")
        for key, val in fields.items():
            if val is None:
                continue
            if key not in _LAYER_FIELDS:
                raise ValueError(f"{lname}: unknown stackup field {key!r}")
            if key in _NUMERIC_FIELDS:
                _validate_positive(f"{lname} {key}", val)
            elif not isinstance(val, str) or not val.strip():
                raise ValueError(f"{lname} {key} must be a non-empty string")


# Import-time drift guard: every preset's copper count must equal its declared `layers` (so the
# layer-count guard and the frontend picker can never disagree with the generated stack).
for _key, _p in FAB_PRESETS.items():  # pragma: no cover - a guard that fails loud at import on drift
    _copper = [e for e in _p["physical"] if e["kind"] == "copper"]
    if len(_copper) != _p["layers"]:
        raise RuntimeError(
            f"fab preset {_key!r} declares {_p['layers']} layers but its stack has {len(_copper)} copper"
        )
