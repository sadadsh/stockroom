"""The frontend's generated copy of the EDA registry must never drift from the Python one.

The UI derives readiness synchronously from the same facts the backend uses (which asset
kinds a tool takes, which it cannot take by reference at all). Two hand-maintained copies of
that would drift the day someone edits one side -- and the LAST time the frontend disagreed
with the backend about a tool's assets, every part read "CAD Incomplete" forever.

So the TS file is generated, and this is the gate: it runs in the suite the owner already
runs, and it fails with the exact command to fix it.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GEN = REPO_ROOT / "scripts" / "gen_eda_registry_ts.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_eda_registry_ts", GEN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_generator_script_exists():
    # Guards the harness itself: if the script were moved, every assertion below would
    # otherwise fail with an unrelated error (or, worse, be skipped).
    assert GEN.is_file(), f"missing {GEN}"


def test_the_checked_in_ts_registry_matches_the_python_registry():
    gen = _load_generator()
    expected = gen.render()
    assert gen.OUT_PATH.is_file(), (
        f"{gen.OUT_PATH} is missing; run: uv run python scripts/gen_eda_registry_ts.py"
    )
    actual = gen.OUT_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "app/frontend/src/lib/edaRegistry.generated.ts is stale. "
        "Run: uv run python scripts/gen_eda_registry_ts.py"
    )


def test_check_mode_agrees_with_the_comparison():
    gen = _load_generator()
    assert gen.main(["--check"]) == 0


def test_a_registry_change_would_actually_be_caught():
    # Prove the gate can FAIL. A parity test that cannot go red is worse than no test.
    gen = _load_generator()
    from stockroom.eda import registry

    extra = registry.EdaTool(key="zz_probe", label="Probe", asset_kinds=("symbol",))
    original = dict(registry._REGISTRY)
    registry._REGISTRY["zz_probe"] = extra
    try:
        assert gen.render() != gen.OUT_PATH.read_text(encoding="utf-8")
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(original)


def test_the_default_tool_is_kicad_not_whichever_sorts_first():
    from stockroom.eda.registry import all_tools, default_tool

    assert default_tool().key == "kicad"
    assert all_tools()[0].key == "kicad", "declaration order is the UI's offer order"
