"""Plan 02 Task 1: the cited, hand-curated package_geometry table + population.

DATA-03. PACKAGE_GEOMETRY is a prioritized subset (recorded coverage Definition
of Done - see stm/geometry.py's module-level docstring/comments), not 100% of
every distinct package the real all-families source contains; the three fixture
packages are REQUIRED coverage.
"""

from pathlib import Path

from stockroom.stm import db as db_mod
from stockroom.stm import geometry as geometry_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_fixture_packages_resolve_to_a_cited_geometry_entry():
    for pkg in ("LQFP64", "UFQFPN48", "UFBGA64"):
        entry = geometry_mod.PACKAGE_GEOMETRY.get(pkg)
        assert entry is not None, f"{pkg} missing from PACKAGE_GEOMETRY"
        assert entry["body_shape"] in ("qfp", "qfn", "bga", "wlcsp")
        assert entry.get("citation"), f"{pkg} entry missing a citation"


def test_build_populates_package_geometry_table_from_the_curated_dict():
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    rows = {
        r["package_name"]: r
        for r in conn.execute(
            "SELECT package_name, body_shape, pin_count, has_center_pad, citation "
            "FROM package_geometry"
        )
    }
    assert len(rows) == len(geometry_mod.PACKAGE_GEOMETRY)
    for pkg in ("LQFP64", "UFQFPN48", "UFBGA64"):
        assert pkg in rows
        assert rows[pkg]["body_shape"] in ("qfp", "qfn", "bga", "wlcsp")
        assert rows[pkg]["citation"]


def test_has_power_pad_disagreement_is_surfaced_not_swallowed():
    # sampled devices disagree among themselves -> surfaced regardless of the
    # curated table's value.
    flagged = geometry_mod.audit_has_power_pad({"UFQFPN48": {True, False}})
    assert flagged == ["UFQFPN48"]

    # sampled devices agree, but disagree with the curated has_center_pad=0.
    flagged = geometry_mod.audit_has_power_pad({"UFQFPN48": {True}})
    assert flagged == ["UFQFPN48"]

    # sampled devices agree WITH the curated value -> not flagged.
    flagged = geometry_mod.audit_has_power_pad({"UFQFPN48": {False}})
    assert flagged == []

    # a package with no curated entry has nothing to cross-check -> not flagged.
    flagged = geometry_mod.audit_has_power_pad({"SOME_UNCURATED_PKG": {True, False}})
    assert flagged == []


def test_no_package_selected_for_rendering_silently_defaults():
    """An uncovered package has NO package_geometry row - the absence itself is
    the explicit 'geometry unavailable' state, never an invented default."""
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    row = conn.execute(
        "SELECT * FROM package_geometry WHERE package_name = 'NOT_A_REAL_PACKAGE'"
    ).fetchone()
    assert row is None


def test_package_geometry_citations_are_real_datasheet_references():
    cited = sum(
        1
        for entry in geometry_mod.PACKAGE_GEOMETRY.values()
        if any(marker in entry["citation"] for marker in ("DS", "DocID", "Rev"))
    )
    assert cited == len(geometry_mod.PACKAGE_GEOMETRY)
