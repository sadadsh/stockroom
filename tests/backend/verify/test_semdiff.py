import pytest

from stockroom.verify.semdiff import (
    SemDiffError,
    assert_only_changed,
    semantic_diff,
)


def test_identical_is_empty():
    assert semantic_diff("(a 1)", "(a 1)") == []


def test_formatting_only_is_empty():
    assert semantic_diff("(a\n\t1)", "(a 1)") == []


def test_number_repr_noise_ignored():
    assert semantic_diff("(at 1.0)", "(at 1)") == []


def test_changed_atom_detected():
    diffs = semantic_diff('(p "V" "10k")', '(p "V" "22k")')
    assert any("CHANGED" in d for d in diffs)


def test_lost_node_detected():
    diffs = semantic_diff("(x (a 1) (b 2))", "(x (a 1))")
    assert any("LOST" in d for d in diffs)


def test_assert_only_changed_allows_intended_edit():
    assert_only_changed('(p "V" "10k")', '(p "V" "22k")', allowed_changes=1)


def test_assert_only_changed_rejects_lost_node():
    with pytest.raises(SemDiffError):
        assert_only_changed("(x (a 1) (b 2))", "(x (a 1))", allowed_changes=1)


def test_assert_only_changed_rejects_extra_change():
    with pytest.raises(SemDiffError):
        assert_only_changed('(p "10k" "1")', '(p "22k" "2")', allowed_changes=1)
