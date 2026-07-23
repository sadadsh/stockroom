"""Plan 04 Task 1: the real all-families build + full-device self-audit run.

Integration test against the REAL CubeMX source (not a fixture) - DATA-01's
acceptance gate. Skips cleanly (never fails) when the real source is absent, or
looks F-only, on a machine without the Windows-side tree.
"""

import subprocess
from pathlib import Path

import pytest

from stockroom.stm import db as db_mod
from stockroom.stm import source as source_mod


def _resolve_all_families_source() -> Path | None:
    """STM32_CUBEMX wins if set; otherwise the confirmed Windows-side default.
    Returns None (never raises) when nothing resolvable, or when what resolves
    looks F-only per check_availability - the F-only WSL fixture is never a
    valid stand-in for this integration test."""
    source = source_mod.default_cubemx_source()
    if source is None or not source.is_dir():
        return None
    report = source_mod.check_availability(source)
    if not report.all_families:
        return None
    return source


_SOURCE = _resolve_all_families_source()

pytestmark = pytest.mark.skipif(
    _SOURCE is None,
    reason="no reachable all-families CubeMX source (STM32_CUBEMX unset and the "
    "confirmed Windows-side default is absent or looks F-only on this machine)",
)


def test_check_availability_reports_all_families_against_the_real_source():
    report = source_mod.check_availability(_SOURCE)
    assert report.all_families is True
    assert report.device_xml_count > 2000
    assert report.family_count > 6


def test_build_against_the_real_source_passes_self_audit_and_stamps_honestly():
    index_path = source_mod.default_index_path()
    # StmIndex.build itself calls check_availability + run_self_audit; reaching
    # this line without a raised StmSourceCoverageError/StmAuditFailure already
    # proves both gates passed across every real device.
    idx = db_mod.StmIndex.build(_SOURCE, db_path=index_path, require_all_families=True)
    try:
        meta = idx.meta()
        assert meta["all_families"] == "true"
        assert int(meta["device_xml_count"]) > 2000
        assert int(meta["family_count"]) > 6
        assert meta["classifier_rev"] == str(db_mod.CLASSIFIER_REV)

        # zero zero-pin packages: guaranteed by run_self_audit already having
        # passed (it would have raised otherwise), reconfirmed directly here.
        zero_pin = idx._conn.execute(
            "SELECT COUNT(*) FROM mcu m LEFT JOIN mcu_package_pin p ON p.mcu_id = m.id "
            "GROUP BY m.id HAVING COUNT(p.id) = 0"
        ).fetchall()
        assert zero_pin == []

        assert index_path.exists()
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(index_path)],
            cwd=repo_root,
            capture_output=True,
        )
        # rc 0 = explicitly gitignored; rc 128 here specifically means "outside
        # the repository entirely" (confirmed via the real config_dir() default,
        # which deliberately lives under the OS per-machine config dir, e.g.
        # ~/.config/stockroom on Linux - store/machine_config.py's own
        # convention). Either is a valid "never committable" state; rc 1 (a
        # real, in-repo, NOT-ignored path) is the only genuine failure.
        outside_repo = (
            result.returncode == 128
            and b"outside repository" in result.stderr
        )
        assert result.returncode == 0 or outside_repo, (
            f"{index_path} is neither gitignored nor outside the repository - "
            "the derived STM index must never be committable "
            f"(git check-ignore rc={result.returncode}, stderr={result.stderr!r})"
        )
    finally:
        idx.close()


def test_load_round_trips_the_real_all_families_index():
    index_path = source_mod.default_index_path()
    loaded = db_mod.StmIndex.load(index_path)
    assert loaded is not None
    assert loaded.mcu_count() > 2000
    loaded.close()


def test_second_build_with_unchanged_source_skips_reparse():
    index_path = source_mod.default_index_path()
    first = db_mod.StmIndex.load(index_path)
    assert first is not None
    first_built_at = first.meta()["built_at"]
    first.close()

    second = db_mod.StmIndex.build(_SOURCE, db_path=index_path, require_all_families=True)
    try:
        assert second.meta()["built_at"] == first_built_at
    finally:
        second.close()
