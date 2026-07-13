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

    def _indent_before(self, index: int) -> str:
        """Whitespace run (including a leading newline) before child `index`,
        or empty string if the child is not newline-prefixed. Captures the full
        CRLF pair so inserting/removing on a Windows/KiCad file keeps CRLF."""
        child = self._children[index]
        start = child.span[0]
        text = self._text
        j = start
        while j > 0 and text[j - 1] in " \t":
            j -= 1
        if j > 0 and text[j - 1] == "\n":
            nl = j - 1
            if nl > 0 and text[nl - 1] == "\r":
                nl -= 1  # include the \r of a \r\n pair
            return text[nl:start]
        if j > 0 and text[j - 1] == "\r":
            return text[j - 1 : start]  # lone CR (old-Mac), defensive
        return ""

    def insert_after(self, child: "SexpNode", sexp_text: str) -> None:
        if self._children is None:
            raise ValueError("insert_after is only valid on a list node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        pos = child.span[1]
        if indent:
            self._doc.replace_span(pos, pos, f"{indent}{sexp_text}")
        else:
            self._doc.replace_span(pos, pos, f" {sexp_text}")

    def insert_child_text(self, sexp_text: str) -> None:
        if self._children is None:
            raise ValueError("insert_child_text is only valid on a list node")
        if self._children:
            last = self._children[-1]
            self.insert_after(last, sexp_text)
            return
        # empty list: insert right before ')'
        close = self._list_span[1] - 1
        self._doc.replace_span(close, close, sexp_text)

    def remove_child(self, child: "SexpNode") -> None:
        if self._children is None:
            raise ValueError("remove_child is only valid on a list node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        start = child.span[0] - len(indent) if indent else child.span[0]
        self._doc.replace_span(start, child.span[1], "")


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
        # newline="" disables newline translation so CRLF is read back exactly.
        # (Path.read_text does not accept newline on Python 3.12, so use open().)
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
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
        # Last write wins for an identical span, so re-editing the same token
        # supersedes the prior edit instead of splicing both against the
        # original coordinates (which would corrupt the output).
        self._edits = [e for e in self._edits if not (e[0] == start and e[1] == end)]
        self._edits.append((start, end, replacement))

    def serialize(self) -> str:
        text = self.text
        # Apply edits from the highest start offset down so earlier offsets stay
        # valid. Spans are distinct leaf tokens (deduped in replace_span), so
        # sorting by start alone is unambiguous.
        for start, end, replacement in sorted(self._edits, key=lambda e: e[0], reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
