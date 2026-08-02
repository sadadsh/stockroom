"""Parser for the bounded P-CAD ASCII expression forest."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from stockroom.pcad.errors import PcadParseError
from stockroom.pcad.lexer import Token, decode_source, tokenize

MAX_DEPTH = 256
SUPPORTED_SIGNATURES = frozenset({"accel_ascii", "pcad_ascii", "tangopro_ascii"})


@dataclass(frozen=True, slots=True)
class Atom:
    value: str
    quoted: bool
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Node:
    items: tuple[Atom | "Node", ...]
    line: int
    column: int

    @property
    def name(self) -> str:
        if not self.items or not isinstance(self.items[0], Atom):
            raise PcadParseError(f"list at line {self.line} has no atom name")
        return self.items[0].value

    @property
    def arguments(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.items[1:] if isinstance(item, Atom))

    def children_named(self, name: str) -> tuple["Node", ...]:
        folded = name.casefold()
        return tuple(
            item
            for item in self.items[1:]
            if isinstance(item, Node) and item.name.casefold() == folded
        )

    def child(self, name: str, *, required: bool = False) -> "Node | None":
        matches = self.children_named(name)
        if len(matches) > 1:
            raise PcadParseError(f"duplicate {name!r} in {self.name!r} at line {self.line}")
        if not matches:
            if required:
                raise PcadParseError(f"missing {name!r} in {self.name!r} at line {self.line}")
            return None
        return matches[0]


@dataclass(frozen=True, slots=True)
class Document:
    signature: str
    declared_path: str
    roots: tuple[Node, ...]
    source_sha256: str

    def roots_named(self, name: str) -> tuple[Node, ...]:
        folded = name.casefold()
        return tuple(root for root in self.roots if root.name.casefold() == folded)

    def root(self, name: str) -> Node:
        matches = self.roots_named(name)
        if len(matches) != 1:
            raise PcadParseError(f"expected exactly one {name!r}, found {len(matches)}")
        return matches[0]


def _atom(token: Token) -> Atom:
    if token.kind not in {"atom", "string"}:
        raise PcadParseError(f"expected atom at line {token.line}, column {token.column}")
    return Atom(token.value, token.kind == "string", token.line, token.column)


def _parse_node(tokens: tuple[Token, ...], start: int, depth: int) -> tuple[Node, int]:
    opening = tokens[start]
    if depth > MAX_DEPTH:
        raise PcadParseError(f"P-CAD nesting exceeds {MAX_DEPTH} levels")
    items: list[Atom | Node] = []
    index = start + 1
    while index < len(tokens):
        token = tokens[index]
        if token.kind == ")":
            if not items or not isinstance(items[0], Atom):
                raise PcadParseError(
                    f"empty or unnamed list at line {opening.line}, column {opening.column}"
                )
            return Node(tuple(items), opening.line, opening.column), index + 1
        if token.kind == "(":
            child, index = _parse_node(tokens, index, depth + 1)
            items.append(child)
            continue
        items.append(_atom(token))
        index += 1
    raise PcadParseError(f"unclosed list at line {opening.line}, column {opening.column}")


def parse_bytes(data: bytes) -> Document:
    text = decode_source(data)
    tokens = tokenize(text)
    if len(tokens) < 4:
        raise PcadParseError("P-CAD source is missing its signature or document roots")
    signature_token, path_token = tokens[:2]
    signature = _atom(signature_token).value
    if signature.casefold() not in SUPPORTED_SIGNATURES:
        raise PcadParseError(f"unsupported P-CAD signature {signature!r}")
    if path_token.kind != "string":
        raise PcadParseError("P-CAD declared path must be quoted")

    roots: list[Node] = []
    index = 2
    while index < len(tokens):
        if tokens[index].kind != "(":
            token = tokens[index]
            raise PcadParseError(
                f"expected top-level list at line {token.line}, column {token.column}"
            )
        node, index = _parse_node(tokens, index, 1)
        roots.append(node)
    document = Document(signature, path_token.value, tuple(roots), sha256(data).hexdigest())
    document.root("asciiHeader")
    document.root("library")
    return document


def parse_text(text: str) -> Document:
    return parse_bytes(text.encode("utf-8"))


def parse_file(path: str | Path) -> Document:
    return parse_bytes(Path(path).read_bytes())
