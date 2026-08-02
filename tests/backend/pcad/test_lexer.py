import pytest

from stockroom.pcad.errors import PcadLexError
from stockroom.pcad.lexer import Token, decode_source, tokenize


def test_lexer_preserves_windows_paths_and_skips_comments():
    tokens = tokenize('ACCEL_ASCII "C:\\Parts\\one.lia" ; ignored\n(x "a\\"b" value)')
    assert [(token.kind, token.value) for token in tokens] == [
        ("atom", "ACCEL_ASCII"),
        ("string", "C:\\Parts\\one.lia"),
        ("(", "("),
        ("atom", "x"),
        ("string", 'a"b'),
        ("atom", "value"),
        (")", ")"),
    ]
    assert tokens[2] == Token("(", "(", 41, 2, 1)


def test_legacy_cp1252_source_decodes_without_replacement_characters():
    assert decode_source(b"Copyright \xa9") == "Copyright ©"


def test_unterminated_string_fails_with_location():
    with pytest.raises(PcadLexError, match="unterminated string at line 1, column 4"):
        tokenize('(x "broken)')
