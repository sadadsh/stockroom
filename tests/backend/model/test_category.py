import pytest

from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
    is_valid_category,
    slugify,
)


def test_taxonomy_is_the_fixed_thirteen():
    assert CATEGORIES == (
        "Resistors",
        "Capacitors",
        "Inductors",
        "Diodes",
        "Transistors",
        "ICs",
        "Connectors",
        "Switches",
        "Crystals & Oscillators",
        "Sensors",
        "Modules",
        "Electromechanical",
        "Other",
    )


def test_is_valid_category():
    assert is_valid_category("ICs")
    assert not is_valid_category("Widgets")


def test_nickname_and_lib_names():
    assert category_nickname("ICs") == "SR-ICs"
    assert category_symbol_lib("ICs") == "SR-ICs.kicad_sym"
    assert category_footprint_lib("ICs") == "SR-ICs.pretty"


def test_nickname_slugifies_spaces_and_punctuation():
    # "Crystals & Oscillators" must become a filesystem/nickname-safe token.
    assert category_nickname("Crystals & Oscillators") == "SR-Crystals_Oscillators"
    assert category_symbol_lib("Crystals & Oscillators") == "SR-Crystals_Oscillators.kicad_sym"


def test_lib_helpers_reject_unknown_category():
    with pytest.raises(ValueError):
        category_nickname("Widgets")


def test_slugify():
    assert slugify("TPS62130RGTR") == "tps62130rgtr"
    assert slugify("Crystals & Oscillators") == "crystals_oscillators"
    assert slugify("  Multiple   spaces ") == "multiple_spaces"
    assert slugify("weird/\\:*?chars") == "weird_chars"
