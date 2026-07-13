"""Span-recording tokenizer for KiCad s-expressions.

Every token carries its exact [start, end) slice into the source text, so an
editor can splice replacements without re-serializing anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Token:
    kind: str  # "(", ")", "str", or "atom"
    start: int
    end: int


def tokenize_spans(text: str) -> Iterator[Token]:
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield Token(c, i, i + 1)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            yield Token("str", i, j + 1)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield Token("atom", i, j)
            i = j
