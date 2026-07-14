"""conform_ops: the object-conform category catalog + editor-input validation (M7f-B).

Pure compute. The catalog is what the editor renders (Title Case labels + suggested starting
sizes); validation guards the target input before it reaches the byte-preserving conform writer,
so an unknown category or a non-positive size/thickness is an honest 400, not a silent no-op."""

import pytest

from stockroom.kicad import conform
from stockroom.projects import conform_ops


def test_catalog_keys_match_the_writer_categories():
    pcb = {c["key"] for c in conform_ops.PCB_CONFORM_CATEGORIES}
    sch = {c["key"] for c in conform_ops.SCH_CONFORM_CATEGORIES}
    # a drift guard: every catalog category must be one the writer knows, and vice versa
    assert pcb == set(conform.PCB_CATEGORIES)
    assert sch == set(conform.SCH_CATEGORIES)


def test_every_category_has_a_title_case_label_and_a_suggested_size():
    for c in conform_ops.PCB_CONFORM_CATEGORIES + conform_ops.SCH_CONFORM_CATEGORIES:
        assert c["label"][:1].isupper()
        s = conform_ops.SUGGESTED[c["key"]]
        assert isinstance(s["size"], (int, float)) and s["size"] > 0


def test_validate_accepts_a_well_formed_target():
    conform_ops.validate_targets(
        {"silk": {"size": 1.0, "thickness": 0.15}},
        {"labels": {"size": 1.27, "thickness": None}},
    )


def test_validate_rejects_an_unknown_category():
    with pytest.raises(ValueError):
        conform_ops.validate_targets({"bogus": {"size": 1.0}}, {})
    with pytest.raises(ValueError):
        conform_ops.validate_targets({}, {"nope": {"size": 1.0}})


def test_validate_rejects_a_category_with_neither_size_nor_thickness():
    with pytest.raises(ValueError):
        conform_ops.validate_targets({"silk": {"size": None, "thickness": None}}, {})


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "x", True])
def test_validate_rejects_a_non_positive_or_non_finite_size(bad):
    with pytest.raises(ValueError):
        conform_ops.validate_targets({"silk": {"size": bad}}, {})


@pytest.mark.parametrize("bad", [0, -0.1, float("inf")])
def test_validate_rejects_a_bad_thickness(bad):
    with pytest.raises(ValueError):
        conform_ops.validate_targets({"silk": {"size": 1.0, "thickness": bad}}, {})


def test_validate_rejects_a_non_dict_spec():
    with pytest.raises(ValueError):
        conform_ops.validate_targets({"silk": 1.0}, {})


def test_any_targets_reports_whether_anything_is_selected():
    assert conform_ops.any_targets({"silk": {"size": 1.0}}, {}) is True
    assert conform_ops.any_targets({}, {"text": {"size": 1.0}}) is True
    assert conform_ops.any_targets({}, {}) is False
    assert conform_ops.any_targets(None, None) is False
