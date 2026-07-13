import pytest

from stockroom.sexp.tokens import Token, tokenize_spans


def toks(text):
    return list(tokenize_spans(text))


def test_parens_and_atoms_have_exact_spans():
    text = '(a bc)'
    result = toks(text)
    assert result == [
        Token("(", 0, 1),
        Token("atom", 1, 2),
        Token("atom", 3, 5),
        Token(")", 5, 6),
    ]


def test_string_span_includes_quotes():
    text = '(x "hi there")'
    result = toks(text)
    str_tok = [t for t in result if t.kind == "str"][0]
    assert text[str_tok.start : str_tok.end] == '"hi there"'


def test_escaped_quote_inside_string():
    text = r'("a\"b")'
    str_tok = [t for t in toks(text) if t.kind == "str"][0]
    assert text[str_tok.start : str_tok.end] == r'"a\"b"'


def test_crlf_and_tabs_are_whitespace():
    text = '(\r\n\t(y 1)\r\n)'
    result = toks(text)
    assert [t.kind for t in result] == ["(", "(", "atom", "atom", ")", ")"]


def test_unterminated_string_raises():
    with pytest.raises(ValueError):
        list(tokenize_spans('(x "abc'))


def test_string_ending_in_escape_raises():
    with pytest.raises(ValueError):
        list(tokenize_spans('("a\\'))
