"""Bounded lexer for ACCEL/P-CAD ASCII library files.

P-CAD's format resembles an s-expression, but it has a two-token file
signature before the expression forest and supports semicolon comments.  A
dedicated lexer avoids weakening the byte-preserving KiCad parser with a
different grammar.
"""

from __future__ import annotations

from dataclasses import dataclass

from stockroom.pcad.errors import PcadLexError

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_STRING_LENGTH = 1024 * 1024
MAX_TOKENS = 2_000_000


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    offset: int
    line: int
    column: int


def decode_source(data: bytes) -> str:
    """Decode a legacy library without losing ordinary Windows characters."""
    if len(data) > MAX_SOURCE_BYTES:
        raise PcadLexError(f"P-CAD source exceeds {MAX_SOURCE_BYTES} bytes")
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PcadLexError("invalid UTF-8 BOM source") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def tokenize(text: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1
    length = len(text)

    def advance(character: str) -> None:
        nonlocal line, column
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1

    def append(kind: str, value: str, offset: int, token_line: int, token_column: int) -> None:
        tokens.append(Token(kind, value, offset, token_line, token_column))
        if len(tokens) > MAX_TOKENS:
            raise PcadLexError(f"P-CAD source exceeds {MAX_TOKENS} tokens")

    while index < length:
        character = text[index]
        if character.isspace():
            advance(character)
            index += 1
            continue
        if character == ";":
            while index < length and text[index] not in "\r\n":
                advance(text[index])
                index += 1
            continue

        token_offset = index
        token_line = line
        token_column = column
        if character in "()":
            append(character, character, token_offset, token_line, token_column)
            advance(character)
            index += 1
            continue
        if character == '"':
            advance(character)
            index += 1
            value: list[str] = []
            while index < length:
                character = text[index]
                if character == '"':
                    advance(character)
                    index += 1
                    append("string", "".join(value), token_offset, token_line, token_column)
                    break
                if character == "\\" and index + 1 < length:
                    following = text[index + 1]
                    if following in {'"', "\\"}:
                        value.append(following)
                        advance(character)
                        advance(following)
                        index += 2
                        continue
                value.append(character)
                if len(value) > MAX_STRING_LENGTH:
                    raise PcadLexError(
                        f"string at line {token_line}, column {token_column} is too long"
                    )
                advance(character)
                index += 1
            else:
                raise PcadLexError(
                    f"unterminated string at line {token_line}, column {token_column}"
                )
            continue

        value_start = index
        while index < length:
            character = text[index]
            if character.isspace() or character in "();":
                break
            if character == '"':
                raise PcadLexError(f"unexpected quote at line {line}, column {column}")
            advance(character)
            index += 1
        value = text[value_start:index]
        if not value:
            raise PcadLexError(f"unexpected character at line {line}, column {column}")
        append("atom", value, token_offset, token_line, token_column)

    return tuple(tokens)
