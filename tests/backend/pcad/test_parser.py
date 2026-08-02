import pytest

from stockroom.pcad import PcadParseError, parse_text


def test_parser_reads_signature_and_expression_forest_case_insensitively():
    document = parse_text(
        'ACCEL_ASCII "legacy.lia"\n'
        "(asciiHeader (asciiVersion 3 0) (fileUnits Mil))\n"
        '(library "Parts" (thing "one"))'
    )
    assert document.signature == "ACCEL_ASCII"
    assert document.declared_path == "legacy.lia"
    assert document.root("ASCIIHEADER").child("fileunits", required=True).arguments == ("Mil",)
    assert document.root("library").arguments == ("Parts",)


@pytest.mark.parametrize(
    "source, message",
    [
        ('UNKNOWN "x" (asciiHeader) (library "x")', "unsupported P-CAD signature"),
        ('ACCEL_ASCII x (asciiHeader) (library "x")', "declared path must be quoted"),
        ('ACCEL_ASCII "x" (asciiHeader) (library "x"', "unclosed list"),
        ('ACCEL_ASCII "x" (asciiHeader) (asciiHeader) (library "x")', "exactly one"),
    ],
)
def test_parser_rejects_malformed_or_ambiguous_documents(source: str, message: str):
    with pytest.raises(PcadParseError, match=message):
        parse_text(source)
