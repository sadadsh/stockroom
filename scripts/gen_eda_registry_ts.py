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

from stockroom.eda.registry import all_tools, data_field_union, default_tool  # noqa: E402
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
        "  /**",
        "   * Asset kinds this tool takes only by EMBEDDING: the tool itself writes the payload",
        "   * into a binary container the part already owns (an Altium 3D body goes inside the",
        "   * footprint's .PcbLib). A kind may be BOTH unsupported-by-reference and embeddable,",
        "   * and that combination is a real, closable gap that MUST be reported. `reason`",
        "   * explains what embedding needs, so a machine without the tool can say why rather",
        "   * than silently doing nothing.",
        "   */",
        "  embeddedAssets: Record<string, EmbeddedAssetSpec>;",
        "  /**",
        "   * Record data this tool RECEIVES when a part is placed from the library, in the order",
        "   * the tool's own artifact declares it. This is what the detail sheet's handoff band",
        "   * renders, and it differs per tool: an Altium DbLib row carries price and stock",
        "   * columns a KiCad schematic has no property for.",
        "   */",
        "  dataFields: DataFieldSpec[];",
        "}",
        "",
        "// One piece of record data a tool receives (mirrors stockroom.eda.registry.DataField).",
        "export interface DataFieldSpec {",
        "  /** The record-derived value this carries. The stable key to join on. */",
        "  key: string;",
        "  /** What a person calls it. */",
        "  label: string;",
        "  /** What THIS tool calls it: a KiCad property name, or an Altium Design Parameter. */",
        "  toolField: string;",
        "  /** Whether the tool shows this on the placed component by default. */",
        "  visible: boolean;",
        "  /**",
        "   * Whether a placed component can be measured as MISSING this. False for a field the",
        "   * tool receives structurally rather than as a fillable property (a KiCad symbol",
        "   * arrives as the component's lib_id, and no component can exist without one).",
        "   */",
        "  passport: boolean;",
        "}",
        "",
        "// One row of the handoff band: a field, and every tool that receives it.",
        "export interface UnionFieldSpec {",
        "  key: string;",
        "  label: string;",
        "  /** Registry declaration order, so the tools read in a stable order. */",
        "  tools: string[];",
        "  /**",
        "   * Who owns this value:",
        "   *  - \"curated\": a PERSON maintains it. The handoff band shows exactly these.",
        "   *  - \"vendor\": a distributor refresh supplies it; it is the Sourcing column's",
        "   *    subject, carries a vendor attribution there, and changes on its own.",
        "   *  - \"derived\": computed from other fields when the artifact is emitted and never",
        "   *    stored, so there is no value to show and re-deriving it here would fork the rule.",
        "   */",
        "  origin: \"curated\" | \"vendor\" | \"derived\";",
        "}",
        "",
        "// How one asset kind gets embedded (mirrors stockroom.eda.registry.EmbeddedAsset).",
        "export interface EmbeddedAssetSpec {",
        "  /** The asset whose file receives the payload. */",
        "  container: string;",
        "  /** The asset kind that supplies the payload. */",
        "  source: string;",
        "  /** Whether embedding needs the EDA tool installed on this machine. */",
        "  requiresToolInstalled: boolean;",
        "  reason: string;",
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
        if tool.embedded_assets:
            lines.append("    embeddedAssets: {")
            for kind, spec in tool.embedded_assets.items():
                lines.append(f"      {_ts_key(kind)}: {{")
                lines.append(f"        container: {_ts_string(spec.container)},")
                lines.append(f"        source: {_ts_string(spec.source)},")
                lines.append(
                    "        requiresToolInstalled: "
                    f"{'true' if spec.requires_tool_installed else 'false'},"
                )
                lines.append(f"        reason: {_ts_string(spec.reason)},")
                lines.append("      },")
            lines.append("    },")
        else:
            lines.append("    embeddedAssets: {},")
        lines.append("    dataFields: [")
        for f in tool.data_fields:
            lines.append(
                f"      {{ key: {_ts_string(f.key)}, label: {_ts_string(f.label)}, "
                f"toolField: {_ts_string(f.tool_field)}, "
                f"visible: {'true' if f.visible else 'false'}, "
                f"passport: {'true' if f.passport else 'false'} }},"
            )
        lines.append("    ],")
        lines.append("  },")
    lines += [
        "];",
        "",
        "/**",
        " * Every record field ANY registered tool consumes, deduplicated, each naming its",
        " * consumers. The handoff band renders exactly this, so a third EDA tool joins that band",
        " * by declaring `data_fields` in the Python registry - with no edit here and none in the",
        " * component. Order is registry declaration order, never alphabetical: the band must open",
        " * on the part number, not on \"Category\".",
        " */",
        "export const EDA_DATA_FIELDS: UnionFieldSpec[] = [",
    ]
    for uf in data_field_union():
        tools = ", ".join(_ts_string(t) for t in uf.tools)
        lines.append(
            f"  {{ key: {_ts_string(uf.key)}, label: {_ts_string(uf.label)}, "
            f"tools: [{tools}], origin: {_ts_string(uf.origin)} }},"
        )
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
