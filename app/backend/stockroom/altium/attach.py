"""CLI: attach a part's Altium assets so it becomes a place-ready row in the regenerated DbLib.

Accepts EITHER a loose .SchLib + .PcbLib pair OR a single compiled .IntLib (auto-extracted).
Completes the "populate through Stockroom" loop: add the part (existing flow), attach its Altium
assets (here), then `python -m stockroom.altium.emit` regenerates the one .DbLib over every
place-ready part.

Usage:
  python -m stockroom.altium.attach <part_id> <BQ24074RGTT.IntLib>
  python -m stockroom.altium.attach <part_id> <BQ24074RGTT.SchLib> <BQ24074RGTT.PcbLib>
"""
from __future__ import annotations

import sys
from pathlib import Path

_USAGE = "usage: python -m stockroom.altium.attach <part_id> <file> [<file> ...]"


def _parse_args(argv) -> tuple[str, list[Path]]:
    if len(argv) < 2:
        raise SystemExit(_USAGE)
    part_id = argv[0]
    sources = [Path(a) for a in argv[1:]]
    missing = [str(s) for s in sources if not s.exists()]
    if missing:
        raise SystemExit(f"file(s) not found: {', '.join(missing)}")
    return part_id, sources


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    part_id, sources = _parse_args(argv)

    from stockroom.api.serve import build_context

    ctx = build_context()
    record = ctx.ops.attach_altium_assets(part_id, *sources)
    sym, fp = record.altium_symbol, record.altium_footprint
    print(f"Attached to {part_id}: symbol {sym.name} ({sym.lib}), footprint {fp.name} ({fp.lib})")
    print("Run `python -m stockroom.altium.emit` to regenerate the DbLib.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
