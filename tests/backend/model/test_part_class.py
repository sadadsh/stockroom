"""Four part classes, and requirements as `f(part_class, tool)` read off the EDA registry.

Spec section 6, decision D3. The binary `passive: bool` it replaces had no home for the M3
mounting holes or the button-integral ring LED already in the owner's register, both of which
were excluded BY HAND.

The point of the class table is that a requirement is DATA, never an `if tool == "altium"` or
an `if record.passive` branch buried in shared logic.
"""

import pytest

from stockroom.eda.registry import all_tools, get_tool
from stockroom.model.part_class import (
    CLASS_NEEDS,
    DEFAULT_PART_CLASS,
    PartClass,
    RequirementOverride,
    capturable_kinds,
    has_bom_line,
    needed_kinds,
    parse_part_class,
)


def test_there_are_exactly_four_classes():
    assert [c.value for c in PartClass] == ["passive", "component", "mechanical", "virtual"]
    assert DEFAULT_PART_CLASS is PartClass.COMPONENT


def test_every_class_declares_its_needs_as_data():
    assert set(CLASS_NEEDS) == set(PartClass), "a class with no declared needs is a silent gap"


def test_a_passive_needs_nothing_from_any_tool():
    # Owner, 2026-07-27: "passive components dont need files, models or symbols not for kicad
    # or for altium, theyre built in."
    for tool in all_tools():
        assert needed_kinds(PartClass.PASSIVE, tool.key) == ()
        assert capturable_kinds(PartClass.PASSIVE, tool.key) == ()
    assert has_bom_line(PartClass.PASSIVE) is True


def test_a_component_needs_symbol_footprint_and_a_model():
    assert needed_kinds(PartClass.COMPONENT, "kicad") == ("symbol", "footprint", "model")
    assert has_bom_line(PartClass.COMPONENT) is True


def test_a_mechanical_part_needs_a_footprint_and_no_symbol():
    assert needed_kinds(PartClass.MECHANICAL, "kicad") == ("footprint",)
    assert "symbol" not in needed_kinds(PartClass.MECHANICAL, "altium")
    assert has_bom_line(PartClass.MECHANICAL) is True


def test_a_virtual_part_needs_nothing_and_has_no_bom_line():
    for tool in all_tools():
        assert needed_kinds(PartClass.VIRTUAL, tool.key) == ()
    assert has_bom_line(PartClass.VIRTUAL) is False


# ------------------------------------------------- the registry, not a branch


def test_needs_are_intersected_with_what_the_TOOL_can_hold():
    # Altium's 3D body cannot be taken by reference, only embedded, so it is a CLOSABLE gap
    # (reported) but never a CAPTURABLE one (never asked of a capture session). Both answers
    # come off the registry, so a third tool is a registry entry and nothing else.
    assert "model" in needed_kinds(PartClass.COMPONENT, "altium")
    assert "model" not in capturable_kinds(PartClass.COMPONENT, "altium")
    assert "model" in capturable_kinds(PartClass.COMPONENT, "kicad")


def test_a_kind_no_registered_tool_declares_is_never_required():
    for tool in all_tools():
        assert set(needed_kinds(PartClass.COMPONENT, tool.key)) <= set(
            get_tool(tool.key).closable_assets()
        )


def test_an_unknown_tool_raises_rather_than_falling_back_to_kicad():
    with pytest.raises(Exception):
        needed_kinds(PartClass.COMPONENT, "eagle")


# ------------------------------------------------- the per-part escape hatch


def test_an_override_replaces_the_class_default():
    ov = RequirementOverride(needs=("footprint",), reason="ring LED integral to the button")
    assert needed_kinds(PartClass.COMPONENT, "kicad", ov) == ("footprint",)


def test_an_override_that_needs_NOTHING_is_different_from_no_override_at_all():
    # `requires_override: null` means "use the class default"; an override with an empty
    # needs list is the owner saying this ONE part needs nothing. Collapsing the two is how
    # an escape hatch silently stops working.
    assert needed_kinds(PartClass.COMPONENT, "kicad", None) != ()
    assert needed_kinds(PartClass.COMPONENT, "kicad", RequirementOverride(needs=())) == ()


def test_an_override_can_be_scoped_to_one_tool():
    ov = RequirementOverride(needs=(), tools=("altium",), reason="hand-built in Altium already")
    assert needed_kinds(PartClass.COMPONENT, "altium", ov) == ()
    assert needed_kinds(PartClass.COMPONENT, "kicad", ov) == ("symbol", "footprint", "model")


def test_an_override_round_trips():
    ov = RequirementOverride(needs=("footprint",), tools=("kicad",), reason="why")
    assert RequirementOverride.from_dict(ov.to_dict()) == ov


def test_an_override_preserves_a_key_from_a_newer_build():
    ov = RequirementOverride.from_dict(
        {"needs": ["footprint"], "reason": "r", "expires_at": "2027-01-01"}
    )
    assert ov.to_dict()["expires_at"] == "2027-01-01"


# ------------------------------------------------- parsing


def test_parse_accepts_the_four_names_and_is_idempotent():
    assert parse_part_class("passive") is PartClass.PASSIVE
    assert parse_part_class(PartClass.VIRTUAL) is PartClass.VIRTUAL


def test_an_unknown_class_is_LOUD_rather_than_guessed():
    # part_class decides which files a part needs. Guessing it would silently either demand
    # files a part cannot have or excuse a part that needs them.
    with pytest.raises(ValueError):
        parse_part_class("module")
    with pytest.raises(ValueError):
        parse_part_class("")
