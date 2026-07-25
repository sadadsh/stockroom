#!/usr/bin/env python3
"""Generate the frontend's copy of the EDA tool registry from the Python one.

`stockroom/eda/registry.py` is the single place a tool's facts live (owner, 2026-07-24), but
the frontend needs those same facts SYNCHRONOUSLY to render readiness -- a part is ready for
a tool when that tool's assets are present, and an asset kind the tool cannot take by
reference must never be reported as a closable gap. Fetching that over the API would make a
pure derivation async for no benefit, and hand-copying it would drift the day someone edits
one side only.

So the TS file is GENERATED here and a test (`tests/backend/eda/test_registry_ts_parity.py`)
fails if the checked-in file does not match what this script would write. Adding a third EDA
tool stays "add a registry entry, then run this script".

    uv run python scripts/gen_eda_registry_ts.py          # write the file
    uv run python scripts/gen_eda_registry_ts.py --check   # exit 1 if it is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))

from stockroom.eda.registry import all_tools, default_tool  # noqa: E402
from stockroom.model.part import ASSET_LABELS  # noqa: E402

OUT_PATH = REPO_ROOT / "app" / "frontend" / "src" / "lib" / "edaRegistry.generated.ts"


def _ts_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ts_key(value: str) -> str:
    """An object key: bare when it is a plain identifier, quoted otherwise."""
    return value if value.isidentifier() else _ts_string(value)


def render() -> str:
    lines = [
        "/**",
        " * GENERATED FILE -- do not hand-edit.",
        " *",
        " * Mirrors `app/backend/stockroom/eda/registry.py`, the one place an EDA tool's facts",
        " * live. Regenerate with `uv run python scripts/gen_eda_registry_ts.py`; a pytest",
        " * (tests/backend/eda/test_registry_ts_parity.py) fails if this file drifts from the",
        " * Python registry, so the two can never disagree about what a tool can hold.",
        " */",
        "",
        "// One EDA tool's facts, as far as the UI is concerned.",
        "export interface EdaToolSpec {",
        "  /** Registry key, and the key into a part's `eda` map. */",
        "  key: string;",
        "  /** Display label. */",
        "  label: string;",
        "  /** Asset kinds this tool consumes, in report order. */",
        "  assetKinds: string[];",
        "  /**",
        "   * Asset kinds this tool CANNOT be given by reference, mapped to why. Never report",
        "   * one of these as a missing asset: it names a gap that can never be closed.",
        "   */",
        "  unsupportedAssets: Record<string, string>;",
        "}",
        "",
        "// Human labels for the asset kinds, keyed as the registry keys them.",
        "export const ASSET_LABELS: Record<string, string> = {",
    ]
    for kind, label in ASSET_LABELS.items():
        lines.append(f"  {_ts_key(kind)}: {_ts_string(label)},")
    lines += [
        "};",
        "",
        "// Every registered tool, in the registry's stable order.",
        "export const EDA_TOOLS: EdaToolSpec[] = [",
    ]
    for tool in all_tools():
        lines.append("  {")
        lines.append(f"    key: {_ts_string(tool.key)},")
        lines.append(f"    label: {_ts_string(tool.label)},")
        kinds = ", ".join(_ts_string(k) for k in tool.asset_kinds)
        lines.append(f"    assetKinds: [{kinds}],")
        if tool.unsupported_assets:
            lines.append("    unsupportedAssets: {")
            for kind, why in tool.unsupported_assets.items():
                lines.append(f"      {_ts_key(kind)}:")
                lines.append(f"        {_ts_string(why)},")
            lines.append("    },")
        else:
            lines.append("    unsupportedAssets: {},")
        lines.append("  },")
    lines += [
        "];",
        "",
        "// The default tool the UI targets when the user has not chosen one.",
        f"export const DEFAULT_EDA_TOOL = {_ts_string(default_tool().key)};",
        "",
        "export function edaTool(key: string): EdaToolSpec | undefined {",
        "  return EDA_TOOLS.find((t) => t.key === key);",
        "}",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = ap.parse_args(argv)

    expected = render()
    current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else None
    if args.check:
        if current == expected:
            print(f"up to date: {OUT_PATH.relative_to(REPO_ROOT).as_posix()}")
            return 0
        print(
            f"STALE: {OUT_PATH.relative_to(REPO_ROOT).as_posix()} does not match the Python "
            f"EDA registry. Run: uv run python scripts/gen_eda_registry_ts.py",
            file=sys.stderr,
        )
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
