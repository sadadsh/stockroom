"""Spec-value/key hygiene: the F2 data-cleanliness normalizer.

Fixtures are the REAL malformed strings enumerated across the 88 library records
(space-before-percent x52, 'PPM / C' spacing x34, the duplicated-label key on all
88), plus the legitimate ' / ' values and the non-string tariff that must be left
exactly alone. Normalization is canonical and idempotent."""

from stockroom.model.spec_hygiene import (
    normalize_spec_key,
    normalize_spec_value,
    normalize_specs,
)


class TestValue:
    def test_space_before_percent(self):
        for raw, want in [
            ("1 %", "1%"),
            ("0.1 %", "0.1%"),
            ("5 %", "5%"),
            ("10 %", "10%"),
            ("20 %", "20%"),
            ("25 %", "25%"),
        ]:
            assert normalize_spec_value(raw) == want

    def test_ppm_per_celsius_spacing(self):
        # Spacing only: bare "C" and the PPM casing are preserved (the library uses
        # bare C everywhere; a "°" is never invented).
        for raw, want in [
            ("100 PPM / C", "100 PPM/C"),
            ("200 PPM / C", "200 PPM/C"),
            ("25 PPM / C", "25 PPM/C"),
        ]:
            assert normalize_spec_value(raw) == want

    def test_ppm_case_and_existing_degree_preserved(self):
        assert normalize_spec_value("100 ppm/C") == "100 ppm/C"  # already tight, untouched
        assert normalize_spec_value("100 PPM / °C") == "100 PPM/°C"  # keep a present degree

    def test_bare_ppm_untouched(self):
        assert normalize_spec_value("50 PPM") == "50 PPM"

    def test_legit_slash_values_untouched(self):
        # Real category / manufacturer values: a general ' / '->'/'  tighten would
        # corrupt these, so the slash rule is scoped to the PPM temp-coeff unit only.
        for v in [
            "ESD Protection Diodes / TVS Diodes",
            "Decoders / Demultiplexers",
            "Analog Devices / Maxim Integrated",
            "TE Connectivity / Holsworthy",
        ]:
            assert normalize_spec_value(v) == v

    def test_non_string_passthrough(self):
        assert normalize_spec_value(37.0) == 37.0
        assert normalize_spec_value(0.0) == 0.0
        assert normalize_spec_value(100) == 100
        pinout = [{"pin": "1", "name": "VCC"}]
        assert normalize_spec_value(pinout) is pinout  # identity, never mutated

    def test_whitespace_trim_and_collapse(self):
        assert normalize_spec_value("  1000  mW ") == "1000 mW"

    def test_idempotent(self):
        for raw in ["1 %", "100 PPM / C", "0.1 %", "50 PPM", "100 ppm/C", "Decoders / Demultiplexers"]:
            once = normalize_spec_value(raw)
            assert normalize_spec_value(once) == once


class TestKey:
    def test_duplicated_label_collapsed(self):
        assert (
            normalize_spec_key("Factory Pack Quantity: Factory Pack Quantity")
            == "Factory Pack Quantity"
        )

    def test_normal_keys_untouched(self):
        for k in ["Tolerance", "Product Category", "Case Code - in", "RoHS"]:
            assert normalize_spec_key(k) == k

    def test_distinct_colon_key_untouched(self):
        # Two DIFFERENT sides of a colon are a real key, never a duplicate to collapse.
        assert normalize_spec_key("Ratio: Max") == "Ratio: Max"

    def test_idempotent(self):
        once = normalize_spec_key("Factory Pack Quantity: Factory Pack Quantity")
        assert normalize_spec_key(once) == once


class TestSpecs:
    def test_full_record_specs(self):
        raw = {
            "Tolerance": "1 %",
            "Temperature Coefficient": "100 PPM / C",
            "Factory Pack Quantity: Factory Pack Quantity": "100",
            "Product": "ESD Protection Diodes / TVS Diodes",
            "US Tariff %": 37.0,
        }
        assert normalize_specs(raw) == {
            "Tolerance": "1%",
            "Temperature Coefficient": "100 PPM/C",
            "Factory Pack Quantity": "100",
            "Product": "ESD Protection Diodes / TVS Diodes",
            "US Tariff %": 37.0,
        }

    def test_key_collision_no_data_loss(self):
        # The duplicated-label key and its clean twin collapse to one, value kept.
        raw = {
            "Factory Pack Quantity: Factory Pack Quantity": "100",
            "Factory Pack Quantity": "100",
        }
        assert normalize_specs(raw) == {"Factory Pack Quantity": "100"}

    def test_collision_distinct_values_canonical_wins_both_orders(self):
        # Two raw keys that canonicalize to the SAME key with DIFFERENT non-blank values
        # (the malformed-label twin + its already-clean key): the value from the clean,
        # already-canonical key wins, and the result is the SAME regardless of insertion
        # order. Deterministic, not order-dependent (F2 adversarial-review finding).
        twin = "Factory Pack Quantity: Factory Pack Quantity"
        clean = "Factory Pack Quantity"
        assert normalize_specs({twin: "5000", clean: "100"}) == {clean: "100"}
        assert normalize_specs({clean: "100", twin: "5000"}) == {clean: "100"}

    def test_collision_two_non_canonical_keeps_first_deterministically(self):
        # When neither colliding key is already canonical, the first-seen non-blank value
        # wins - deterministic for a given input (no order-dependent surprise mid-dict).
        twin = "Factory Pack Quantity: Factory Pack Quantity"
        other = " Factory Pack Quantity :  Factory Pack Quantity "
        assert normalize_specs({twin: "5000", other: "9999"}) == {"Factory Pack Quantity": "5000"}

    def test_preserves_insertion_order(self):
        raw = {"b": "1 %", "a": "2 %"}
        assert list(normalize_specs(raw).keys()) == ["b", "a"]

    def test_empty(self):
        assert normalize_specs({}) == {}

    def test_returns_new_dict(self):
        raw = {"Tolerance": "1 %"}
        out = normalize_specs(raw)
        assert out is not raw
        assert raw == {"Tolerance": "1 %"}  # input untouched
