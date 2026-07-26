#!/usr/bin/env python3
"""Prove a part can actually be PLACED from the generated `.DbLib`, in real Altium.

`altium_dblib_verify.py` proves Altium can CONNECT to the data source. Connecting and placing are
different mechanisms, and only the first was ever measured, so "the Altium library works" rested on
an untested half. This closes it: it resolves the row's symbol and footprint, places the component
on a fresh sheet, saves it, and then re-reads the saved `.SchDoc` FROM OUTSIDE ALTIUM to say what
actually landed.

The risk it is aimed at is concrete. A Stockroom row names its libraries by BARE FILENAME
(`tpd6e05u06rvzr.SchLib`), and Altium resolves a bare filename through the DbLib's search paths
rather than relative to the `.DbLib` itself. Our emitter writes `LibrarySearchPath=.`, so placement
rests entirely on what `.` means to Altium, which is the exact shape of the bug that broke the
connection string on 2026-07-26.

Costs one Altium boot and a license seat. Exit code is non-zero when the place did not happen, so
this can gate a release.

Usage
-----
    uv run python scripts/altium_place_verify.py                     # the in-repo library
    uv run python scripts/altium_place_verify.py --dblib <path> --mpn TPD6E05U06RVZR
    uv run python scripts/altium_place_verify.py --keep               # keep the saved .SchDoc

No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.altium.place import place_from_dblib  # noqa: E402

_DEFAULT_DBLIB = REPO / "libraries" / "Stockroom" / "altium" / "Stockroom.DbLib"


def first_mpn(dblib: Path) -> str:
    """The first MPN in the DbLib's data source, so the gate needs no hardcoded part.

    Read from the SQLite file beside the .DbLib rather than from the .DbLib's own connection
    string: this runs on the WSL side where that Windows-absolute path does not resolve, and the
    point here is choosing a subject, not testing the connection (that is the other gate's job).
    """
    db = dblib.parent / "stockroom-parts.db"
    if not db.exists():
        return ""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT MPN FROM Parts ORDER BY MPN LIMIT 1").fetchone()
    return str(row[0]) if row else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dblib", type=Path, default=_DEFAULT_DBLIB, help="the .DbLib to place from")
    ap.add_argument("--mpn", default="", help="the row to place (default: the first in the table)")
    ap.add_argument("--out", type=Path, default=None, help="where to save the schematic")
    ap.add_argument("--keep", action="store_true", help="keep the saved .SchDoc for inspection")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args(argv)

    dblib = args.dblib.expanduser()
    if not dblib.exists():
        print(f"FAILED: no .DbLib at {dblib.as_posix()}")
        return 2
    mpn = args.mpn or first_mpn(dblib)
    if not mpn:
        print(f"FAILED: no part to place. {dblib.parent.as_posix()} has no readable data source.")
        return 2

    print(f"placing {mpn!r} from {dblib.as_posix()}")
    res = place_from_dblib(dblib, mpn, schdoc=args.out, timeout=args.timeout)

    # Resolution is reported WHATEVER the outcome, because a run that timed out during placement
    # still answers the question the search-path risk is about.
    print(f"  symbol library:    {res.symbol_library or '<UNRESOLVED>'}")
    print(f"  symbol reference:  {res.symbol_reference or '<none>'}")
    print(f"  footprint library: {res.footprint_library or '<UNRESOLVED>'}")
    if res.placed_design_item_ids:
        print(f"  placed on sheet:   {', '.join(res.placed_design_item_ids)}")
        print(f"  footprint on part: {', '.join(res.placed_footprints) or '<MISSING>'}")
        print(f"  DbLib columns carried onto the placement: {len(res.placed_parameters)}")
    print(f"{'PLACED' if res.ok else 'FAILED'}: {res.detail}")
    if res.altium_log:
        print("--- Altium's own log ---")
        print(res.altium_log.strip())

    if res.ok and not args.keep:
        for path in (args.out,) if args.out else ():
            Path(path).unlink(missing_ok=True)
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
