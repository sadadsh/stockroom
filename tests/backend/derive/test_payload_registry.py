"""The payload-parser registry, and the two invariants that keep it from becoming a branch.

The derive path deliberately does NOT use `enrich.registry`'s Source objects: those need API keys
(`MouserAdapter.enabled` is False without one), and a re-derive has to work on a fresh clone with
no credentials or a machine cannot rebuild the library it just pulled. So there is a second,
credential-free registry - and a second registry means drift, which is what this file measures.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from stockroom.derive import engine as engine_mod
from stockroom.derive import naming as naming_mod
from stockroom.derive import payloads as payloads_mod
from stockroom.derive.engine import assert_no_writer_imported
from stockroom.derive.payloads import (
    FIELD_SOURCE_PRIORITY,
    PAYLOAD_PARSERS,
    known_sources,
    parse_one,
    parser_for,
    sources_for_field,
)


def test_the_registry_is_not_empty_and_is_ordered():
    """ORDER IS THE CONTRACT: `merge_missing` gives a field to whoever fills it first, so an
    unordered registry would pick winners nondeterministically and 'derive twice, byte-identical'
    would fail intermittently - the worst way for it to fail."""
    assert known_sources(), "no payload parsers registered: every re-derive would produce nothing"
    assert isinstance(PAYLOAD_PARSERS, tuple), "a tuple, so priority order cannot be reshuffled"
    assert len(set(known_sources())) == len(known_sources()), "a source is registered twice"


def test_every_field_priority_is_complete_deterministic_and_names_registered_sources():
    known = set(known_sources())
    for field, preferred in FIELD_SOURCE_PRIORITY.items():
        assert field
        assert preferred
        assert len(preferred) == len(set(preferred))
        assert set(preferred) <= known
        ordered = sources_for_field(field)
        assert set(ordered) == known
        assert len(ordered) == len(known)


def test_every_parser_runs_with_NO_credentials_and_NO_network():
    """The whole reason this registry exists. A parser that needed a key or a socket would make a
    re-derive impossible on a fresh clone, which breaks device parity: same files, same info."""
    for source in known_sources():
        parser = parser_for(source)
        assert parser is not None
        # An empty body is the hardest credential-free case: it must return an empty result rather
        # than reach for a client, a token or a cache.
        result = parser({}, "SOME-MPN")
        assert not result.filled_fields(), f"{source} invented data from an empty payload"


def test_an_unknown_source_is_skipped_rather_than_raising():
    """Forward compatibility: a newer build may store a source this one cannot read. Refusing would
    make an older peer unable to rebuild a library it just pulled."""
    assert parser_for("farnell") is None
    assert not parse_one("farnell", {"anything": 1}, "MPN").filled_fields()


def test_a_malformed_payload_yields_an_empty_result_not_an_exception():
    """One corrupt file must not make a part unrebuildable. The payload stays on disk either way."""
    for source in known_sources():
        for junk in (None, {}, {"SearchResults": "not-a-dict"}, {"Products": 5}):
            assert not parse_one(source, junk, "MPN").filled_fields()


def test_the_derive_path_cannot_write_evidence():
    """LOSSLESSNESS as a property of the code. See the docstring on `assert_no_writer_imported`
    for why this is an AST walk and not a substring search."""
    assert_no_writer_imported()


def test_the_writer_check_can_actually_FAIL(tmp_path):
    """A gate that cannot fail is worse than no gate, because it reports safety.

    FIXED 2026-07-27 (cold-eyes finding 2). The version this replaces built its own tiny AST from
    a bare string and asserted `ast.walk` finds a call in it - which measures the `ast` module,
    not `assert_no_writer_imported`. MEASURED to be vacuous: an early `return` inserted at the top
    of `assert_no_writer_imported`, disabling BOTH of its checks, left the entire
    `tests/backend/derive` suite green - 25 passed - including this very test.

    `engine._scan_modules_for_writes` was split out specifically so this test can drive the REAL
    scanning logic against a genuinely offending module, rather than restating the rule in
    miniature beside it.
    """
    import types

    from stockroom.derive.engine import _scan_modules_for_writes

    offending_path = tmp_path / "offending_module.py"
    offending_path.write_text(
        "def go(root):\n    write_payload(root, 'x', 'mouser', '{}')\n", encoding="utf-8"
    )
    fake_module = types.ModuleType("offending_module")
    fake_module.__file__ = str(offending_path)

    with pytest.raises(AssertionError, match="write_payload"):
        _scan_modules_for_writes((fake_module,), object())

    # NEGATIVE CONTROL: a module with no such call must pass cleanly, so the test above is
    # detecting the offending CALL and not merely "any module raises".
    clean_path = tmp_path / "clean_module.py"
    clean_path.write_text("def go(root):\n    return root.read_text()\n", encoding="utf-8")
    clean_module = types.ModuleType("clean_module")
    clean_module.__file__ = str(clean_path)
    _scan_modules_for_writes((clean_module,), object())  # must not raise


def test_no_derive_module_branches_on_a_SOURCE_NAME():
    """The tool-agnostic rule, applied to sources instead of EDA tools.

    A per-source difference belongs in the registry table, never in an `if source == "mouser"`
    buried in shared logic - that exact shape is what produced the permanent "CAD Incomplete" bug
    on the EDA side. Measured by AST so a comparison inside a string or a docstring cannot convict.
    """
    known = set(known_sources())
    offenders: list[str] = []
    for module in (engine_mod, naming_mod, payloads_mod):
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            literals = [
                c.value for c in [node.left, *node.comparators]
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            ]
            for lit in literals:
                if lit in known:
                    offenders.append(f"{module.__name__}:{node.lineno} compares against {lit!r}")
    assert not offenders, (
        "a source name is hardcoded in a comparison inside the derive path:\n  "
        + "\n  ".join(offenders)
        + "\nPer-source behaviour is DATA in PAYLOAD_PARSERS, never a branch."
    )


@pytest.mark.parametrize("source", list(known_sources()))
def test_the_registry_only_names_sources_that_really_parse(source):
    """Guards the other direction of drift: an entry whose function was renamed or removed."""
    parser = parser_for(source)
    assert callable(parser)
