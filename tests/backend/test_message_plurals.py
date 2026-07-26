"""No message the backend writes for a person may fake a plural with `(s)`.

The owner registered this complaint once already, about the status bar reading "1 Components"
(fixed frontend-side in `623c6d2`). It was still true in five backend messages, so this is the
gate rather than a fifth one-line fix: a rule stated in prose and enforced by nothing is how the
same complaint comes back.

FACT, not judgement: this walks the AST and looks at STRING LITERALS only, so a `(s)` in a
comment or a docstring - which no user ever sees - cannot trip it. That distinction is the whole
reason it is an AST gate and not a grep; a grep over this same tree convicts
`# vcap = family needs external cap(s)` and a docstring about "its on-disk file(s)".
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from stockroom.projects.fab_ops import validate_preset_apply
from stockroom.text import counted

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend" / "stockroom"


def _message_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string constant that is NOT a docstring, with its line number."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append((node.lineno, node.value))
    return out


# Two modules embed JavaScript payloads as Python strings (the vendor-site drivers and the live
# capture probe). Those are CODE, and `function q(s){...}` is a parameter list, not a faked plural.
# Detected by a marker only real JS carries, so the exclusion is a fact about the literal rather
# than a path allowlist that would silently cover a real message added to the same file later.
_JS_MARKERS = ("function(", "=>", "document.querySelector", "window.__")


def _is_javascript(text: str) -> bool:
    return any(m in text for m in _JS_MARKERS)


def test_no_backend_message_fakes_a_plural_with_parenthesised_s():
    offenders, skipped = [], []
    for path in sorted(BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, text in _message_literals(tree):
            if "(s)" not in text:
                continue
            where = f"{path.relative_to(BACKEND).as_posix()}:{lineno}"
            if _is_javascript(text):
                skipped.append(where)
            else:
                offenders.append(f"{where}: {text.strip()}")
    # Never silent about what was excluded: a gate that quietly drops candidates reads as full
    # coverage while covering less.
    print(f"[plural gate] {counted(len(skipped), 'JavaScript payload')} not checked: {skipped}")
    assert offenders == [], (
        "a count must agree with its noun - use stockroom.text.counted:\n  "
        + "\n  ".join(offenders)
    )


def test_the_fab_preset_mismatch_names_one_layer_in_the_singular():
    # The message a person actually reads when they pick the wrong preset. One copper layer is not
    # "1 copper layer(s)".
    with pytest.raises(ValueError) as exc:
        validate_preset_apply("oshpark_2", board_copper_count=1)
    assert "1 copper layer;" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        validate_preset_apply("oshpark_2", board_copper_count=4)
    assert "4 copper layers;" in str(exc.value)
