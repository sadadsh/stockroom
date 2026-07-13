import pytest

from stockroom.sexp.document import SexpDocument

KICAD_FIXTURES = ["minimal.kicad_sym", "minimal.kicad_mod", "minimal.kicad_sch"]


@pytest.mark.parametrize("name", KICAD_FIXTURES)
def test_parse_then_serialize_is_byte_identical(fixtures_dir, name):
    with open(fixtures_dir / name, encoding="utf-8", newline="") as f:
        original = f.read()
    doc = SexpDocument.parse(original)
    assert doc.serialize() == original


@pytest.mark.parametrize("name", KICAD_FIXTURES)
def test_fixtures_use_crlf(fixtures_dir, name):
    raw = (fixtures_dir / name).read_bytes()
    assert b"\r\n" in raw, f"{name} must use CRLF to mirror KiCad output"
