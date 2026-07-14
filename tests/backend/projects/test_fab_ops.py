"""M7f-C fab-preset catalog + stackup validators (pure, Qt-free): the physical-stackup presets the
editor offers, and the guards that reject bad input BEFORE it reaches the byte-preserving writer."""

import math

import pytest

from stockroom.kicad import stackup
from stockroom.projects import fab_ops


def test_presets_registry_has_the_two_oshpark_presets():
    assert set(fab_ops.FAB_PRESETS) == {"oshpark_2", "oshpark_4"}


def test_preset_copper_count_matches_declared_layers():
    for key, p in fab_ops.FAB_PRESETS.items():
        copper = [e for e in p["physical"] if e["kind"] == "copper"]
        assert len(copper) == p["layers"], key


def test_two_layer_stack_shape():
    p = fab_ops.FAB_PRESETS["oshpark_2"]
    assert p["layers"] == 2
    kinds = [e["kind"] for e in p["physical"]]
    assert kinds == ["copper", "dielectric", "copper"]
    assert p["board_thickness_mm"] == 1.6
    assert p["finish"] == "ENIG"
    assert p["soldermask_color"] == "Purple"


def test_four_layer_stack_shape():
    p = fab_ops.FAB_PRESETS["oshpark_4"]
    assert p["layers"] == 4
    copper = [e for e in p["physical"] if e["kind"] == "copper"]
    diel = [e for e in p["physical"] if e["kind"] == "dielectric"]
    assert len(copper) == 4 and len(diel) == 3
    # inner copper is thinner than outer (0.5 oz vs 1 oz)
    assert copper[1]["thickness"] < copper[0]["thickness"]
    assert "FR408HR" in diel[0]["material"]
    assert p["verify_note"]  # the honesty caveat is present and non-empty


def test_catalog_is_title_case_and_api_shaped():
    cat = fab_ops.preset_catalog()
    labels = {c["label"] for c in cat}
    assert "OSH Park 2-Layer" in labels and "OSH Park 4-Layer" in labels
    entry = next(c for c in cat if c["key"] == "oshpark_4")
    for k in ("key", "label", "layers", "board_thickness_mm", "finish", "soldermask_color",
              "verify_note"):
        assert k in entry


def test_get_preset():
    assert fab_ops.get_preset("oshpark_2")["layers"] == 2
    assert fab_ops.get_preset("nope") is None


# --- validate_preset_apply ----------------------------------------------------

def test_validate_preset_apply_unknown_key():
    with pytest.raises(ValueError):
        fab_ops.validate_preset_apply("nope", 2)


def test_validate_preset_apply_layer_mismatch():
    with pytest.raises(ValueError):
        fab_ops.validate_preset_apply("oshpark_2", 4)  # 2-layer preset onto a 4-copper board
    with pytest.raises(ValueError):
        fab_ops.validate_preset_apply("oshpark_4", 2)


def test_validate_preset_apply_match_returns_preset():
    p = fab_ops.validate_preset_apply("oshpark_4", 4)
    assert p["key"] == "oshpark_4"


# --- validate_field_edits -----------------------------------------------------

def test_validate_field_edits_rejects_nonpositive_and_nonfinite():
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"dielectric 1": {"thickness": 0}})
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"dielectric 1": {"thickness": -1}})
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"dielectric 1": {"epsilon_r": math.inf}})
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"dielectric 1": {"loss_tangent": float("nan")}})


def test_validate_field_edits_rejects_blank_strings():
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(copper_finish="   ")
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"dielectric 1": {"material": ""}})


def test_validate_field_edits_rejects_bool_numeric():
    # a JSON bool coerces to int in Python; a thickness is never a boolean
    with pytest.raises(ValueError):
        fab_ops.validate_field_edits(layer_edits={"F.Cu": {"thickness": True}})


def test_validate_field_edits_accepts_valid():
    fab_ops.validate_field_edits(
        copper_finish="ENIG", dielectric_constraints=True,
        layer_edits={"dielectric 2": {"thickness": 1.2, "material": "Rogers", "epsilon_r": 3.66,
                                      "loss_tangent": 0.0037}})


# --- integration: a preset renders a well-formed native block -----------------

def test_preset_builds_a_wellformed_native_stackup():
    p = fab_ops.FAB_PRESETS["oshpark_4"]
    layers = stackup.build_preset_layers(
        ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], p["physical"],
        mask_color=p["soldermask_color"])
    block = stackup.render_stackup_block(
        layers, copper_finish=p["finish"], dielectric_constraints=False)
    assert block.count('(type "copper")') == 4
    assert '(copper_finish "ENIG")' in block
    assert '(color "Purple")' in block  # a coloured mask
    assert block.count("(") == block.count(")")
