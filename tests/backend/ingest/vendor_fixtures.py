"""Build synthetic vendor-layout zips from the repo's KiCad fixtures so the
ingestion pipeline is tested against real directory shapes, not mocks."""

from __future__ import annotations

import zipfile
from pathlib import Path


def make_vendor_zip(dst_zip: Path, vendor: str, fixtures_dir: Path) -> Path:
    sym = (fixtures_dir / "one_symbol.kicad_sym").read_bytes()
    legacy = (fixtures_dir / "legacy.lib").read_bytes()
    fp = (fixtures_dir / "one_footprint.kicad_mod").read_bytes()
    step = b"ISO-10303-21;\n"
    with zipfile.ZipFile(dst_zip, "w") as zf:
        if vendor == "octopart":
            zf.writestr("device.lib", legacy)
            zf.writestr("device.dcm", "EESchema-DOCLIB  Version 2.0\n#\n#End Doc Library\n")
            zf.writestr("MyPart.pretty/MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
        elif vendor == "samacsys":
            zf.writestr("KiCad/MyPart.kicad_sym", sym)
            zf.writestr("KiCad/MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
            zf.writestr("MyPart.epw", "pointer")  # junk, ignored
        elif vendor == "ultralibrarian":
            zf.writestr("KiCAD/2025-02-10_09-58-00.kicad_sym", sym)
            zf.writestr("KiCAD/MyPart.pretty/VarA.kicad_mod", fp)
            zf.writestr("KiCAD/MyPart.pretty/VarB.kicad_mod", fp)
            zf.writestr("3D/MyPart.stp", step)
        elif vendor == "snapeda":
            zf.writestr("MyPart.kicad_sym", sym)
            zf.writestr("MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
            zf.writestr("how-to-import.htm", "<html></html>")  # junk marker
        else:
            raise ValueError(f"unknown vendor: {vendor}")
    return dst_zip
