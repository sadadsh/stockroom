"""Byte-preserving s-expression document.

Parse builds a node tree whose leaves carry source spans. Edits are recorded
as (start, end, replacement, seq) tuples and applied to the ORIGINAL text from
the highest offset down at serialize time, so untouched bytes are never
rewritten. A replacement has start < end (deduped by span, last write wins); an
insertion has start == end (never deduped, ordered by seq so multiple inserts at
one anchor stack in insertion order).
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
    __slots__ = ("_doc", "_token", "_children", "_text", "_list_span", "_value_override")

    def __init__(self, doc, text, token=None, children=None):
        self._doc = doc
        self._text = text
        self._token = token  # set for leaves
        self._children = children  # set for lists
        self._list_span = None  # (open, close) byte span; set for list nodes
        self._value_override = None  # reflects a pending set_value for read-after-write

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
        if self._value_override is not None:
            return self._value_override  # a pending set_value is visible to reads
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
        self._value_override = new  # so .value reflects the edit before serialize

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
        if child._doc is not self._doc:
            raise ValueError("cannot anchor an insert on a freshly inserted node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        pos = child.span[1]
        self._doc.insert_span(pos, f"{indent}{sexp_text}" if indent else f" {sexp_text}")
        # Attach a readable node so find/find_all/value see the insert. It parses
        # into its own mini-document, so its leaves read from the fragment text.
        # A freshly inserted node is read-only this session; re-editing its value
        # needs a reload (its spans point into the fragment, not the main text).
        self._children.insert(idx + 1, SexpDocument.parse(sexp_text).root)

    def insert_child_text(self, sexp_text: str) -> None:
        if self._children is None:
            raise ValueError("insert_child_text is only valid on a list node")
        # Anchor on the last ORIGINAL child (skip nodes inserted this session, whose
        # spans point into their own fragment text, not the parent). This keeps the
        # insert offset valid even after prior inserts on the same node.
        anchor = None
        for ch in reversed(self._children):
            if ch._doc is self._doc:
                anchor = ch
                break
        if anchor is not None:
            idx = self._children.index(anchor)
            indent = self._indent_before(idx)
            pos = anchor.span[1]
            self._doc.insert_span(pos, f"{indent}{sexp_text}" if indent else f" {sexp_text}")
        else:
            # no original child: insert right before ')'
            close = self._list_span[1] - 1
            self._doc.insert_span(close, sexp_text)
        self._children.append(SexpDocument.parse(sexp_text).root)

    def remove_child(self, child: "SexpNode") -> None:
        if self._children is None:
            raise ValueError("remove_child is only valid on a list node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        start = child.span[0] - len(indent) if indent else child.span[0]
        self._doc.replace_span(start, child.span[1], "")
        self._children.pop(idx)  # so find/find_all no longer see the removed child


class SexpDocument:
    def __init__(self, text: str):
        self.text = text
        # each edit is (start, end, replacement, seq). start == end is a zero-width
        # insertion (ordered, never deduped); start < end is a replacement of an
        # existing span (deduped by span, last write wins). seq preserves the order
        # of multiple insertions at the same anchor.
        self._edits: list[tuple[int, int, str, int]] = []
        self._seq = 0
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
        # Replace an existing span (start < end). Last write wins for the same span
        # so re-editing a token supersedes the prior edit instead of splicing both.
        if start != end:
            self._edits = [e for e in self._edits if not (e[0] == start and e[1] == end)]
        self._edits.append((start, end, replacement, self._seq))
        self._seq += 1

    def insert_span(self, pos: int, text: str) -> None:
        # Zero-width insertion at a real byte offset in self.text. Never deduped;
        # multiple insertions at the same anchor keep their order via seq. Callers
        # must anchor on original text (never on an inserted node); this guard
        # fails loud if a future caller passes a fragment-relative offset.
        if not 0 <= pos <= len(self.text):
            raise ValueError(f"insert offset {pos} out of range 0..{len(self.text)}")
        self._edits.append((pos, pos, text, self._seq))
        self._seq += 1

    def serialize(self) -> str:
        text = self.text
        # Apply from the highest start down so earlier offsets stay valid. For edits
        # at the same start (insertions stacked at one anchor), apply the highest seq
        # first so the earliest-inserted text ends up first in the output.
        for start, end, replacement, _seq in sorted(
            self._edits, key=lambda e: (e[0], e[3]), reverse=True
        ):
            text = text[:start] + replacement + text[end:]
        return text

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
