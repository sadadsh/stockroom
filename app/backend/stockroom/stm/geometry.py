"""Per-pin package geometry facts: typed LQFP/QFN/BGA positions (Qt-free, stdlib-only).

CubeMX gives every pin a raw ``Position`` string: a plain integer for perimeter
packages (LQFP/QFN, "1".."N", four-sided by construction) or a JEDEC ball label for
area-array packages (BGA/WLCSP, "A1".."AB12"). Hardware's stm32_db.py dropped every
alphanumeric position (`int(el.get("Position")) : except ValueError: continue`) -
that is Pitfall 2, and it silently zeroed out entire BGA/WLCSP packages. This module
keeps both position kinds as first-class, typed facts: a numeric perimeter position
gets an `lqfp_side`; an alnum ball position gets a parsed `bga_row`/`bga_col`.

Geometry-fact functions here are pure and per-pin; the curated, cited
PACKAGE_GEOMETRY table (pitch/body/depopulation - facts CubeMX never states at all)
is added by Plan 02.
"""

from __future__ import annotations

import re
import string

# Classification/geometry-rule revision, stamped into every built index (mirrors
# CLASSIFIER_REV's bump-log convention in db.py). StmIndex.load() refuses a file
# whose stamped geometry_rev does not match this constant.
#   rev 1 (2026-07-23): initial port - lqfp_side unchanged from Hardware; NEW
#     parse_bga_position for alnum BGA/WLCSP balls (Hardware dropped these).
GEOMETRY_REV = 1

# JEDEC ball-grid row letters skip 'I' (easily confused with '1'). Single letters
# A..Z minus I (25 letters), then double letters continue the same convention
# (AA, AB, ... skipping any second-letter I) for packages large enough to need them.
_ROW_ALPHABET = [c for c in string.ascii_uppercase if c != "I"]

_BGA_POSITION = re.compile(r"^([A-Za-z]+)(\d+)$")


def lqfp_side(pos: int, n: int) -> str | None:
    """Which of the four sides a numeric perimeter position sits on (1-indexed,
    quartered around the package). Ported verbatim from Hardware's stm32_db.py -
    QFN packages (UFQFPN48/32, numeric, four-sided) use this identically to LQFP;
    only true BGA/WLCSP alnum positions need parse_bga_position instead."""
    if n <= 0 or pos < 1 or pos > n:
        return None
    q = n // 4
    if pos <= q:
        return "left"
    if pos <= 2 * q:
        return "bottom"
    if pos <= 3 * q:
        return "right"
    return "top"


def parse_bga_position(raw: str) -> tuple[str, int]:
    """"A1" -> ("A", 1); "AB12" -> ("AB", 12). Raises ValueError on a malformed label.

    NEW: Hardware has no equivalent (it drops every alnum position at parse time).
    """
    m = _BGA_POSITION.match((raw or "").strip())
    if not m:
        raise ValueError(f"not a BGA/WLCSP position label: {raw!r}")
    return m.group(1).upper(), int(m.group(2))


def bga_row_index(row: str) -> int:
    """0-based ordinal of a BGA row letter in JEDEC order (skips 'I'), so a UI can
    sort/compare rows without re-deriving the skip rule. bga_row_index("H") + 1 ==
    bga_row_index("J") (there is no row "I")."""
    row = row.upper()
    if len(row) == 1:
        return _ROW_ALPHABET.index(row)
    base = len(_ROW_ALPHABET)
    first, second = row[0], row[1:]
    return base + _ROW_ALPHABET.index(first) * base + bga_row_index(second)


def per_pin_geometry(package_name: str, raw_position: str, pin_count: int) -> dict:
    """One pin's typed position facts for a given (package, raw CubeMX Position,
    the package's total distinct physical pin count).

    Numeric positions (LQFP/QFN, perimeter) resolve position_kind='numeric' plus a
    non-null lqfp_side; bga_row/bga_col stay null. Alnum positions (BGA/WLCSP,
    area-array) resolve position_kind='alnum' plus non-null bga_row/bga_col;
    lqfp_side stays null. package_name is accepted (not yet used) so a future
    package-shape-specific override has a natural seam without changing the signature.
    """
    del package_name  # not yet needed; kept in the signature per INTERFACES section 3
    raw = (raw_position or "").strip()
    try:
        pos_int = int(raw)
    except ValueError:
        row, col = parse_bga_position(raw)
        return {
            "position_kind": "alnum",
            "lqfp_side": None,
            "bga_row": row,
            "bga_col": col,
        }
    return {
        "position_kind": "numeric",
        "lqfp_side": lqfp_side(pos_int, pin_count),
        "bga_row": None,
        "bga_col": None,
    }
