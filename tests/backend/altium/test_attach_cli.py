import pytest

from stockroom.altium.attach import _parse_args


def test_parse_args_loose_pair(tmp_path):
    a = tmp_path / "x.SchLib"
    b = tmp_path / "x.PcbLib"
    a.write_text("s")
    b.write_text("p")
    part_id, sources = _parse_args(["bq24074rgtt", str(a), str(b)])
    assert part_id == "bq24074rgtt"
    assert [s.name for s in sources] == ["x.SchLib", "x.PcbLib"]


def test_parse_args_single_intlib(tmp_path):
    f = tmp_path / "x.IntLib"
    f.write_text("i")
    part_id, sources = _parse_args(["bq24074rgtt", str(f)])
    assert part_id == "bq24074rgtt" and len(sources) == 1


def test_parse_args_missing_file_exits(tmp_path):
    with pytest.raises(SystemExit):
        _parse_args(["p1", str(tmp_path / "nope.IntLib")])


def test_parse_args_requires_part_id_and_a_file():
    with pytest.raises(SystemExit):
        _parse_args(["p1"])  # no source files
    with pytest.raises(SystemExit):
        _parse_args([])  # nothing
