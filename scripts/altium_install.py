#!/usr/bin/env python3
"""Install the generated `.DbLib` into Altium, so its parts are reachable in the Components panel.

A correct database library that Altium has not been told about is worth nothing. Measured
2026-07-26 on the owner's real machine: the Installed Libraries list was EMPTY, so no Stockroom
part could be browsed or dragged however perfect the file was. This is the Altium counterpart to
what `kicad/wiring.py` already does for KiCad.

Costs one Altium boot and the license seat, so close a windowed Altium first (it will say so).
Idempotent: a library already installed reports `already` rather than being added twice.

    uv run python scripts/altium_install.py                      # the in-repo library
    uv run python scripts/altium_install.py --dblib <path>
    uv run python scripts/altium_install.py --dblib <path> --uninstall

No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.altium.install import install_library  # noqa: E402

_DEFAULT = REPO / "libraries" / "Stockroom" / "altium" / "Stockroom.DbLib"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dblib", type=Path, default=_DEFAULT)
    ap.add_argument("--uninstall", action="store_true", help="remove it from Altium instead")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)

    res = install_library(a.dblib.expanduser(), uninstall=a.uninstall, timeout=a.timeout)
    # Both lists, always. "It is installed" is a claim; the list is the observation behind it.
    print(f"  before ({len(res.before)}): {', '.join(res.before) or '<none>'}")
    print(f"  after  ({len(res.after)}): {', '.join(res.after) or '<none>'}")
    print(f"{res.status.upper()}: {res.detail}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
