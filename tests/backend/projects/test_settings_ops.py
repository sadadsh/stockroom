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


# --- M7f-A2: .kicad_pro severities + ERC pin-map + text-variables -------------


def test_severity_levels_are_kicads_three():
    assert settings_ops.SEVERITY_LEVELS == ("error", "warning", "ignore")


def test_erc_pin_types_are_twelve_in_kicad_order():
    assert settings_ops.ERC_PIN_MAP_SIZE == 12
    assert len(settings_ops.ERC_PIN_TYPES) == 12
    # KiCad's stored row/column order starts with input and ends with no_connect
    assert settings_ops.ERC_PIN_TYPES[0] == "input"
    assert settings_ops.ERC_PIN_TYPES[-1] == "no_connect"


def test_validate_severity_map_accepts_present_keys_and_known_levels():
    settings_ops.validate_severity_map(
        {"pin_not_connected": "error", "wire_dangling": "ignore"},
        allowed={"pin_not_connected", "wire_dangling"},
    )


def test_validate_severity_map_rejects_an_unknown_level():
    with pytest.raises(ValueError):
        settings_ops.validate_severity_map({"clearance": "fatal"}, allowed={"clearance"})


def test_validate_severity_map_rejects_a_rule_id_not_in_the_allowed_set():
    # a typo'd rule id must not inject a junk key into the file's severity map.
    with pytest.raises(ValueError):
        settings_ops.validate_severity_map({"clearnace": "error"}, allowed={"clearance"})


def test_validate_severity_map_accepts_an_empty_map():
    settings_ops.validate_severity_map({}, allowed=set())  # nothing to change is valid


def test_validate_pin_map_accepts_a_12x12_int_matrix():
    m = [[0] * 12 for _ in range(12)]
    m[1][1] = 2
    m[6][0] = 1
    settings_ops.validate_pin_map(m)


def test_validate_pin_map_rejects_wrong_dimensions():
    with pytest.raises(ValueError):
        settings_ops.validate_pin_map([[0] * 12 for _ in range(11)])  # 11 rows
    with pytest.raises(ValueError):
        settings_ops.validate_pin_map([[0] * 11 for _ in range(12)])  # 11 cols


def test_validate_pin_map_rejects_an_out_of_range_or_non_int_cell():
    m = [[0] * 12 for _ in range(12)]
    m[0][0] = 4  # KiCad severities are 0..3
    with pytest.raises(ValueError):
        settings_ops.validate_pin_map(m)
    m[0][0] = "x"
    with pytest.raises(ValueError):
        settings_ops.validate_pin_map(m)


def test_validate_pin_map_rejects_a_bool_cell():
    # a JSON bool is an int in Python; a pin-map cell is a severity index, never a boolean.
    m = [[0] * 12 for _ in range(12)]
    m[0][0] = True
    with pytest.raises(ValueError):
        settings_ops.validate_pin_map(m)


def test_reconcile_text_variables_coerces_values_to_str():
    out = settings_ops.reconcile_text_variables({"VER": 3, "NAME": "board"})
    assert out == {"VER": "3", "NAME": "board"}


def test_reconcile_text_variables_rejects_a_blank_key():
    with pytest.raises(ValueError):
        settings_ops.reconcile_text_variables({"  ": "x"})


def test_reconcile_text_variables_empty_is_a_valid_clear():
    # deleting every var yields an empty desired map; that is a valid "clear all", not an error.
    assert settings_ops.reconcile_text_variables({}) == {}
