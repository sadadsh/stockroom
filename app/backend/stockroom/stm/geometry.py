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
#   rev 2 (2026-07-23): PACKAGE_GEOMETRY (hand-curated pitch/body/depopulation
#     table) + audit_has_power_pad added.
#   rev 3 (2026-07-23): parse_bga_position widened to accept a leading numeric
#     zone prefix ("1A2" -> row "1A", col 2) - discovered against the REAL
#     all-families source (STM32MP1 SiP packages TFBGA361/257, VFBGA273/424:
#     64 device XML use a secondary die/POP-memory ball zone labeled with a
#     leading digit, distinct from the main perimeter grid's plain "A1" labels
#     on the SAME device). Without this, StmIndex.build raised ValueError and
#     refused to ingest any STM32MP1 device in these four packages - a real
#     regression this phase's own Pitfall-2 discipline exists to catch. Never
#     silently dropped; the zone digit is preserved IN the row identifier so
#     "1A2" and "A2" resolve to distinct, non-colliding bga_row values.
GEOMETRY_REV = 3

# JEDEC ball-grid row letters skip 'I' (easily confused with '1'). Single letters
# A..Z minus I (25 letters), then double letters continue the same convention
# (AA, AB, ... skipping any second-letter I) for packages large enough to need them.
_ROW_ALPHABET = [c for c in string.ascii_uppercase if c != "I"]

# Row group: an optional leading zone digit (STM32MP1 SiP secondary ball zones,
# e.g. "1A2") followed by one or more row letters; column group: trailing digits.
_BGA_POSITION = re.compile(r"^(\d*[A-Za-z]+)(\d+)$")


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


def infer_body_shape(package_name: str, has_alnum_positions: bool) -> str:
    """Best-effort body shape for a package with NO curated PACKAGE_GEOMETRY row,
    so an uncurated package still renders honestly instead of falling back to a
    perimeter default that a ball-grid package cannot satisfy. The name decides
    when its vocabulary is known (WLCSP/CSP, BGA, QFN-family); real alnum ball
    positions force an area-array shape even for an unknown name. A consumer must
    surface the result as inferred, never as a curated fact."""
    name = (package_name or "").upper()
    if "WLCSP" in name or "CSP" in name:
        return "wlcsp"
    if "BGA" in name:
        return "bga"
    if has_alnum_positions:
        return "bga"
    if "QFPN" in name or "QFN" in name or "DFN" in name or "SON" in name:
        return "qfn"
    return "qfp"


# ─────────────────────────────────────────────────────────────────────────────
# PACKAGE_GEOMETRY - hand-curated package mechanical facts CubeMX never states
# (Plan 02 / DATA-03). Keyed by CubeMX Package name.
#
# COVERAGE DEFINITION OF DONE (recorded per this phase's CONTEXT.md open
# question): this is a PRIORITIZED SUBSET, not 100% of the 134 distinct
# packages the real all-families source (2,125 device XML) was found to
# contain this session. It covers the phase's three committed test fixtures
# (LQFP64, UFQFPN48, UFBGA64 - REQUIRED) plus the next highest-MCU-count
# packages from a real census run against the confirmed Windows-side source at
# "/mnt/c/Users/Sadad Haidari/STMP/cubemx_db/mcu" (2026-07-23): LQFP100 (205
# MCUs), LQFP64 (192), LQFP48 (148), UFQFPN48 (140), LQFP144 (137), UFQFPN32
# (68), LQFP176 (65), UFBGA100 (55), UFBGA169 (55), UFBGA64 (50) - roughly 52%
# of all ingested MCUs by this subset alone. Per PITFALLS.md's own recovery
# strategy ("don't block all BGA rendering on 100% automated geometry
# coverage"), this is a legitimate, explicitly-recorded choice, not silence.
# A package NOT in this dict has NO package_geometry row after StmIndex.build
# (never a fabricated default) - that absence IS the "geometry unavailable"
# state; any consumer must treat a missing lookup as unavailable, not guess.
#
# PROVENANCE, read carefully (an honest, logged gap per the owner's standing
# ledger directive - not hidden):
#   - pin_count, rows, cols, and depopulation below ARE empirically verified
#     this session by parsing one real device XML per package from the
#     confirmed all-families source (not guessed): distinct <Pin Position=...>
#     counts and, for BGA, the actual observed row-letter/column-number span.
#     UFBGA100's 12x12 canvas holding only 100 populated balls (44 corner
#     positions depopulated) and UFBGA169's fully-populated 13x13 grid were
#     both confirmed this way.
#   - pitch_mm and body_mm are standard JEDEC package-outline values (LQFP =
#     JEDEC MS-026, QFN = JEDEC MO-220/MO-248-family, UFBGA = ST's own
#     ultra-fine-pitch BGA family drawings) that are consistent across
#     virtually the entire ST portfolio for a given package name - these are
#     NOT independently re-verified against a freshly fetched datasheet PDF
#     this session (no live datasheet fetch tool was available in this
#     execution environment). The DS citation per entry is a REAL, already
#     in-repo datasheet reference (the same DS numbers cited in
#     legacy/tools/stm32_authority.py's FAMILY_ELECTRICAL/FAMILY_POWER
#     tables), pointed at that datasheet's package-mechanical-data section,
#     not a page-number-verified fetch. This is flagged explicitly in the
#     01-02-SUMMARY.md as an open follow-up item (a DATA-07-style hand-check
#     of pitch_mm/body_mm against a real mechanical drawing PDF), same spirit
#     as the phase's own stratified hand-check for pin data.
#   - has_center_pad reflects the MAJORITY HasPowerPad value observed across
#     every real device in that package this session (UFQFPN48: 138 false /
#     2 true; UFQFPN32: 54 false / 14 true) - the minority is a genuine
#     per-device fact PACKAGE_GEOMETRY intentionally does NOT average away;
#     audit_has_power_pad below surfaces it instead of swallowing it.
PACKAGE_GEOMETRY: dict[str, dict] = {
    "LQFP64": {
        "body_shape": "qfp", "pin_count": 64, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 10.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS9826 Rev 6 (STM32F0 package-mechanical-data section); "
                     "JEDEC MS-026 LQFP64 outline, 10x10mm body, 0.5mm pitch",
        "notes": "Phase 1 fixture package (STM32F030RCTx). Grid/pin-count "
                 "confirmed against a real device XML this session; "
                 "pitch/body are standard JEDEC values, not independently "
                 "re-verified against a fetched PDF - see module docstring.",
    },
    "UFQFPN48": {
        "body_shape": "qfn", "pin_count": 48, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 7.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS9826 Rev 6 (STM32F0 package-mechanical-data section); "
                     "JEDEC MO-220 UFQFPN48 outline, 7x7mm body, 0.5mm pitch",
        "notes": "Phase 1 fixture package (STM32F048C6Ux). HasPowerPad "
                 "observed 138 false / 2 true across the real all-families "
                 "source this session - majority (no exposed pad) recorded "
                 "here; the minority is surfaced by audit_has_power_pad, "
                 "never averaged away.",
    },
    "UFBGA64": {
        "body_shape": "bga", "pin_count": 64, "rows": 8, "cols": 8,
        "pitch_mm": 0.4, "body_mm": 5.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS9826 Rev 6 (STM32F0 package-mechanical-data section); "
                     "ST UFBGA64 outline, 5x5mm body, 0.4mm pitch, "
                     "fully-populated 8x8 ball grid (A1..H8)",
        "notes": "Phase 1 fixture package (STM32F072RBIx). Fully-populated "
                 "8x8 grid (rows A-H, cols 1-8) confirmed against the real "
                 "device XML this session.",
    },
    "LQFP48": {
        "body_shape": "qfp", "pin_count": 48, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 7.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS9826 Rev 6 (STM32F0 package-mechanical-data section); "
                     "JEDEC MS-026 LQFP48 outline, 7x7mm body, 0.5mm pitch",
        "notes": "148 MCUs in the real all-families census (2026-07-23). "
                 "Pin count confirmed against a real device XML this session.",
    },
    "LQFP100": {
        "body_shape": "qfp", "pin_count": 100, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 14.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS8626 (DocID022152) Rev 5 (STM32F4 package-mechanical-"
                     "data section); JEDEC MS-026 LQFP100 outline, 14x14mm "
                     "body, 0.5mm pitch",
        "notes": "Highest-MCU-count package in the real census (205 MCUs, "
                 "2026-07-23). The phase's rich F407 fixture uses this "
                 "package. Pin count confirmed against a real device XML.",
    },
    "LQFP144": {
        "body_shape": "qfp", "pin_count": 144, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 20.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS8626 (DocID022152) Rev 5 (STM32F4 package-mechanical-"
                     "data section); JEDEC MS-026 LQFP144 outline, 20x20mm "
                     "body, 0.5mm pitch",
        "notes": "137 MCUs in the real all-families census. Pin count "
                 "confirmed against a real device XML this session.",
    },
    "LQFP176": {
        "body_shape": "qfp", "pin_count": 176, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 24.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS10916 Rev 5 (STM32F7 package-mechanical-data "
                     "section); JEDEC MS-026 LQFP176 outline, 24x24mm body, "
                     "0.5mm pitch",
        "notes": "65 MCUs in the real all-families census. Pin count "
                 "confirmed against a real device XML this session.",
    },
    "UFQFPN32": {
        "body_shape": "qfn", "pin_count": 32, "rows": None, "cols": None,
        "pitch_mm": 0.5, "body_mm": 5.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS9826 Rev 6 (STM32F0 package-mechanical-data section); "
                     "JEDEC MO-220 UFQFPN32 outline, 5x5mm body, 0.5mm pitch",
        "notes": "68 MCUs in the real all-families census. HasPowerPad "
                 "observed 54 false / 14 true (a notable ~20% minority) "
                 "across the real source this session - majority recorded "
                 "here; audit_has_power_pad surfaces the minority.",
    },
    "UFBGA100": {
        "body_shape": "bga", "rows": 12, "cols": 12, "pin_count": 100,
        "pitch_mm": 0.5, "body_mm": 7.0, "has_center_pad": 0,
        "depopulation": "corner-depopulated: 100 of 144 canvas positions "
                        "populated (12x12 grid, corners omitted)",
        "citation": "DS8626 (DocID022152) Rev 5 (STM32F4 package-mechanical-"
                     "data section); ST UFBGA100 outline, 7x7mm body, "
                     "0.5mm pitch",
        "notes": "55 MCUs in the real all-families census. Grid span (rows "
                 "A-H,J-M; cols 1-12) and the 100-of-144 depopulation "
                 "confirmed against a real device XML this session.",
    },
    "UFBGA169": {
        "body_shape": "bga", "rows": 13, "cols": 13, "pin_count": 169,
        "pitch_mm": 0.4, "body_mm": 7.0, "has_center_pad": 0,
        "depopulation": None,
        "citation": "DS8626 (DocID022152) Rev 5 (STM32F4 package-mechanical-"
                     "data section); ST UFBGA169 outline, 7x7mm body, "
                     "0.4mm pitch, fully-populated 13x13 ball grid",
        "notes": "55 MCUs in the real all-families census. Fully-populated "
                 "13x13 grid (rows A-H,J-N; cols 1-13) confirmed against a "
                 "real device XML this session.",
    },
}


def audit_has_power_pad(observed: dict[str, set[bool]]) -> list[str]:
    """Cross-check CubeMX's per-device root HasPowerPad attribute against the
    curated PACKAGE_GEOMETRY.has_center_pad fact for that package.

    ``observed`` is package_name -> the set of HasPowerPad boolean values seen
    across every device ingested this build. Returns the sorted list of
    package names to SURFACE (never silently swallow): either the sampled
    devices disagree among themselves (a package-mechanical fact should not
    vary within one true package - itself a real signal something is off), or
    they agree but disagree with the curated table's has_center_pad value.
    A package absent from PACKAGE_GEOMETRY is skipped here (nothing curated
    to cross-check against).
    """
    flagged: set[str] = set()
    for package, values in observed.items():
        entry = PACKAGE_GEOMETRY.get(package)
        if entry is None:
            continue  # nothing curated to cross-check against
        if len(values) > 1:
            flagged.add(package)
            continue
        observed_value = next(iter(values))
        if bool(entry["has_center_pad"]) != observed_value:
            flagged.add(package)
    return sorted(flagged)
