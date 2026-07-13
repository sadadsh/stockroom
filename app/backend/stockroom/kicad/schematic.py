"""Read KiCad .kicad_sch schematics and rewrite symbol instances (for audit)."""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad


class SymbolInstance:
    def __init__(self, node: SexpNode):
        self._node = node

    def _property_node(self, name: str) -> SexpNode | None:
        for prop in self._node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3 and kids[1].value == name:
                return prop
        return None

    @property
    def lib_id(self) -> str:
        node = self._node.find("lib_id")
        return node.children[1].value if node else ""

    @property
    def reference(self) -> str:
        return self.get_property("Reference") or ""

    @property
    def value(self) -> str:
        return self.get_property("Value") or ""

    def get_property(self, name: str) -> str | None:
        prop = self._property_node(name)
        return prop.children[2].value if prop else None

    def set_property(self, name: str, value: str) -> None:
        prop = self._property_node(name)
        if prop is not None:
            prop.children[2].set_value(value, quote=True)
        else:
            self._node.insert_child_text(
                f"(property {quote_kicad(name)} {quote_kicad(value)} (at 0 0 0))"
            )

    def set_lib_id(self, lib_id: str) -> None:
        node = self._node.find("lib_id")
        if node is None:
            raise KiCadFileError("instance has no lib_id")
        node.children[1].set_value(lib_id, quote=True)


class Schematic:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "kicad_sch":
            raise KiCadFileError("not a .kicad_sch file (missing kicad_sch)")

    @classmethod
    def load(cls, path) -> "Schematic":
        return cls(SexpDocument.load(path))

    @property
    def instances(self) -> list[SymbolInstance]:
        out = []
        for node in self._doc.root.find_all("symbol"):
            if node.find("lib_id") is not None:
                out.append(SymbolInstance(node))
        return out

    def instance_by_reference(self, ref: str) -> SymbolInstance:
        for inst in self.instances:
            if inst.reference == ref:
                return inst
        raise KiCadFileError(f"no instance with reference {ref}")

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
