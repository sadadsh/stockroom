"""Byte-preserving s-expression document.

Parse builds a node tree whose leaves carry source spans. Edits are recorded
as (start, end, replacement) tuples and applied to the ORIGINAL text in reverse
order at serialize time, so untouched bytes are never rewritten.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.sexp.tokens import Token, tokenize_spans


def quote_kicad(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(text: str, tok: Token) -> str:
    raw = text[tok.start : tok.end]
    if tok.kind == "str":
        inner = raw[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return raw


class SexpNode:
    __slots__ = ("_doc", "_token", "_children", "_text", "_list_span")

    def __init__(self, doc, text, token=None, children=None):
        self._doc = doc
        self._text = text
        self._token = token  # set for leaves
        self._children = children  # set for lists
        self._list_span = None  # (open, close) byte span; set for list nodes

    @property
    def is_atom(self) -> bool:
        return self._token is not None

    @property
    def kind(self) -> str:
        return self._token.kind if self._token else "("

    @property
    def span(self) -> tuple[int, int]:
        if self._token:
            return (self._token.start, self._token.end)
        first, last = self._children_span()
        return (first, last)

    def _children_span(self) -> tuple[int, int]:
        # span of a list = from its own '(' to its ')'; stored on the list node
        return self._list_span

    @property
    def value(self) -> str:
        if not self._token:
            return ""
        return _unquote(self._text, self._token)

    @property
    def name(self) -> str | None:
        if self._token or not self._children:
            return None
        head = self._children[0]
        return head.value if head.is_atom else None

    @property
    def children(self) -> list["SexpNode"]:
        return list(self._children or [])

    def find(self, name: str) -> "SexpNode | None":
        for ch in self._children or []:
            if not ch.is_atom and ch.name == name:
                return ch
        return None

    def find_all(self, name: str) -> list["SexpNode"]:
        return [
            ch
            for ch in (self._children or [])
            if not ch.is_atom and ch.name == name
        ]

    def set_value(self, new: str, *, quote: bool) -> None:
        if not self._token:
            raise ValueError("set_value is only valid on a leaf node")
        replacement = quote_kicad(new) if quote else new
        self._doc.replace_span(self._token.start, self._token.end, replacement)


class SexpDocument:
    def __init__(self, text: str):
        self.text = text
        self._edits: list[tuple[int, int, str]] = []
        self.root = self._build()

    @classmethod
    def parse(cls, text: str) -> "SexpDocument":
        return cls(text)

    @classmethod
    def load(cls, path) -> "SexpDocument":
        text = Path(path).read_text(encoding="utf-8", newline="")
        return cls(text)

    def _build(self) -> SexpNode:
        toks = list(tokenize_spans(self.text))
        pos = 0

        def read() -> SexpNode:
            nonlocal pos
            tok = toks[pos]
            if tok.kind == "(":
                open_start = tok.start
                pos += 1
                kids: list[SexpNode] = []
                while toks[pos].kind != ")":
                    kids.append(read())
                close_end = toks[pos].end
                pos += 1
                node = SexpNode(self, self.text, children=kids)
                node._list_span = (open_start, close_end)
                return node
            pos += 1
            return SexpNode(self, self.text, token=tok)

        return read()

    def replace_span(self, start: int, end: int, replacement: str) -> None:
        self._edits.append((start, end, replacement))

    def serialize(self) -> str:
        text = self.text
        for start, end, replacement in sorted(self._edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
