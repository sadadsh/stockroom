import shutil

import pytest

from stockroom.kicad.lib_table import LibTable
from stockroom.verify.semdiff import semantic_diff


def _load(tmp_path, name):
    src = pytest.importorskip  # noqa: keep import structure simple
    dst = tmp_path / name
    shutil.copyfile(
        __import__("pathlib").Path(__file__).parent.parent / "fixtures" / "kicad" / (name + ".sample"),
        dst,
    )
    return dst


def test_reads_existing_entries(tmp_fixture, fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    assert t.entries() == ["KiCad", "MySymbols"]
    assert t.has_lib("MySymbols")
    assert not t.has_lib("SR-ICs")


def test_append_adds_one_row_and_preserves_everything(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    before = dst.read_bytes().decode("utf-8")
    t = LibTable.load(dst)
    added = t.append_kicad_lib(
        "SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs"
    )
    assert added is True
    out = t.serialize()
    # the Table row and MySymbols row are byte-identical substrings still present
    assert '(lib (name "KiCad") (type "Table")' in out
    assert '(lib (name "MySymbols") (type "KiCad") (uri "/home/sadad/git/Hardware/libs")' in out
    # exactly one new row, nothing lost
    diffs = semantic_diff(before, out)
    assert all(d.startswith("ADDED") for d in diffs), diffs
    assert t.has_lib("SR-ICs")


def test_append_preserves_crlf_and_tabs(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs")
    out = t.serialize()
    # the new row sits on its own CRLF+TAB line like the existing rows
    assert '\r\n\t(lib (name "SR-ICs") (type "KiCad")' in out
    assert out.endswith(")\r\n") or out.endswith(")\n")


def test_append_is_idempotent(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    assert t.append_kicad_lib("SR-ICs", "u", "d") is True
    assert t.append_kicad_lib("SR-ICs", "u", "d") is False  # already present
    assert t.entries().count("SR-ICs") == 1


def test_new_empty_table_has_version_7(tmp_path):
    t = LibTable.new("sym_lib_table")
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs")
    out = t.serialize()
    assert "(version 7)" in out
    assert '(lib (name "SR-ICs") (type "KiCad")' in out
    assert t.entries() == ["SR-ICs"]


def test_fp_table_uri_points_at_pretty(fixtures_dir, tmp_path):
    dst = tmp_path / "fp-lib-table"
    shutil.copyfile(fixtures_dir / "fp-lib-table.sample", dst)
    t = LibTable.load(dst)
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/footprints/SR-ICs.pretty", "Stockroom ICs")
    out = t.serialize()
    assert '(uri "${SR_LIB}/footprints/SR-ICs.pretty")' in out
