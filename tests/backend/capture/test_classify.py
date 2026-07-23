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


def test_model_only_zip_is_shared_like_loose(tmp_path):
    z = tmp_path / "m.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.step", "x")
    # a lone 3D model classifies the same whether loose or zipped
    assert classify_asset(z).tool == "shared"
    assert classify_asset(Path("a.step")).tool == "shared"


def test_valid_zip_all_unknown_is_unknown(tmp_path):
    z = tmp_path / "u.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.txt", "hi")
    c = classify_asset(z)
    assert c.tool == "unknown" and c.kind == "zip" and c.requirements == frozenset()


def test_loose_legacy_lib_symbol_and_wrl_model():
    assert classify_asset(Path("x.lib")).tool == "kicad"
    assert classify_asset(Path("x.lib")).requirements == frozenset({Requirement.KICAD_SYMBOL})
    assert classify_asset(Path("x.wrl")).requirements == frozenset({Requirement.KICAD_MODEL})


def test_classify_zip_by_content_without_zip_suffix(tmp_path):
    # A vendor download can land without a .zip name (WebView2 saves a Content-Disposition-less
    # download as a GUID .tmp). Classify it by CONTENT so a valid bundle is never dropped.
    import zipfile

    from stockroom.capture.classify import classify_asset
    from stockroom.capture.requirements import Requirement

    p = tmp_path / "b3b67b52-c43c-49f0-bae3-8a70f0582572.tmp"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("KiCADv6/x.kicad_sym", "sym")
        z.writestr("KiCADv6/footprints.pretty/x.kicad_mod", "mod")
        z.writestr("RC0603N_YAG.step", "3d")
    c = classify_asset(p)
    assert c.kind == "zip"
    assert Requirement.KICAD_SYMBOL in c.requirements
    assert Requirement.KICAD_FOOTPRINT in c.requirements
    assert Requirement.KICAD_MODEL in c.requirements


def test_classify_prefers_known_suffix_over_content_sniff(tmp_path):
    # A recognized EDA suffix still wins - a real .kicad_sym is scanned as a symbol, never zip-sniffed.
    from stockroom.capture.classify import classify_asset
    from stockroom.capture.requirements import Requirement

    p = tmp_path / "x.kicad_sym"
    p.write_text("(kicad_symbol_lib)")
    c = classify_asset(p)
    assert c.requirements == frozenset({Requirement.KICAD_SYMBOL})
