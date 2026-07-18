"""The server-side spec filter behind the modular Mouser-style search. The facets endpoint
tells the UI which dimensions exist (options / ranges); THIS is how a selection narrows the
parts list. It must agree with the facet it came from: option values compare as text (the
options facet), a range compares SI-normalized magnitudes (the range facet, via the same
_parse_numeric), so a filter never disagrees with the checkbox that produced it."""

from __future__ import annotations

from types import SimpleNamespace

from stockroom.store.parametric import (
    SpecConstraint,
    matches_spec_filters,
    parse_spec_filters,
)


def _rec(**specs):
    return SimpleNamespace(specs=dict(specs))


# --- parse_spec_filters ------------------------------------------------------


def test_parse_options_token():
    [c] = parse_spec_filters(["Dielectric:X7R"])
    assert c == SpecConstraint(key="Dielectric", values=["X7R"])


def test_parse_repeated_option_key_ors_its_values():
    [c] = parse_spec_filters(["Dielectric:X7R", "Dielectric:C0G"])
    assert c.key == "Dielectric"
    assert c.values == ["X7R", "C0G"]
    assert c.min is None and c.max is None


def test_parse_range_token_sets_both_bounds():
    [c] = parse_spec_filters(["Resistance:1000~10000"])
    assert c.key == "Resistance"
    assert c.min == 1000.0
    assert c.max == 10000.0
    assert c.values == []


def test_parse_open_ended_ranges():
    [lo] = parse_spec_filters(["Resistance:1000~"])
    assert lo.min == 1000.0 and lo.max is None
    [hi] = parse_spec_filters(["Resistance:~5000"])
    assert hi.min is None and hi.max == 5000.0


def test_parse_distinct_keys_stay_separate():
    cs = {c.key: c for c in parse_spec_filters(["Resistance:1000~10000", "Tolerance:1~5"])}
    assert set(cs) == {"Resistance", "Tolerance"}


def test_parse_skips_malformed_tokens_never_raises():
    # no colon, empty key, empty value, a non-string - all dropped, nothing raised
    assert parse_spec_filters(["nocolon", ":novalue", "nokey:", "  :  ", 42]) == []


# --- matches_spec_filters ----------------------------------------------------


def test_no_constraints_matches_every_record():
    assert matches_spec_filters(_rec(Anything="x"), []) is True


def test_options_matches_only_the_selected_value():
    cs = parse_spec_filters(["Dielectric:X7R"])
    assert matches_spec_filters(_rec(Dielectric="X7R"), cs) is True
    assert matches_spec_filters(_rec(Dielectric="C0G"), cs) is False


def test_options_or_within_a_key():
    cs = parse_spec_filters(["Dielectric:X7R", "Dielectric:C0G"])
    assert matches_spec_filters(_rec(Dielectric="C0G"), cs) is True
    assert matches_spec_filters(_rec(Dielectric="X5R"), cs) is False


def test_range_compares_si_normalized_magnitude():
    cs = parse_spec_filters(["Resistance:5000~20000"])
    assert matches_spec_filters(_rec(Resistance="10 kΩ"), cs) is True   # 10000 in band
    assert matches_spec_filters(_rec(Resistance="1 kΩ"), cs) is False   # 1000 below
    assert matches_spec_filters(_rec(Resistance="47 kΩ"), cs) is False  # 47000 above


def test_open_ended_range_bounds_one_side():
    below = parse_spec_filters(["Resistance:~5000"])
    assert matches_spec_filters(_rec(Resistance="1 kΩ"), below) is True
    assert matches_spec_filters(_rec(Resistance="10 kΩ"), below) is False


def test_a_record_missing_the_constrained_key_is_excluded():
    cs = parse_spec_filters(["Dielectric:X7R"])
    assert matches_spec_filters(_rec(Resistance="10 kΩ"), cs) is False


def test_a_range_on_a_non_numeric_value_excludes_the_record():
    cs = parse_spec_filters(["Dielectric:1~5"])
    assert matches_spec_filters(_rec(Dielectric="X7R"), cs) is False


def test_multiple_keys_and_together():
    cs = parse_spec_filters(["Resistance:5000~20000", "Tolerance:0~2"])
    assert matches_spec_filters(_rec(Resistance="10 kΩ", Tolerance="1%"), cs) is True
    assert matches_spec_filters(_rec(Resistance="10 kΩ", Tolerance="5%"), cs) is False
