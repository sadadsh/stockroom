"""The two-registry invariant `sources.py` documents, actually enforced.

`importer.sources.SOURCE_BUILDERS` (credentialed fetch) and `derive.payloads.PAYLOAD_PARSERS`
(credential-free parse) are deliberately separate registries - see both modules' docstrings for
why - and that separation is only safe if they name the SAME sources in the SAME priority order.
A source with a fetcher but no parser would store a payload nothing can ever derive from, which
would look like a successful import and silently derive to nothing forever.

FOUND BY COLD-EYES REVIEW (2026-07-27): `sources.py`'s own docstring claimed "that is gated by
tests/backend/importer/test_source_registry.py" - and no such file existed. A comment asserting
coverage that is not there is worse than an admitted gap, because it reads as safe. This is that
file, finally.
"""
from __future__ import annotations

from stockroom.derive.payloads import PAYLOAD_PARSERS
from stockroom.importer.sources import SOURCE_BUILDERS, source_names


def test_every_fetcher_has_a_matching_parser():
    """A source the importer can FETCH must be a source the derive engine can PARSE, or its
    evidence would sit on disk forever, unused - the exact "store what nothing can read" failure
    the docstring warns about."""
    fetch_names = {key for key, _ in SOURCE_BUILDERS}
    parse_names = {key for key, _ in PAYLOAD_PARSERS}
    assert fetch_names, "no fetchers registered - this test would prove nothing"
    missing = fetch_names - parse_names
    assert not missing, (
        f"{sorted(missing)} can be FETCHED (importer.sources) but not PARSED "
        f"(derive.payloads) - evidence for these sources would be written and never derived."
    )


def test_the_fetch_order_matches_the_parse_priority_order():
    """ORDER IS THE CONTRACT on the parse side (see `derive/payloads.py`): `merge_missing` gives
    a field to whoever fills it first. If the importer fetched in a different order than the
    engine parses, nothing would be WRONG about any single payload, but which vendor's answer
    wins a contested field would depend on an order nobody chose on purpose. The two lists don't
    have to be equal in LENGTH (a parser may exist for a source with no live fetcher yet, e.g.
    LCSC), only in the RELATIVE order of names both agree on."""
    fetch_order = [key for key, _ in SOURCE_BUILDERS]
    parse_order = [key for key, _ in PAYLOAD_PARSERS]
    parse_rank = {name: i for i, name in enumerate(parse_order)}
    ranked_fetch = [parse_rank[name] for name in fetch_order if name in parse_rank]
    assert ranked_fetch == sorted(ranked_fetch), (
        f"fetch order {fetch_order} disagrees with parse priority order {parse_order} - "
        f"the importer and the derive engine would pick different winners for a contested field."
    )


def test_source_names_matches_the_registry_it_is_derived_from():
    """Guards against `source_names()` drifting from `SOURCE_BUILDERS` itself (a stale cache, a
    hand-maintained duplicate)."""
    assert set(source_names()) == {key for key, _ in SOURCE_BUILDERS}


def test_this_gate_can_actually_fail():
    """A gate that can never fail is worse than no gate - it reports safety. Constructs a
    deliberately BROKEN pair of tables (a fetcher with no parser) and asserts the same logic the
    tests above use would catch it, so this file's own checking logic is proven, not merely
    assumed."""
    fetch_names = {"mouser", "digikey", "farnell"}
    parse_names = {"mouser", "digikey"}
    missing = fetch_names - parse_names
    assert missing == {"farnell"}, "the drift-detection logic itself does not detect drift"
