#!/usr/bin/env python3
"""Answer "is my library complete?" against the owner's own acceptance bar. Read-only.

    uv run python scripts/library_audit.py
    uv run python scripts/library_audit.py --strict        # exit 1 if the bar is not met
    uv run python scripts/library_audit.py --list-gaps     # name every failing record

PROMOTED 2026-07-27 after writing the same audit as a throwaway heredoc three times in one session.
It is not scaffolding: *"is my library complete"* is a question the OWNER asks, not one that only
exists while developing, and answering it by hand each time is the app missing a feature. This is
the CLI half; it belongs behind a UI surface eventually, and until then it is at least a committed
command with a real interface rather than something retyped from memory.

THE BAR IS THE OWNER'S, quoted from the spec's measured starting state (section 3):

    "Zero records missing description, manufacturer or datasheet"

plus the structural invariants the v3 schema is supposed to guarantee: every record on the current
schema, every id path-safe, every filename agreeing with its id, and no two records sharing an MPN.

WHAT IT DOES NOT CLAIM. Completeness of DATA is not completeness of ASSETS - a part can have a
perfect description and no footprint. Asset readiness is `f(part_class, tool)` and is reported
SEPARATELY below, per class, because a passive needing no files is complete and a component missing
its symbol is not, and rolling those into one percentage is how a coverage number starts reading
like a quality claim.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.eda.registry import all_tools  # noqa: E402
from stockroom.model.part import SCHEMA_VERSION, PartRecord, asset_present  # noqa: E402
from stockroom.model.part_class import needed_kinds  # noqa: E402
from stockroom.model.part_id import is_valid_part_id  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", type=Path, default=REPO / "libraries" / "Stockroom")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the acceptance bar is unmet")
    ap.add_argument("--list-gaps", action="store_true", help="name every record behind the bar")
    a = ap.parse_args(argv)

    parts_dir = a.library.resolve() / "parts"
    if not parts_dir.is_dir():
        print(f"no parts directory at {parts_dir.as_posix()}", file=sys.stderr)
        return 2

    records: list[tuple[Path, PartRecord]] = []
    unreadable: list[str] = []
    for path in sorted(parts_dir.glob("*.json")):
        try:
            records.append((path, PartRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))))
        except Exception as exc:  # noqa: BLE001 - an unreadable record is a finding, not a crash
            unreadable.append(f"{path.name}: {type(exc).__name__}: {exc}")

    gaps: dict[str, list[str]] = collections.defaultdict(list)
    by_class: collections.Counter = collections.Counter()
    by_evidence: collections.Counter = collections.Counter()
    specs: list[int] = []
    mpn_owners: dict[str, list[str]] = collections.defaultdict(list)
    tools = [t.key for t in all_tools()]
    asset_gap: collections.Counter = collections.Counter()
    class_ready: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])

    for path, rec in records:
        by_class[rec.part_class.value] += 1
        by_evidence[tuple(sorted(rec.sources))] += 1
        specs.append(len(rec.specs or {}))
        mpn_owners[rec.mpn.strip().upper()].append(rec.id)

        if not rec.description:
            gaps["description"].append(rec.id)
        if not rec.manufacturer:
            gaps["manufacturer"].append(rec.id)
        if not (rec.datasheet and (rec.datasheet.file or rec.datasheet.source_url)):
            gaps["datasheet"].append(rec.id)
        if not rec.mpn:
            gaps["mpn"].append(rec.id)
        if rec.schema_version != SCHEMA_VERSION:
            gaps[f"schema != v{SCHEMA_VERSION}"].append(f"{rec.id} (v{rec.schema_version})")
        if not is_valid_part_id(rec.id):
            gaps["id not path-safe"].append(rec.id)
        if path.stem != rec.id:
            gaps["filename != id"].append(f"{path.name} vs {rec.id}")
        if not rec.sources:
            gaps["no sourced evidence"].append(rec.id)

        # Asset readiness, per class and per tool - never rolled into one number.
        complete_for_all = True
        for tool in tools:
            bundle = rec.assets_for(tool)
            for kind in needed_kinds(rec.part_class, tool, rec.requires_override):
                if not asset_present(bundle.get(kind)):
                    asset_gap[f"{tool}:{kind}"] += 1
                    complete_for_all = False
        slot = class_ready[rec.part_class.value]
        slot[1] += 1
        if complete_for_all:
            slot[0] += 1

    dupes = {m: ids for m, ids in mpn_owners.items() if len(ids) > 1}

    print(f"library : {a.library.resolve().as_posix()}")
    print(f"records : {len(records)}" + (f"  ({len(unreadable)} UNREADABLE)" if unreadable else ""))
    print(f"classes : {dict(by_class)}")
    print("evidence: " + ", ".join(
        f"{'+'.join(k) if k else 'none'}={v}" for k, v in sorted(by_evidence.items())
    ))
    if specs:
        ordered = sorted(specs)
        print(f"specs   : min {ordered[0]}, median {ordered[len(ordered) // 2]}, max {ordered[-1]}")

    print("\nTHE OWNER'S BAR - zero records missing description, manufacturer or datasheet:")
    for field in ("description", "manufacturer", "datasheet"):
        n = len(gaps.get(field, []))
        print(f"  {'PASS' if not n else 'FAIL'}  missing {field}: {n}")

    print("\nSTRUCTURAL INVARIANTS the v3 schema is meant to guarantee:")
    for field in ("mpn", f"schema != v{SCHEMA_VERSION}", "id not path-safe", "filename != id"):
        n = len(gaps.get(field, []))
        print(f"  {'PASS' if not n else 'FAIL'}  {field}: {n}")
    print(f"  {'PASS' if not dupes else 'FAIL'}  two records sharing one MPN: {len(dupes)}")
    print(f"  {'PASS' if not unreadable else 'FAIL'}  unreadable records: {len(unreadable)}")

    print("\nASSET READINESS, reported PER CLASS on purpose (a passive needing no files is")
    print("complete; folding that into one percentage makes coverage read as quality):")
    for cls, (ready, total) in sorted(class_ready.items()):
        pct = f"{100 * ready // total}%" if total else "n/a"
        print(f"  {cls:11s} {ready}/{total} have every asset their class needs  ({pct})")
    if asset_gap:
        print("  outstanding asset gaps by tool:kind:")
        for key, n in sorted(asset_gap.items(), key=lambda kv: -kv[1]):
            print(f"    {key:20s} {n}")

    print(f"\n  records with no sourced evidence: {len(gaps.get('no sourced evidence', []))}")

    if a.list_gaps:
        print()
        for field, ids in sorted(gaps.items()):
            if ids:
                print(f"{field} ({len(ids)}):")
                for i in ids[:40]:
                    print(f"    {i}")
        for mpn, ids in dupes.items():
            print(f"duplicate MPN {mpn}: {', '.join(ids)}")
        for u in unreadable:
            print(f"unreadable: {u}")

    bar_met = not any(gaps.get(f) for f in ("description", "manufacturer", "datasheet", "mpn"))
    structural = not dupes and not unreadable and not any(
        gaps.get(f) for f in (f"schema != v{SCHEMA_VERSION}", "id not path-safe", "filename != id")
    )
    if a.strict and not (bar_met and structural):
        print("\nSTRICT: the bar is not met.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
