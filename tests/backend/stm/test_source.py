"""CubeMX source coverage, build guards, and Windows discovery boundaries."""

from pathlib import Path

import pytest

from stockroom.stm import db as db_mod
from stockroom.stm import source as source_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_check_availability_reports_f_only_for_the_committed_fixtures():
    report = source_mod.check_availability(FIXTURES)
    assert report.device_xml_count == 4
    assert report.family_count == 2
    assert report.all_families is False
    assert set(report.families) == {"STM32F0", "STM32F4"}


def test_check_availability_reports_source_path():
    report = source_mod.check_availability(FIXTURES)
    assert report.source_path == str(FIXTURES)


def test_check_availability_all_families_true_when_family_count_exceeds_f_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    families = ["STM32F0", "STM32F1", "STM32F2", "STM32F3", "STM32F4", "STM32F7", "STM32G0"]
    for i, family in enumerate(families):
        (src / f"SYNTH_{family}_{i}.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<Mcu Family="{family}" Package="LQFP48" RefName="SYNTH_{family}_{i}" '
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
    idx = db_mod.StmIndex.build(FIXTURES)
    assert idx.meta()["all_families"] == "false"
    assert idx.meta()["family_count"] == "2"
    assert idx.meta()["device_xml_count"] == "4"


def test_normalize_accepts_the_cubemx_database_folder(tmp_path):
    database = tmp_path / "db"
    device_data = database / "mcu"
    device_data.mkdir(parents=True)
    (device_data / "STM32TEST.xml").write_text(
        '<Mcu Family="STM32F4" RefName="STM32TEST" />',
        encoding="utf-8",
    )

    assert source_mod.normalize_cubemx_source(database) == device_data


def test_device_xml_probe_degrades_when_the_source_cannot_be_read(tmp_path, monkeypatch):
    source_dir = tmp_path / "mcu"
    source_dir.mkdir()
    (source_dir / "STM32TEST.xml").write_text("<Mcu />", encoding="utf-8")
    monkeypatch.setattr(source_mod.ET, "iterparse", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))

    assert source_mod.has_device_xml(source_dir) is False


def test_windows_autodiscovery_never_points_back_into_wsl():
    candidates = tuple(Path(value) for value in source_mod._WINDOWS_CANDIDATES)

    assert candidates
    assert all(not candidate.as_posix().startswith("/mnt/") for candidate in candidates)
    assert all(candidate.drive for candidate in candidates)
