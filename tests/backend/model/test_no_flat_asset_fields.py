"""No code may reach for a part's assets through the pre-cutover flat fields.

The old record had implicitly-KiCad `symbol`/`footprint`/`model` plus bolted-on
`altium_symbol`/`altium_footprint` and NO Altium model slot. That asymmetry caused the
permanent "CAD Incomplete" bug (readiness read the KiCad fields for Altium) and the
attach-clobber bug (an Altium attach overwrote the KiCad reference). Both are now impossible
by construction -- every tool owns a symmetric `EdaAssets` bundle in `record.assets`.

This is the gate that keeps it that way. It exists because the failure mode is SILENT:
`getattr(part, "symbol", None)` still compiles, still runs, and now returns None forever --
which is exactly what happened to `projects/fill.py` during the cutover and would have made
every project fill match nothing with no error anywhere.
"""
import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3] / "app" / "backend" / "stockroom"

# The attribute names that no longer exist on PartRecord.
FLAT_FIELDS = {"altium_symbol", "altium_footprint"}
# These names are legitimate on OTHER objects (a staged part, a resolved passive, a footprint
# object, a candidate), so `x.symbol` alone is not evidence of a bug. Only a getattr against a
# STRING literal is unambiguous -- that is the form that fails silently.
GETATTR_NAMES = FLAT_FIELDS | {"symbol", "footprint", "model"}

# `model/part.py` legitimately names the legacy keys: it is the module that CONSUMES them.
ALLOWED_FILES = {"model/part.py"}


def _python_files():
    for path in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(BACKEND).as_posix()
        if rel in ALLOWED_FILES:
            continue
        yield rel, path


def test_the_scan_actually_sees_the_backend():
    # Guard the harness: a glob that silently returns nothing would make every assertion
    # below pass vacuously, which is worse than having no gate at all.
    files = list(_python_files())
    assert len(files) > 50, f"only found {len(files)} backend modules; the scan is broken"


@pytest.mark.parametrize("rel,path", list(_python_files()), ids=lambda v: v if isinstance(v, str) else "")
def test_no_module_reads_an_asset_through_a_removed_flat_field(rel, path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        # `record.altium_symbol` -- the attribute is gone, so this would AttributeError,
        # but catching it here names the fix instead of waiting for a runtime crash.
        if isinstance(node, ast.Attribute) and node.attr in FLAT_FIELDS:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        # `getattr(x, "symbol", None)` -- the SILENT form. It keeps working and returns the
        # default forever, so nothing raises and nothing fails until behaviour is wrong.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in GETATTR_NAMES
        ):
            offenders.append(f"line {node.lineno}: getattr(..., {node.args[1].value!r})")

    assert not offenders, (
        f"{rel} reaches for a part's assets through a removed flat field: "
        + "; ".join(offenders)
        + '. Use record.assets_for("<tool>").<kind> and name the EDA tool explicitly.'
    )
