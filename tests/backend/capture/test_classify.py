import io
import zipfile
from pathlib import Path

from stockroom.capture.classify import (
    LIA_IMPORT_ROUTE,
    AssetGroup,
    classify_asset,
)
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


def test_samacsys_epw_pointer_is_not_counted_as_cad():
    c = classify_asset(Path("download.epw"))
    assert c.tool == "unknown"
    assert c.kind == "unknown"
    assert c.requirements == frozenset()


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


def test_suffixless_ole_schlib_classifies_by_content(tmp_path):
    # WebView2 can save a download as a GUID ".tmp" with no useful name. A zip already
    # classifies by its members; an OLE compound file (a loose .SchLib/.PcbLib saved
    # that way) must classify by ITS content too, never drop as unknown.
    import shutil as _sh
    from pathlib import Path as _P

    fx = _P(__file__).parent.parent / "altium" / "fixtures"
    p = tmp_path / "guid-download.tmp"
    _sh.copyfile(fx / "sample.SchLib", p)
    got = classify_asset(p)
    assert got.tool == "altium"
    assert Requirement.ALTIUM_SYMBOL in got.requirements


def test_suffixless_ole_pcblib_classifies_by_content(tmp_path):
    import shutil as _sh
    from pathlib import Path as _P

    fx = _P(__file__).parent.parent / "altium" / "fixtures"
    p = tmp_path / "guid-download2.tmp"
    _sh.copyfile(fx / "sample.PcbLib", p)
    got = classify_asset(p)
    assert got.tool == "altium"
    assert Requirement.ALTIUM_FOOTPRINT in got.requirements


def test_zip_nested_inside_a_zip_classifies_its_members(tmp_path):
    # Vendors sometimes wrap the Altium zip INSIDE the bundle zip; the members of an
    # inner zip (one level) count toward the classification.
    import io
    import zipfile as _zf

    inner = io.BytesIO()
    with _zf.ZipFile(inner, "w") as z:
        z.writestr("part.SchLib", "x")
        z.writestr("part.PcbLib", "x")
    outer = tmp_path / "bundle.zip"
    with _zf.ZipFile(outer, "w") as z:
        z.writestr("README.txt", "hi")
        z.writestr("altium/part-altium.zip", inner.getvalue())
    got = classify_asset(outer)
    assert Requirement.ALTIUM_SYMBOL in got.requirements
    assert Requirement.ALTIUM_FOOTPRINT in got.requirements


def test_a_pcad_lia_satisfies_BOTH_altium_requirements(tmp_path):
    """MEASURED 2026-07-27 by downloading Ultra Librarian's PCAD v15 export for a real part.

    OWNER'S CORRECTION, and they were right: *"in ul when u download the altium pcad files it gives
    u a lia"*. A `.LIA` is a P-CAD ASCII library, which Altium Designer imports directly. The
    downloaded file carries `ACCEL_ASCII` plus exactly one `symbolDef` (the schematic symbol), one
    `patternDef` (the PCB footprint) and one `compDef` - 69 pads and 212 pin references - so ONE
    file satisfies altium_symbol AND altium_footprint, the same shape as a compiled `.IntLib`.

    This corrects a conclusion that had been coded as capability: measuring only the "Altium
    Designer (script based)" row (which ships a Delphi script and no libraries) had produced
    "Ultra Librarian cannot supply Altium", which was over-generalised from one row of three.
    """
    lia = tmp_path / "TPD6E05U06RVZR.lia"
    lia.write_text('ACCEL_ASCII "TEST.LIA"\n(symbolDef "S")\n(patternDef "P")\n', encoding="utf-8")
    got = classify_asset(lia)
    assert Requirement.ALTIUM_SYMBOL in got.requirements
    assert Requirement.ALTIUM_FOOTPRINT in got.requirements
    assert got.tool == "altium"


def test_a_lia_inside_a_vendor_zip_is_found_too(tmp_path):
    """Ultra Librarian delivers it nested under `AltiumV15/`, never loose."""
    import zipfile

    bundle = tmp_path / "ul.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("AltiumV15/2026-07-27_20-52-11.lia", 'ACCEL_ASCII "X"\n(symbolDef "S")\n')
        zf.writestr("AltiumV15/ImportGuide.html", "<html></html>")
    got = classify_asset(bundle)
    assert Requirement.ALTIUM_SYMBOL in got.requirements
    assert Requirement.ALTIUM_FOOTPRINT in got.requirements


# --- the three named groups -------------------------------------------------
# Classification has to say out loud which of three groups a file belongs to:
# importable CAD, supporting material that is never auto-imported, and prohibited
# executable/script content. "Unknown" stays available and is not a claim of safety.


def test_importable_cad_group_covers_every_kicad_and_altium_shape(tmp_path):
    for name in (
        "part.kicad_sym",
        "part.lib",
        "part.kicad_mod",
        "MyPart.pretty",
        "part.step",
        "part.STP",
        "part.wrl",
        "part.SchLib",
        "part.PcbLib",
        "part.IntLib",
        "part.lia",
    ):
        got = classify_asset(Path(name))
        assert got.group is AssetGroup.IMPORTABLE_CAD, name
        assert got.requirements, name


def test_a_pretty_directory_is_a_kicad_footprint_role(tmp_path):
    pretty = tmp_path / "MyPart.pretty"
    pretty.mkdir()
    (pretty / "VarA.kicad_mod").write_text("(footprint)")
    got = classify_asset(pretty)
    assert got.tool == "kicad" and got.kind == "footprint"
    assert got.requirements == frozenset({Requirement.KICAD_FOOTPRINT})
    assert got.group is AssetGroup.IMPORTABLE_CAD


def test_the_lia_route_is_named_so_nothing_imports_the_raw_file():
    # A `.lia` satisfies both Altium roles, but only through the proven P-CAD
    # normalization; the route is recorded here so callers cannot invent another one.
    assert LIA_IMPORT_ROUTE == "stockroom.altium.converter.convert_pcad_ascii"
    got = classify_asset(Path("x.lia"))
    assert got.group is AssetGroup.IMPORTABLE_CAD
    assert got.requirements == frozenset(
        {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}
    )


def test_supporting_material_is_named_supporting_not_dropped():
    for name in ("datasheet.pdf", "README.txt", "LICENSE", "how-to-import.htm", "preview.png"):
        got = classify_asset(Path(name))
        assert got.group is AssetGroup.SUPPORTING, name
        assert got.requirements == frozenset(), name


def test_prohibited_content_is_named_by_extension():
    for name in (
        "setup.exe", "installer.msi", "helper.dll", "run.bat", "run.cmd", "go.ps1",
        "loader.js", "loader.vbs", "saver.scr", "legacy.com", "open me.lnk",
    ):
        got = classify_asset(Path(name))
        assert got.group is AssetGroup.PROHIBITED, name
        assert got.requirements == frozenset(), name
        assert got.prohibited_members == (Path(name).name,), name


def test_prohibited_content_is_named_by_leading_bytes_too(tmp_path):
    # A content/extension mismatch that cannot be safely identified is prohibited, not
    # a 3D model: the name says STEP, the bytes say PE image.
    payload = tmp_path / "model.step"
    payload.write_bytes(b"MZ\x90\x00 the rest is a binary")
    got = classify_asset(payload)
    assert got.group is AssetGroup.PROHIBITED
    assert got.requirements == frozenset()


def test_a_bundle_carrying_an_executable_is_flagged_prohibited(tmp_path):
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("KiCad/part.kicad_sym", "x")
        zf.writestr("Install/setup.exe", "x")
    got = classify_asset(bundle)
    assert got.group is AssetGroup.PROHIBITED
    assert got.prohibited_members == ("Install/setup.exe",)
    # the CAD requirements are still reported so the person sees what the bundle claimed
    assert Requirement.KICAD_SYMBOL in got.requirements


def test_a_bundle_of_only_supporting_files_is_supporting(tmp_path):
    bundle = tmp_path / "docs.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("datasheet.pdf", "%PDF-1.4")
        zf.writestr("README.txt", "hi")
    got = classify_asset(bundle)
    assert got.group is AssetGroup.SUPPORTING
    assert got.requirements == frozenset()


def test_a_nested_archive_read_is_bounded_by_the_shared_limits(tmp_path, monkeypatch):
    # The nested member used to be read whole with `inner_fh.read()`. A member that
    # declares more than the shared per-member bound is now skipped, not swallowed.
    import stockroom.capture.classify as classify

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("part.SchLib", "x")
    outer = tmp_path / "bundle.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("altium/part.zip", inner.getvalue())
    monkeypatch.setattr(classify, "MAX_MEMBER_EXPANDED_BYTES", 4)
    got = classify.classify_asset(outer)
    assert got.requirements == frozenset()


def test_a_corrupt_inner_archive_still_leaves_the_bundle_usable(tmp_path):
    outer = tmp_path / "bundle.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("KiCad/part.kicad_sym", "x")
        z.writestr("altium/broken.zip", b"PK\x03\x04 not really")
    got = classify_asset(outer)
    assert Requirement.KICAD_SYMBOL in got.requirements
