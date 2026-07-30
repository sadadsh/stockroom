from __future__ import annotations

from scripts.catalog_search_benchmark import (
    RECEIPT_SCHEMA,
    _percentile_95,
    run_benchmark,
)


def test_percentile_is_defined_for_one_sample() -> None:
    assert _percentile_95([12.5]) == 12.5


def test_small_catalog_benchmark_exercises_every_query_family() -> None:
    receipt = run_benchmark(rows=2_000, samples=2, budget_ms=60_000)

    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["catalog_rows"] == 2_000
    assert receipt["budget_met"] is True
    assert [
        (family["name"], family["expected_matches"], family["samples"])
        for family in receipt["query_families"]
    ] == [
        ("unique-mpn", 1, 2),
        ("token", 2, 2),
        ("manufacturer", 20, 2),
    ]
    assert all(family["budget_met"] for family in receipt["query_families"])
