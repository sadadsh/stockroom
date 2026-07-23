"""Task 3: typed LQFP/QFN/BGA positions - the Pitfall 2 non-drop regression lock.

Hardware's stm32_db.py silently dropped every alphanumeric BGA/WLCSP Position
(`int(Position)` : except ValueError: continue), zeroing out 22/35 packages. This
module's geometry facts (position_kind + lqfp_side or bga_row/bga_col) must never
reproduce that drop.
"""

from pathlib import Path

from stockroom.stm import db as db_mod
from stockroom.stm import geometry as geometry_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def _legacy_lqfp_side(pos: int, n: int):
    """The exact legacy algorithm (legacy/tools/stm32_db.py:291-301), reproduced
    inline so a spot-check does not depend on importing the Qt-adjacent legacy
    module - proves stm.geometry.lqfp_side is behaviorally unchanged."""
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


def test_lqfp_side_matches_legacy_at_n_64_spot_check():
    for pos in (1, 16, 17, 32, 33, 48, 49, 64):
        assert geometry_mod.lqfp_side(pos, 64) == _legacy_lqfp_side(pos, 64)


def test_parse_bga_position_single_and_double_letter_rows():
    assert geometry_mod.parse_bga_position("A1") == ("A", 1)
    assert geometry_mod.parse_bga_position("H8") == ("H", 8)
    assert geometry_mod.parse_bga_position("AB12") == ("AB", 12)


def test_bga_row_letter_sequence_skips_i_so_j_follows_h():
    assert geometry_mod.bga_row_index("H") + 1 == geometry_mod.bga_row_index("J")
    # 'I' itself is never a valid JEDEC row letter - it is simply absent from the
    # ordering, not indexable at all.
    assert "I" not in geometry_mod._ROW_ALPHABET


def test_build_from_fixtures_bga_alnum_vs_numeric_partition():
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn

    bga_mcu = conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F072RBIx'"
    ).fetchone()
    bga_rows = conn.execute(
        "SELECT position_kind, bga_row, bga_col, lqfp_side FROM mcu_package_pin "
        "WHERE mcu_id = ?",
        (bga_mcu["id"],),
    ).fetchall()
    assert len(bga_rows) == 64
    assert all(r["position_kind"] == "alnum" for r in bga_rows)
    assert all(r["bga_row"] is not None and r["bga_col"] is not None for r in bga_rows)
    assert all(r["lqfp_side"] is None for r in bga_rows)

    for ref in ("STM32F030RCTx", "STM32F048C6Ux"):
        mcu = conn.execute("SELECT id FROM mcu WHERE ref_name = ?", (ref,)).fetchone()
        rows = conn.execute(
            "SELECT position_kind, bga_row, bga_col, lqfp_side FROM mcu_package_pin "
            "WHERE mcu_id = ?",
            (mcu["id"],),
        ).fetchall()
        assert len(rows) > 0
        assert all(r["position_kind"] == "numeric" for r in rows)
        assert all(r["lqfp_side"] is not None for r in rows)
        assert all(r["bga_row"] is None and r["bga_col"] is None for r in rows)


def test_no_package_in_the_build_ends_with_zero_pins():
    """The explicit regression lock against Hardware's int()-or-drop behavior,
    which killed 22/35 packages by silently reducing them to zero parsed pins."""
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    rows = conn.execute(
        "SELECT m.package_name, COUNT(p.id) n FROM mcu m "
        "LEFT JOIN mcu_package_pin p ON p.mcu_id = m.id "
        "GROUP BY m.id"
    ).fetchall()
    assert len(rows) == 4
    for r in rows:
        assert r["n"] > 0, f"package {r['package_name']} parsed zero pins"


def test_infer_body_shape_by_package_name_and_position_evidence():
    """A package with no curated PACKAGE_GEOMETRY row still gets an honest body shape:
    the name decides when it can (WLCSP/BGA/QFN vocabulary), and alnum ball positions
    force an area-array shape even for a name the vocabulary does not know."""
    infer = geometry_mod.infer_body_shape
    # area-array names, with or without ball evidence
    assert infer("UFBGA176", True) == "bga"
    assert infer("TFBGA100", True) == "bga"
    assert infer("LFBGA354", True) == "bga"
    assert infer("WLCSP49", True) == "wlcsp"
    # ball evidence wins over an unknown name
    assert infer("MYSTERY99", True) == "bga"
    # perimeter names
    assert infer("UFQFPN28", False) == "qfn"
    assert infer("VFQFPN32", False) == "qfn"
    assert infer("UQFN48", False) == "qfn"
    assert infer("LQFP32", False) == "qfp"
    assert infer("TSSOP20", False) == "qfp"
    # unknown perimeter name falls back to the quad-flat default
    assert infer("", False) == "qfp"
