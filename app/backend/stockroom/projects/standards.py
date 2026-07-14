"""Net-class reconciliation + fab-floor validation (M7e).

COMPUTE lifted from the retired nd_netclass_manager and adapted to the real
KiCad 10 net-class shape (net_settings.classes[] in the .kicad_pro, colors as
rgba() strings, wire/bus width as integer mils). This module is pure dict-in /
dict-out; the actual byte edit is performed by kicad/project_settings.py inside a
Transaction bound to the project's own git repo.

`reconcile_classes` is a SAFE-MERGE (an editor loads every class, edits some,
saves the set): each submission field-merges onto the same-named existing class
so KiCad-internal fields the UI never models are preserved; a class the editor
did not touch is preserved untouched; explicit deletes are honored; a brand-new
class is filled with KiCad-10 defaults. `validate_classes` flags below-fab-floor
dimensions as NON-BLOCKING amber findings (the editor still saves; the risk is
surfaced, never silently swallowed and never a hard block).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

_EPS = 1e-9

# The KiCad-10 fields a net class carries on disk. A brand-new class the editor
# adds is materialised with these defaults so the written .kicad_pro is valid and
# KiCad reads it back without complaint (verified against a real KiCad 10 project).
NETCLASS_DEFAULTS: dict = {
    "clearance": 0.2,
    "track_width": 0.2,
    "via_diameter": 0.6,
    "via_drill": 0.3,
    "microvia_diameter": 0.3,
    "microvia_drill": 0.1,
    "diff_pair_width": 0.2,
    "diff_pair_gap": 0.25,
    "diff_pair_via_gap": 0.25,
    "priority": 0,
    "tuning_profile": "",
    "schematic_color": "rgba(0, 0, 0, 0.000)",
    "pcb_color": "rgba(0, 0, 0, 0.000)",
    "wire_width": 6,
    "bus_width": 12,
    "line_style": 0,
}

# Built-in fab-house dimension floors (mm), for validate-on-save. Values are the
# conservative minimums each house documents for its standard process; picking a
# floor makes the amber validation fab-aware. "none" disables the floor checks.
FAB_FLOORS: dict = {
    "none": {"label": "No fab floor", "min_clearance": 0.0, "min_track": 0.0,
             "min_via": 0.0, "min_drill": 0.0, "min_annular": 0.0},
    "jlcpcb": {"label": "JLCPCB standard", "min_clearance": 0.127, "min_track": 0.127,
               "min_via": 0.45, "min_drill": 0.2, "min_annular": 0.065},
    "oshpark_2": {"label": "OSH Park 2-layer", "min_clearance": 0.1524, "min_track": 0.1524,
                  "min_via": 0.508, "min_drill": 0.254, "min_annular": 0.127},
    "oshpark_4": {"label": "OSH Park 4-layer", "min_clearance": 0.127, "min_track": 0.127,
                  "min_via": 0.4572, "min_drill": 0.254, "min_annular": 0.1016},
}


def default_class(name: str) -> dict:
    """A brand-new net class named `name` with KiCad-10 defaults."""
    return {"name": name, **NETCLASS_DEFAULTS}


def reconcile_classes(existing, submitted, deleted=None) -> list:
    """Merge the editor's submitted classes onto the existing on-disk classes.

    - a submitted class field-merges onto the same-named existing class (the
      submission wins per field, existing fields it omits are preserved);
    - an existing class the editor neither submitted nor deleted is preserved
      untouched (never clobber a class the tool does not manage);
    - a name in `deleted` is removed even if also submitted;
    - a submitted class with no existing match is added with KiCad-10 defaults;
    - Default is kept at the front and existing order is otherwise preserved,
      new classes appended.

    Inputs are never mutated.
    """
    deleted_set = set(deleted or [])
    submitted_by_name = {c.get("name"): c for c in submitted if c.get("name")}
    result: list = []
    seen: set = set()

    for cls in existing:
        name = cls.get("name")
        if name in deleted_set:
            continue  # authoritatively removed
        if name in submitted_by_name:
            merged = dict(cls)
            merged.update(submitted_by_name[name])  # submission wins per field
            result.append(merged)
        else:
            result.append(dict(cls))  # unmanaged, preserved
        seen.add(name)

    for cls in submitted:
        name = cls.get("name")
        if name and name not in seen and name not in deleted_set:
            new = default_class(name)
            new.update(cls)  # submitted values override defaults
            result.append(new)
            seen.add(name)

    # keep Default first (KiCad convention) without otherwise reordering
    result.sort(key=lambda c: 0 if c.get("name") == "Default" else 1)
    return result


def _resolve_floor(floor) -> dict:
    if isinstance(floor, str):
        return FAB_FLOORS.get(floor, FAB_FLOORS["none"])
    return floor or FAB_FLOORS["none"]


def validate_classes(classes, floor) -> list:
    """Return a list of {netclass, issue} for every below-floor / inconsistent
    dimension. An empty list means every class is fab-sound. Non-blocking: the
    caller still writes, but surfaces these as amber warnings. `floor` may be a
    FAB_FLOORS key or a floor dict.
    """
    prof = _resolve_floor(floor)
    findings: list = []

    def _num(cls, key):
        # Real KiCad-10 OMITS a field from a class when it equals the editor default (the
        # on-disk Default class is just name/clearance/track_width/via_diameter/via_drill).
        # An absent key is valid data, not a below-floor risk, so return None and skip the
        # check rather than reading it as 0 and fabricating a violation.
        v = cls.get(key)
        return None if v is None else float(v)

    for cls in classes:
        name = cls.get("name", "?")
        clearance, track = _num(cls, "clearance"), _num(cls, "track_width")
        via, drill = _num(cls, "via_diameter"), _num(cls, "via_drill")
        wire, bus = _num(cls, "wire_width"), _num(cls, "bus_width")
        dp_width, dp_gap = _num(cls, "diff_pair_width"), _num(cls, "diff_pair_gap")

        def bad(issue: str, _name=name):
            findings.append({"netclass": _name, "issue": issue})

        if clearance is not None and clearance < prof["min_clearance"] - _EPS:
            bad(f"clearance {clearance} below fab min {prof['min_clearance']}")
        if track is not None and track < prof["min_track"] - _EPS:
            bad(f"track width {track} below fab min {prof['min_track']}")
        if via is not None and via < prof["min_via"] - _EPS:
            bad(f"via diameter {via} below fab min {prof['min_via']}")
        if drill is not None and drill < prof["min_drill"] - _EPS:
            bad(f"via drill {drill} below fab min {prof['min_drill']}")
        if via and drill and drill >= via:
            bad(f"via drill {drill} not smaller than via diameter {via}")
        elif via and drill and (via - drill) / 2 < prof["min_annular"] - _EPS:
            bad(f"annular ring {(via - drill) / 2:.4f} below fab min {prof['min_annular']}")
        # Only a PRESENT non-positive stroke is a defect; an omitted key is a KiCad default.
        if (wire is not None and wire <= 0) or (bus is not None and bus <= 0):
            bad("non-positive wire or bus stroke")
        if dp_width is not None and dp_width > 0 and (dp_gap is None or dp_gap <= 0):
            bad("diff-pair width set but no gap")

    # NOTE: no duplicate-priority check. In KiCad-10 net-class priority is a resolution-order
    # tiebreaker (default 0) that classes legitimately share, not a uniqueness constraint;
    # flagging a shared priority produced huge bogus findings on real projects.
    return findings
