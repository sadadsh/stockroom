"""Plan 02 Task 3: check_availability + the all-families build guard (DATA-01).

The build must never promise "all families" against a source that looks F-only.
"""

from pathlib import Path

import pytest

from stockroom.stm import db as db_mod
from stockroom.stm import source as source_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_check_availability_reports_f_only_for_the_committed_fixtures():
    report = source_mod.check_availability(FIXTURES)
    assert report.device_xml_count == 4
    # The four committed fixtures span STM32F0 (x3) and STM32F4 (x1) - 2 families.
    assert report.family_count == 2
    assert report.all_families is False
    assert set(report.families) == {"STM32F0", "STM32F4"}


def test_check_availability_reports_source_path():
    report = source_mod.check_availability(FIXTURES)
    assert report.source_path == str(FIXTURES)


def test_check_availability_all_families_true_when_family_count_exceeds_f_only(tmp_path):
    # Synthesize a source spanning 7 distinct families (more than the F0-F7
    # six-family ceiling) using minimal per-family XML.
    src = tmp_path / "src"
    src.mkdir()
    families = ["STM32F0", "STM32F1", "STM32F2", "STM32F3", "STM32F4", "STM32F7", "STM32G0"]
    for i, fam in enumerate(families):
        (src / f"SYNTH_{fam}_{i}.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<Mcu Family="{fam}" Package="LQFP48" RefName="SYNTH_{fam}_{i}" '
            f'xmlns="http://mcd.rou.st.com/modules.php?name=mcu">\n'
            f"</Mcu>\n",
            encoding="utf-8",
        )
    report = source_mod.check_availability(src)
    assert report.family_count == 7
    assert report.all_families is True


def test_build_guard_raises_when_source_looks_f_only_without_descope():
    with pytest.raises(db_mod.StmSourceCoverageError):
        db_mod.StmIndex.build(FIXTURES, require_all_families=True)


def test_build_succeeds_against_f_only_source_when_not_requiring_all_families():
    # Default (require_all_families=False) never raises - fixture-scoped/dev
    # builds keep working; the meta stamp still honestly reports all_families=False.
    idx = db_mod.StmIndex.build(FIXTURES)
    assert idx.meta()["all_families"] == "false"
    assert idx.meta()["family_count"] == "2"
    assert idx.meta()["device_xml_count"] == "4"
