import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import detect_source


def _touch(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_octopart_detected_by_device_lib_and_dcm(tmp_path):
    _touch(tmp_path / "device.lib")
    _touch(tmp_path / "device.dcm")
    _touch(tmp_path / "MyPart.pretty" / "fp.kicad_mod")
    _touch(tmp_path / "MyPart.step")
    d = detect_source(tmp_path)
    assert d.vendor == "octopart"
    assert d.symbol_path.name == "device.lib"
    assert d.dcm_path.name == "device.dcm"
    assert [p.name for p in d.footprint_paths] == ["fp.kicad_mod"]
    assert d.model_path.name == "MyPart.step"


def test_samacsys_detected_by_exact_KiCad_folder(tmp_path):
    _touch(tmp_path / "KiCad" / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "KiCad" / "MyPart.kicad_mod", "(footprint)")
    d = detect_source(tmp_path)
    assert d.vendor == "samacsys"
    assert d.symbol_path.suffix == ".kicad_sym"
    assert [p.name for p in d.footprint_paths] == ["MyPart.kicad_mod"]


def test_samacsys_prefers_kicad_sym_over_legacy_lib(tmp_path):
    _touch(tmp_path / "KiCad" / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "KiCad" / "MyPart.lib", "EESchema")
    _touch(tmp_path / "KiCad" / "MyPart.kicad_mod", "(footprint)")
    d = detect_source(tmp_path)
    assert d.symbol_path.suffix == ".kicad_sym"


def test_ultralibrarian_detected_by_exact_KiCAD_folder_and_pretty(tmp_path):
    base = tmp_path / "KiCAD"
    _touch(base / "2025-02-10_09-58-00.lib", "EESchema")  # timestamp-named symbol
    _touch(base / "MyPart.pretty" / "VarA.kicad_mod", "(footprint)")
    _touch(base / "MyPart.pretty" / "VarB.kicad_mod", "(footprint)")
    _touch(tmp_path / "3D" / "MyPart.stp")
    d = detect_source(tmp_path)
    assert d.vendor == "ultralibrarian"
    assert d.symbol_path.name == "2025-02-10_09-58-00.lib"
    assert sorted(p.name for p in d.footprint_paths) == ["VarA.kicad_mod", "VarB.kicad_mod"]
    assert d.model_path.name == "MyPart.stp"


def test_snapeda_fallback_loose_files(tmp_path):
    _touch(tmp_path / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "MyPart.kicad_mod", "(footprint)")
    _touch(tmp_path / "MyPart.step")
    _touch(tmp_path / "datasheet.pdf")
    _touch(tmp_path / "how-to-import.htm")
    d = detect_source(tmp_path)
    assert d.vendor == "snapeda"
    assert d.symbol_path.name == "MyPart.kicad_sym"
    assert [p.name for p in d.footprint_paths] == ["MyPart.kicad_mod"]
    assert d.datasheet_path.name == "datasheet.pdf"


def test_partial_model_only(tmp_path):
    _touch(tmp_path / "MyPart.step")
    d = detect_source(tmp_path)
    assert d.vendor == "partial"
    assert d.model_path.name == "MyPart.step"
    assert d.symbol_path is None
    assert d.footprint_paths == []


def test_model_priority_step_over_stp_over_wrl(tmp_path):
    _touch(tmp_path / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "a.wrl")
    _touch(tmp_path / "b.stp")
    _touch(tmp_path / "c.step")
    d = detect_source(tmp_path)
    assert d.model_path.name == "c.step"


def test_nothing_usable_raises(tmp_path):
    _touch(tmp_path / "readme.txt")
    with pytest.raises(IngestError):
        detect_source(tmp_path)
