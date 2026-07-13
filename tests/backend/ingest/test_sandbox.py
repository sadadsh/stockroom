import zipfile

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.sandbox import sha256_of, unpack_inputs


def test_unpack_zip_extracts_into_isolated_root(tmp_path):
    z = tmp_path / "part.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("KiCad/foo.kicad_mod", "(footprint)")
    work = tmp_path / "work"
    [u] = unpack_inputs([z], work)
    assert u.is_zip is True
    assert (u.root / "KiCad" / "foo.kicad_mod").read_text() == "(footprint)"
    assert u.sha256 == sha256_of(z)


def test_unpack_bare_file_copies_into_root(tmp_path):
    f = tmp_path / "sym.kicad_sym"
    f.write_text("(kicad_symbol_lib)")
    [u] = unpack_inputs([f], tmp_path / "work")
    assert u.is_zip is False
    assert (u.root / "sym.kicad_sym").read_text() == "(kicad_symbol_lib)"
    assert u.sha256 == sha256_of(f)


def test_unpack_folder_copies_tree(tmp_path):
    src = tmp_path / "src"
    (src / "KiCAD").mkdir(parents=True)
    (src / "KiCAD" / "a.lib").write_text("x")
    [u] = unpack_inputs([src], tmp_path / "work")
    assert (u.root / "KiCAD" / "a.lib").read_text() == "x"
    assert u.sha256 == ""


def test_unpack_multiple_inputs_get_separate_roots(tmp_path):
    a = tmp_path / "a.kicad_sym"; a.write_text("a")
    b = tmp_path / "b.kicad_sym"; b.write_text("b")
    us = unpack_inputs([a, b], tmp_path / "work")
    assert len(us) == 2
    assert us[0].root != us[1].root


def test_zip_slip_is_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "pwn")
    with pytest.raises(IngestError):
        unpack_inputs([z], tmp_path / "work")


def test_missing_input_raises(tmp_path):
    with pytest.raises(IngestError):
        unpack_inputs([tmp_path / "nope.zip"], tmp_path / "work")
