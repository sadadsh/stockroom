"""M7h projects/fields: the KiField derived rows-by-fields grid + the edit-validation shaper.

The grid is one row per unique reference designator, one column per field that appears on any
placed component, canonical KiCad fields ordered first. Reference is the row identity and is
read-only (a designator is renamed by annotation, not a field write). A reference that maps to
more than one component whose fields disagree is a duplicate-designator anomaly surfaced
non-editable; an unannotated reference is non-editable (annotate first). field_changes_by_ref
validates a batch of {ref, field, value} cell edits against the grid and returns the
{ref: {field: value}} map projects.fill.fill_document writes byte-preservingly.
"""

from __future__ import annotations

import pytest

from stockroom.projects import fields


def _c(ref, *, lib_id="Device:R", value="10k", footprint="", sheet="board.kicad_sch", **extra):
    """A placed-component dict shaped exactly like projects.fill.read_components returns."""
    props = {"Reference": ref, "Value": value, "Footprint": footprint, **extra}
    return {"ref": ref, "lib_id": lib_id, "value": value, "footprint": footprint,
            "props": props, "_sheet": sheet}


# -- build_field_grid ----------------------------------------------------------


def test_grid_one_row_per_reference_with_ordered_columns():
    comps = [
        _c("R1", value="10k", footprint="R_0402", MPN="RC0402"),
        _c("C1", lib_id="Device:C", value="100nF", footprint="C_0402"),
    ]
    grid = fields.build_field_grid(comps)
    assert [r["ref"] for r in grid["rows"]] == ["C1", "R1"]  # natural sort, C before R
    assert grid["columns"][:3] == ["Reference", "Value", "Footprint"]  # canonical first
    assert "MPN" in grid["columns"]
    r1 = next(r for r in grid["rows"] if r["ref"] == "R1")
    assert r1["fields"]["Value"] == "10k" and r1["fields"]["MPN"] == "RC0402"
    assert r1["editable"] is True and r1["unannotated"] is False
    # every row carries every column (blank when the component lacks the field), uniform grid
    c1 = next(r for r in grid["rows"] if r["ref"] == "C1")
    assert c1["fields"]["MPN"] == ""


def test_natural_sort_orders_numbers_not_lexically():
    grid = fields.build_field_grid([_c("R10"), _c("R2"), _c("R1")])
    assert [r["ref"] for r in grid["rows"]] == ["R1", "R2", "R10"]


def test_reference_column_is_read_only():
    grid = fields.build_field_grid([_c("R1")])
    assert grid["readonly_columns"] == ["Reference"]


def test_unannotated_reference_row_is_not_editable():
    grid = fields.build_field_grid([_c("R?")])
    row = grid["rows"][0]
    assert row["unannotated"] is True and row["editable"] is False
    assert grid["summary"]["unannotated"] == 1


def test_multi_unit_same_ref_merges_to_one_editable_row():
    # two unit-nodes of one multi-unit component share a ref and identical fields -> one row
    comps = [_c("U1", lib_id="Amp:LM358", value="LM358"),
             _c("U1", lib_id="Amp:LM358", value="LM358")]
    grid = fields.build_field_grid(comps)
    assert len([r for r in grid["rows"] if r["ref"] == "U1"]) == 1
    row = grid["rows"][0]
    assert row["editable"] is True and row["instances"] == 2


def test_duplicate_ref_with_conflicting_fields_is_non_editable():
    comps = [_c("R1", value="10k"), _c("R1", value="47k")]
    grid = fields.build_field_grid(comps)
    row = next(r for r in grid["rows"] if r["ref"] == "R1")
    assert row["editable"] is False and "Value" in row["conflicts"]
    assert row["fields"]["Value"] == ""  # a conflicting value is not fabricated
    assert grid["summary"]["duplicate"] == 1


def test_field_present_on_one_node_only_is_not_a_conflict():
    # a field carried by only one of a ref's nodes (all present values agree) is not a conflict
    comps = [_c("U1", lib_id="A:x", value="v", MPN="M1"), _c("U1", lib_id="A:x", value="v")]
    grid = fields.build_field_grid(comps)
    row = grid["rows"][0]
    assert row["editable"] is True and row["fields"]["MPN"] == "M1" and row["conflicts"] == []


def test_field_blank_on_one_node_and_filled_on_another_is_not_a_conflict():
    # review #1: one unit of a multi-unit component carries MPN filled, the other carries MPN
    # present-but-BLANK (or KiCad's ~). A blank and an absent field are the same, so this is one
    # legitimate editable component, not a duplicate-designator anomaly; its real value shows.
    for blank in ("", "~", "-"):
        comps = [_c("U1", lib_id="A:x", value="v", MPN="M1"),
                 _c("U1", lib_id="A:x", value="v", MPN=blank)]
        grid = fields.build_field_grid(comps)
        row = grid["rows"][0]
        assert row["editable"] is True, f"blank={blank!r}"
        assert row["fields"]["MPN"] == "M1" and row["conflicts"] == []
        assert grid["summary"]["duplicate"] == 0


def test_grid_summary_counts():
    grid = fields.build_field_grid([_c("R1"), _c("C?", lib_id="Device:C"), _c("R2")])
    assert grid["summary"]["components"] == 3
    assert grid["summary"]["editable"] == 2
    assert grid["summary"]["unannotated"] == 1


def test_empty_project_grid_is_honest():
    grid = fields.build_field_grid([])
    assert grid["rows"] == [] and grid["columns"] == []
    assert grid["summary"]["components"] == 0


# -- field_changes_by_ref ------------------------------------------------------


def _rows():
    return fields.build_field_grid([
        _c("R1", value="10k", MPN=""),
        _c("C1", lib_id="Device:C", value="100nF"),
        _c("R?"),
    ])["rows"]


def test_changes_shapes_valid_edits():
    edits = [{"ref": "R1", "field": "MPN", "value": "RC0402"},
             {"ref": "R1", "field": "Value", "value": "22k"},
             {"ref": "C1", "field": "Footprint", "value": "C_0603"}]
    changes = fields.field_changes_by_ref(_rows(), edits)
    assert changes == {"R1": {"MPN": "RC0402", "Value": "22k"},
                       "C1": {"Footprint": "C_0603"}}


def test_editing_reference_is_refused():
    with pytest.raises(ValueError):
        fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "Reference", "value": "R9"}])


def test_blank_field_name_is_refused():
    with pytest.raises(ValueError):
        fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "   ", "value": "x"}])


def test_unknown_ref_is_refused():
    with pytest.raises(ValueError):
        fields.field_changes_by_ref(_rows(), [{"ref": "Z9", "field": "MPN", "value": "x"}])


def test_unannotated_ref_edit_is_refused():
    with pytest.raises(ValueError):
        fields.field_changes_by_ref(_rows(), [{"ref": "R?", "field": "Value", "value": "x"}])


def test_adding_a_new_field_column_is_allowed():
    changes = fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "Tolerance", "value": "1%"}])
    assert changes == {"R1": {"Tolerance": "1%"}}


def test_case_colliding_field_snaps_to_the_existing_column():
    # review #2: editing "mpn" when an "MPN" column exists must UPDATE MPN, never insert a second
    # duplicate "mpn" property. The change is keyed on the existing column's exact case.
    changes = fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "mpn", "value": "RC0402"}])
    assert changes == {"R1": {"MPN": "RC0402"}}


def test_case_variant_of_reference_is_still_refused():
    # canonicalization must not let "reference" slip past the read-only guard
    with pytest.raises(ValueError):
        fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "reference", "value": "R9"}])


def test_none_value_becomes_empty_string():
    changes = fields.field_changes_by_ref(_rows(), [{"ref": "R1", "field": "MPN", "value": None}])
    assert changes == {"R1": {"MPN": ""}}
