"""Every source key the backend can stamp on a value has a human label in the SPA.

`Mouser_web` reached the alternates disclosure as a vendor name because the frontend's label
table knew three keys (`mouser`, `lcsc`, `digikey`) and Title-cased everything else. The table
is now complete - but a table that is complete TODAY and has nothing watching it is the same
bug on a delay, so this walks the backend for the keys it can actually emit and fails when one
of them has no entry.

FACT, not judgement: an AST walk for `Sourced(<value>, "<key>", ...)` and `source="<key>"`,
which is exactly how a source key is written. Direction matters - it asserts backend ⊆ frontend.
A frontend entry with no backend producer is harmless (a retired adapter), so it is reported
rather than failed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend" / "stockroom"
SOURCED_TS = (
    Path(__file__).resolve().parents[2] / "app" / "frontend" / "src" / "lib" / "sourced.ts"
)


def _frontend_keys() -> set[str]:
    """The keys of SOURCE_LABELS, read out of the TypeScript.

    Parsed from the object literal rather than executed: a pytest run has no TS runtime, and
    shelling out to node would make a backend test depend on the frontend toolchain being
    installed. The literal is a flat `key: "Label",` map, so the shape is stable enough to
    read - and if it ever stops matching, the assertion below fails LOUD (an empty key set
    can never satisfy a non-empty backend set) instead of passing vacuously.
    """
    text = SOURCED_TS.read_text(encoding="utf-8")
    body = re.search(r"const SOURCE_LABELS[^{]*\{(.*?)\n\};", text, re.S)
    assert body, f"could not find the SOURCE_LABELS literal in {SOURCED_TS.name}"
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", body.group(1), re.M))


def _backend_source_keys() -> dict[str, str]:
    """Every literal source key the backend writes, mapped to where it was found."""
    found: dict[str, str] = {}
    for path in sorted(BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            where = f"{path.relative_to(BACKEND).as_posix()}:{node.lineno}"
            # ONLY the two constructors that stamp a value with who said it. Scanning every
            # `source=` keyword in the tree instead was too loose and convicted
            # `EmbeddedAsset(source="model")` in the EDA registry, where "source" means which
            # ASSET KIND the embed reads from - a different word that happens to be spelled the
            # same. Match the fact the rule is about, not a name that also appears elsewhere.
            if name not in ("Sourced", "SourcedValue"):
                continue
            # Sourced(value, "<source>", "<confidence>")
            if len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value:
                    found.setdefault(arg.value, where)
            # Sourced(value, source="<source>")
            for kw in node.keywords:
                if kw.arg == "source" and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str) and kw.value.value:
                        found.setdefault(kw.value.value, where)
    return found


def test_the_frontend_can_name_every_source_the_backend_emits():
    backend, frontend = _backend_source_keys(), _frontend_keys()
    assert frontend, "read no keys out of sourced.ts - the parser has drifted from the file"
    unlabelled = {k: v for k, v in sorted(backend.items()) if k not in frontend}
    assert not unlabelled, (
        "these source keys would reach a person as a Title-cased internal key; add them to "
        "SOURCE_LABELS in app/frontend/src/lib/sourced.ts:\n  "
        + "\n  ".join(f"{k}  (first seen {v})" for k, v in unlabelled.items())
    )
    # The other direction is information, not a failure: a label with no producer is a retired
    # adapter, which costs nothing. Printed so it can be pruned deliberately.
    orphans = sorted(frontend - set(backend))
    print(f"[source labels] {len(backend)} backend keys, orphan labels: {orphans}")
