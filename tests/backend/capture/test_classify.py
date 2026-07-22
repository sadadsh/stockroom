import zipfile
from pathlib import Path

from stockroom.capture.classify import classify_asset
from stockroom.capture.requirements import Requirement


def test_loose_kicad_symbol():
    c = classify_asset(Path("BQ24074.kicad_sym"))
    assert c.tool == "kicad" and c.kind == "symbol"
    assert c.requirements == frozenset({Requirement.KICAD_SYMBOL})


def test_loose_model():
    assert classify_asset(Path("part.step")).requirements == frozenset({Requirement.KICAD_MODEL})
    assert classify_asset(Path("part.STP")).requirements == frozenset({Requirement.KICAD_MODEL})


def test_loose_altium_schlib_and_pcblib():
    assert classify_asset(Path("x.SchLib")).requirements == frozenset({Requirement.ALTIUM_SYMBOL})
    assert classify_asset(Path("x.PcbLib")).requirements == frozenset({Requirement.ALTIUM_FOOTPRINT})


def test_intlib_is_both_altium():
    c = classify_asset(Path("x.IntLib"))
    assert c.requirements == frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def test_unknown_extension():
    c = classify_asset(Path("readme.txt"))
    assert c.tool == "unknown" and c.requirements == frozenset()


def test_mixed_zip(tmp_path):
    z = tmp_path / "bundle.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("KiCad/BQ24074.kicad_sym", "x")
        zf.writestr("KiCad/BQ24074.kicad_mod", "x")
        zf.writestr("KiCad/BQ24074.step", "x")
        zf.writestr("Altium/BQ24074.SchLib", "x")
        zf.writestr("Altium/BQ24074.PcbLib", "x")
    c = classify_asset(z)
    assert c.kind == "zip" and c.tool == "mixed"
    assert c.requirements == frozenset(Requirement)


def test_kicad_only_zip(tmp_path):
    z = tmp_path / "k.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.kicad_sym", "x")
        zf.writestr("a.kicad_mod", "x")
    c = classify_asset(z)
    assert c.tool == "kicad"
    assert c.requirements == frozenset({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT})


def test_altium_only_zip(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.SchLib", "x")
        zf.writestr("a.PcbLib", "x")
    c = classify_asset(z)
    assert c.tool == "altium"
    assert c.requirements == frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def test_bad_zip_is_unknown(tmp_path):
    z = tmp_path / "bad.zip"
    z.write_bytes(b"not a zip")
    c = classify_asset(z)
    assert c.tool == "unknown" and c.kind == "zip" and c.requirements == frozenset()
