"""Byte-preserving reader/writer for KiCad global sym-lib-table / fp-lib-table.

These are s-expression files (format version 7). Stockroom appends its own
(type "KiCad") rows with ${SR_LIB} URIs and never disturbs existing rows, in
particular the V10 (type "Table") stock-library chain row (verified against the
owner's real KiCad 10 tables). All edits go through the M1 span-preserving
layer, so CRLF, tabs, and every untouched row survive exactly.
"""

from __future__ import annotations

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad

_KINDS = ("sym_lib_table", "fp_lib_table")


class LibTable:
    def __init__(self, doc: SexpDocument, kind: str):
        if kind not in _KINDS:
            raise ValueError(f"unknown lib-table kind: {kind}")
        if doc.root.name != kind:
            raise KiCadFileError(f"not a {kind} (root is {doc.root.name!r})")
        self._doc = doc
        self.kind = kind

    @classmethod
    def load(cls, path) -> "LibTable":
        doc = SexpDocument.load(path)
        return cls(doc, doc.root.name)

    @classmethod
    def new(cls, kind: str) -> "LibTable":
        if kind not in _KINDS:
            raise ValueError(f"unknown lib-table kind: {kind}")
        text = f"({kind}\r\n\t(version 7)\r\n)\r\n"
        return cls(SexpDocument.parse(text), kind)

    def _lib_nodes(self):
        return self._doc.root.find_all("lib")

    def _row_name(self, lib_node) -> str:
        name = lib_node.find("name")
        return name.children[1].value if name else ""

    def entries(self) -> list[str]:
        return [self._row_name(n) for n in self._lib_nodes()]

    def has_lib(self, name: str) -> bool:
        return name in self.entries()

    def append_kicad_lib(self, name: str, uri: str, descr: str = "") -> bool:
        if self.has_lib(name):
            return False
        row = (
            f"(lib (name {quote_kicad(name)}) (type \"KiCad\") "
            f"(uri {quote_kicad(uri)}) (options \"\") (descr {quote_kicad(descr)}))"
        )
        # insert_child_text anchors on the last original child (a lib row, or the
        # (version 7) node in a fresh table) and replicates its CRLF+TAB indent,
        # so the new row lands on its own correctly-indented line.
        self._doc.root.insert_child_text(row)
        return True

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)
