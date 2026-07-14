"""settings_ops: the board-setup form schema + editor-input validation (M7f-A).

Pure compute. The board-setup field catalog is the single description the editor
renders from; validation guards the input before it reaches the byte-preserving
Board writer, so an unsupported key or a malformed value is an honest error rather
than a silent no-op or a raw float() crash.
"""

import pytest

from stockroom.projects import settings_ops


def test_board_setup_fields_cover_every_editable_key():
    keys = {f["key"] for f in settings_ops.BOARD_SETUP_FIELDS}
    # the real (setup) keys plus the per-side via-protection booleans the read shape uses
    assert "pad_to_mask_clearance" in keys
    assert "tenting_front" in keys and "tenting_back" in keys
    assert "aux_axis_origin" in keys and "grid_origin" in keys
    assert "capping" in keys and "filling" in keys


def test_every_field_declares_a_known_kind_and_a_title_case_label():
    for f in settings_ops.BOARD_SETUP_FIELDS:
        assert f["kind"] in {"length", "ratio", "bool", "coord"}
        # Title Case interactive label (design contract): first char upper, no lone lower word.
        assert f["label"][:1].isupper()


def test_validate_accepts_a_well_formed_setup():
    settings_ops.validate_board_setup(
        {"pad_to_mask_clearance": 0.05, "tenting_front": True, "aux_axis_origin": [10, 20]}
    )


def test_validate_rejects_an_unsupported_key():
    with pytest.raises(ValueError):
        settings_ops.validate_board_setup({"not_a_real_key": 1})


def test_validate_rejects_a_non_numeric_length():
    with pytest.raises(ValueError):
        settings_ops.validate_board_setup({"pad_to_mask_clearance": "wide"})


def test_validate_rejects_a_malformed_coordinate():
    with pytest.raises(ValueError):
        settings_ops.validate_board_setup({"grid_origin": [10]})  # needs 2 numbers


def test_validate_rejects_a_non_numeric_coordinate():
    with pytest.raises(ValueError):
        settings_ops.validate_board_setup({"grid_origin": [10, "y"]})


def test_validate_thickness_rejects_non_positive():
    settings_ops.validate_thickness(1.6)  # ok
    with pytest.raises(ValueError):
        settings_ops.validate_thickness(0)
    with pytest.raises(ValueError):
        settings_ops.validate_thickness(-1)
    with pytest.raises(ValueError):
        settings_ops.validate_thickness("thick")


def test_validate_thickness_rejects_non_finite():
    # Infinity passes a bare `<= 0` guard but crashes _fmt_num's int(f) with OverflowError
    # (a 500, not a clean 400); NaN is non-comparable. Both must be a clean ValueError.
    with pytest.raises(ValueError):
        settings_ops.validate_thickness(float("inf"))
    with pytest.raises(ValueError):
        settings_ops.validate_thickness(float("nan"))


def test_effective_board_setup_fills_absent_bool_defaults():
    # an absent via-protection block is NOT off: tenting defaults ON in KiCad, so the editor
    # must show it ON, never as a silent OFF that a save would then write and flip.
    eff = settings_ops.effective_board_setup({"pad_to_mask_clearance": 0.05})
    assert eff["pad_to_mask_clearance"] == 0.05  # present key preserved
    assert eff["tenting_front"] is True and eff["tenting_back"] is True  # KiCad default ON
    assert eff["covering_front"] is False and eff["plugging_back"] is False  # default OFF
    assert eff["capping"] is False and eff["filling"] is False
    assert eff["allow_soldermask_bridges_in_footprints"] is False


def test_effective_board_setup_keeps_present_values_over_defaults():
    eff = settings_ops.effective_board_setup({"tenting_front": False})
    assert eff["tenting_front"] is False  # a present OFF is not overwritten by the ON default
    assert eff["tenting_back"] is True  # the absent side still shows its default


def test_effective_board_setup_leaves_absent_numeric_and_coord_blank():
    eff = settings_ops.effective_board_setup({})
    assert "pad_to_mask_clearance" not in eff  # numeric stays absent (form shows blank)
    assert "grid_origin" not in eff  # coord stays absent
