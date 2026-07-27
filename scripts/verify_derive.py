#!/usr/bin/env python3
"""Prove the spec's acceptance test against a REAL library, at whatever scale it has.

Spec section 9, verbatim: *"change the naming scheme, re-derive the entire library, and lose
nothing that was imported. If a re-derive can destroy imported data, the schema is wrong.
Concretely: a re-derive must be idempotent (run it twice, get identical records) and lossless (the
`sourced/` tree is never written by it)."*

    uv run python scripts/verify_derive.py                    # the whole active library
    uv run python scripts/verify_derive.py --limit 20         # a quick sample

PROMOTED from an ad-hoc check run twice by hand (2026-07-27) - once against a one-part scratch
library, once against the real one. The unit tests in `tests/backend/derive/` prove these properties
against FIXTURES; this proves them against the owner's actual records, which is a different claim:
a fixture cannot have the messy real payload, the odd category, or the 38-spec bag that a real
distributor answer does.

READ-ONLY BY CONSTRUCTION. It re-derives into memory and compares; it never writes a record. The
`sourced/` tree is hashed before and after so "lossless" is a measurement rather than a promise.
Exit code is non-zero if any property fails, so this can gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.derive.engine import rederive  # noqa: E402
from stockroom.derive.naming import scheme_names  # noqa: E402
from stockroom.model.part import PartRecord  # noqa: E402
from stockroom.model.sourced import SOURCED_DIRNAME  # noqa: E402


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", type=Path, default=REPO / "libraries" / "Stockroom")
    ap.add_argument("--limit", type=int, default=0, help="check only the first N records")
    ap.add_argument("--verbose", action="store_true", help="name every failing record")
    a = ap.parse_args(argv)

    library = a.library.resolve()
    parts_dir = library / "parts"
    if not parts_dir.is_dir():
        print(f"no parts directory at {parts_dir.as_posix()}", file=sys.stderr)
        return 2

    paths = sorted(parts_dir.glob("*.json"))
    if a.limit:
        paths = paths[: a.limit]

    evidence_before = _tree_hashes(library / SOURCED_DIRNAME)

    checked = with_evidence = 0
    not_idempotent: list[str] = []
    identity_changed: list[str] = []
    scheme_leaked: list[str] = []
    schemes = [s for s in scheme_names() if s != "spec-aware"]

    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = PartRecord.from_dict(raw)
        checked += 1
        if record.sources:
            with_evidence += 1

        at = record.derived.derived_at or "2026-01-01T00:00:00Z"
        ident = (record.id, record.mpn, record.manufacturer, record.part_class.value)

        # IDEMPOTENT: two derives from the same evidence must serialize identically.
        first = rederive(record, library, derived_at=at).dumps()
        second = rederive(record, library, derived_at=at).dumps()
        if first != second:
            not_idempotent.append(record.id)

        # IDENTITY: never rewritten by a derive, under any scheme.
        for scheme in schemes:
            other = rederive(record, library, derived_at=at, scheme=scheme)
            if (other.id, other.mpn, other.manufacturer, other.part_class.value) != ident:
                identity_changed.append(f"{record.id} ({scheme})")
            # Swapping the scheme may change ONLY the display name. Anything else moving means the
            # naming scheme is leaking into values it has no business deciding.
            base = json.loads(first)["derived"]
            got = other.derived.to_dict()
            if {k: v for k, v in got.items() if k != "display_name"} != {
                k: v for k, v in base.items() if k != "display_name"
            }:
                scheme_leaked.append(f"{record.id} ({scheme})")

    evidence_after = _tree_hashes(library / SOURCED_DIRNAME)

    print(f"library        : {library.as_posix()}")
    print(f"records checked: {checked}")
    print(f"  with evidence: {with_evidence} (the rest derive from nothing, which is honest)")
    print(f"schemes tried  : spec-aware + {', '.join(schemes)}")
    print()

    def report(label: str, bad: list[str]) -> bool:
        ok = not bad
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  ({len(bad)})"))
        if bad and a.verbose:
            for name in bad[:20]:
                print(f"          {name}")
        return ok

    results = [
        report("derive twice -> byte-identical record", not_idempotent),
        report("identity (id/mpn/manufacturer/part_class) survives every scheme", identity_changed),
        report("a scheme swap changes ONLY display_name", scheme_leaked),
        report("sourced/ untouched by every derive", []
               if evidence_after == evidence_before else ["evidence tree changed"]),
    ]
    n_files = len(evidence_before)
    n_bytes = sum(len((library / SOURCED_DIRNAME / f).read_bytes()) for f in evidence_before)
    print(f"\nevidence tree  : {n_files} files, {n_bytes:,} bytes - unchanged by "
          f"{checked * (1 + 2 * len(schemes))} derives")

    if with_evidence == 0:
        # Not a failure, but the properties above are close to vacuous without evidence to derive
        # FROM - and a green result that measured nothing is the outcome to avoid reporting.
        print("\n  WARNING: no record carries any evidence, so these passes prove very little. "
              "Run scripts/import_library.py --apply first.")

    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
