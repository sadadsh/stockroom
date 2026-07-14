"""M7e: net-class reconciliation + fab-floor validation (ported COMPUTE from the
retired nd_netclass_manager, adapted to the real KiCad 10 net-class shape).

Reconcile is a SAFE-MERGE: an editor loads every class, edits some, and saves the
set; reconcile field-merges each submission onto the same-named existing class
(preserving KiCad-internal fields the UI never models, e.g. tuning_profile /
diff_pair_via_gap / colors), preserves classes the editor did not touch, honors
explicit deletes, and fills KiCad-10 defaults for a brand-new class. Validation
flags below-fab-floor dimensions as non-blocking amber findings.
"""

from __future__ import annotations

from stockroom.projects import standards as st


# --- reconcile_classes -------------------------------------------------------

def test_reconcile_updates_an_existing_class_by_name_field_merge():
    existing = [
        {"name": "Default", "clearance": 0.2, "track_width": 0.2, "tuning_profile": "keepme"},
    ]
    submitted = [{"name": "Default", "track_width": 0.15}]
    out = st.reconcile_classes(existing, submitted)
    default = next(c for c in out if c["name"] == "Default")
    assert default["track_width"] == 0.15  # the edit landed
    assert default["clearance"] == 0.2  # untouched field preserved
    assert default["tuning_profile"] == "keepme"  # KiCad-internal field the UI never sent, preserved


def test_reconcile_preserves_an_unmanaged_class_untouched():
    # a class the editor did not submit (and did not delete) stays byte-for-byte.
    existing = [{"name": "Default", "clearance": 0.2}, {"name": "HIDDEN", "clearance": 0.9, "x": 1}]
    submitted = [{"name": "Default", "clearance": 0.15}]
    out = st.reconcile_classes(existing, submitted)
    hidden = next(c for c in out if c["name"] == "HIDDEN")
    assert hidden == {"name": "HIDDEN", "clearance": 0.9, "x": 1}


def test_reconcile_honors_an_explicit_delete():
    existing = [{"name": "Default"}, {"name": "OLD"}]
    out = st.reconcile_classes(existing, [{"name": "Default"}], deleted=["OLD"])
    assert [c["name"] for c in out] == ["Default"]


def test_reconcile_delete_wins_even_if_also_submitted():
    existing = [{"name": "Default"}, {"name": "OLD"}]
    out = st.reconcile_classes(existing, [{"name": "OLD"}], deleted=["OLD"])
    assert [c["name"] for c in out] == ["Default"]


def test_reconcile_adds_a_new_class_with_kicad10_defaults():
    existing = [{"name": "Default", "clearance": 0.2}]
    submitted = [{"name": "Default", "clearance": 0.2}, {"name": "PWR", "track_width": 0.4}]
    out = st.reconcile_classes(existing, submitted)
    pwr = next(c for c in out if c["name"] == "PWR")
    assert pwr["track_width"] == 0.4  # the submitted value
    # KiCad-10 required fields are materialised so the class is valid on disk
    for key in ("clearance", "via_diameter", "via_drill", "diff_pair_via_gap",
                "microvia_diameter", "microvia_drill", "priority", "tuning_profile",
                "schematic_color", "pcb_color", "wire_width", "bus_width", "line_style"):
        assert key in pwr, f"new class missing KiCad-10 field {key}"


def test_reconcile_keeps_default_first_and_preserves_order():
    existing = [{"name": "Default"}, {"name": "A"}, {"name": "B"}]
    submitted = [{"name": "A"}, {"name": "Default"}, {"name": "B"}, {"name": "C"}]
    out = st.reconcile_classes(existing, submitted)
    names = [c["name"] for c in out]
    assert names[0] == "Default"  # Default is never reordered away from the front
    assert names == ["Default", "A", "B", "C"]  # existing order preserved, new appended


def test_reconcile_does_not_mutate_inputs():
    existing = [{"name": "Default", "clearance": 0.2}]
    submitted = [{"name": "Default", "clearance": 0.15}]
    st.reconcile_classes(existing, submitted)
    assert existing[0]["clearance"] == 0.2
    assert submitted[0]["clearance"] == 0.15


# --- validate_classes --------------------------------------------------------

def _sound_class(name="Sig", **over):
    base = {
        "name": name, "clearance": 0.2, "track_width": 0.2, "via_diameter": 0.6,
        "via_drill": 0.3, "wire_width": 6, "bus_width": 12, "priority": 1,
    }
    base.update(over)
    return base


def test_validate_flags_below_floor_track():
    floor = st.FAB_FLOORS["oshpark_2"]  # min_track 0.1524
    findings = st.validate_classes([_sound_class(track_width=0.1)], floor)
    assert any("track" in f["issue"] for f in findings)
    assert findings[0]["netclass"] == "Sig"


def test_validate_sound_class_against_none_floor_is_clean():
    findings = st.validate_classes([_sound_class()], st.FAB_FLOORS["none"])
    assert findings == []


def test_validate_flags_drill_not_smaller_than_via():
    findings = st.validate_classes([_sound_class(via_diameter=0.4, via_drill=0.4)], st.FAB_FLOORS["none"])
    assert any("drill" in f["issue"] and "via" in f["issue"] for f in findings)


def test_validate_flags_annular_ring_below_floor():
    # via 0.5 drill 0.45 -> annular 0.025, below the 0.1016 OSH-4 floor
    findings = st.validate_classes(
        [_sound_class(via_diameter=0.5, via_drill=0.45)], st.FAB_FLOORS["oshpark_4"]
    )
    assert any("annular" in f["issue"] for f in findings)


def test_validate_flags_diff_pair_width_without_gap():
    findings = st.validate_classes(
        [_sound_class(diff_pair_width=0.2, diff_pair_gap=0)], st.FAB_FLOORS["none"]
    )
    assert any("gap" in f["issue"] for f in findings)


def test_validate_does_not_flag_shared_priority():
    # KiCad-10 does NOT require unique net-class priorities: priority is a resolution-order
    # tiebreaker whose default is 0, so many classes legitimately share it. Flagging a shared
    # priority produced huge bogus findings on real projects (e.g. "duplicate priority 0" over
    # 200+ classes) and self-triggered on every new class (NETCLASS_DEFAULTS priority is 0).
    findings = st.validate_classes(
        [_sound_class("A", priority=0), _sound_class("B", priority=0)], st.FAB_FLOORS["none"]
    )
    assert not any("priority" in f["issue"] for f in findings)


def test_validate_ignores_absent_wire_and_bus_on_a_minimal_class():
    # Real KiCad-10 omits wire_width/bus_width (and priority/diff-pair) from a class when they
    # equal the schematic-editor default: the on-disk Default class is literally just
    # {name, clearance, track_width, via_diameter, via_drill}. An omitted key is valid data,
    # NOT a below-floor risk, so validation must not fabricate a "non-positive wire/bus stroke"
    # finding on it (this ran on the editor open path, so it hit every real project).
    minimal_default = {
        "name": "Default", "clearance": 0.2, "track_width": 0.2,
        "via_diameter": 0.6, "via_drill": 0.3,
    }
    assert st.validate_classes([minimal_default], st.FAB_FLOORS["none"]) == []


def test_validate_still_flags_a_present_non_positive_stroke():
    # a class that DOES carry wire_width/bus_width and sets one to 0 is still a real defect.
    findings = st.validate_classes([_sound_class(wire_width=0)], st.FAB_FLOORS["none"])
    assert any("stroke" in f["issue"] for f in findings)


def test_validate_accepts_a_floor_key_string():
    # convenience: a fab-floor key resolves to its floor
    findings = st.validate_classes([_sound_class(track_width=0.1)], "oshpark_2")
    assert any("track" in f["issue"] for f in findings)


def test_fab_floors_have_labels_and_expected_keys():
    for key, floor in st.FAB_FLOORS.items():
        assert "label" in floor
        for k in ("min_clearance", "min_track", "min_via", "min_drill", "min_annular"):
            assert k in floor, f"{key} floor missing {k}"
