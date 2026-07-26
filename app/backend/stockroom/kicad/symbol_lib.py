"""Read/edit KiCad .kicad_sym symbol libraries with byte preservation."""

from __future__ import annotations

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad


class Symbol:
    def __init__(self, node: SexpNode):
        self._node = node

    @property
    def name(self) -> str:
        return self._node.children[1].value

    def _property_node(self, name: str) -> SexpNode | None:
        for prop in self._node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3 and kids[1].value == name:
                return prop
        return None

    def get_property(self, name: str) -> str | None:
        prop = self._property_node(name)
        return prop.children[2].value if prop else None

    def set_property(self, name: str, value: str, hide: bool = False) -> None:
        """Set a property value. hide=True marks it hidden (and heals an existing
        visible one): metadata fields (MPN, Purchase, ...) must never render on a
        schematic or drown the symbol preview in text."""
        prop = self._property_node(name)
        if prop is not None:
            prop.children[2].set_value(value, quote=True)
            if hide:
                self._ensure_hidden(prop)
        else:
            effects = " (effects (hide yes))" if hide else ""
            self._node.insert_child_text(
                f"(property {quote_kicad(name)} {quote_kicad(value)} (at 0 0 0){effects})"
            )

    def property_hidden(self, name: str) -> bool | None:
        """True/False for an existing property's hidden state, None when absent."""
        prop = self._property_node(name)
        if prop is None:
            return None
        effects = prop.find("effects")
        if effects is None:
            return False
        hide_node = effects.find("hide")
        if hide_node is None:
            return False
        return len(hide_node.children) >= 2 and hide_node.children[1].value == "yes"

    @staticmethod
    def _ensure_hidden(prop: SexpNode) -> None:
        effects = prop.find("effects")
        if effects is None:
            prop.insert_child_text("(effects (hide yes))")
            return
        hide_node = effects.find("hide")
        if hide_node is None:
            effects.insert_child_text("(hide yes)")
        elif len(hide_node.children) >= 2 and hide_node.children[1].value != "yes":
            hide_node.children[1].set_value("yes", quote=False)

    def hide_all_properties(self) -> None:
        """Hide EVERY property field (Reference, Value, Footprint, Datasheet, MPN, ...) so a
        preview render shows the clean symbol body + pins + pin names/numbers, not the fields
        splashed and overlapping into a smudge over it. Pin names/numbers are pin data, not
        properties, so they are left intact. The source lib is only touched on a rendering copy."""
        for prop in self._node.find_all("property"):
            self._ensure_hidden(prop)


class SymbolLib:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "kicad_symbol_lib":
            raise KiCadFileError("not a .kicad_sym file (missing kicad_symbol_lib)")

    @classmethod
    def load(cls, path) -> "SymbolLib":
        return cls(SexpDocument.load(path))

    @property
    def version(self) -> str:
        node = self._doc.root.find("version")
        return node.children[1].value if node else ""

    @property
    def symbol_names(self) -> list[str]:
        return [s.children[1].value for s in self._doc.root.find_all("symbol")]

    def get_symbol(self, name: str) -> Symbol:
        for s in self._doc.root.find_all("symbol"):
            if s.children[1].value == name:
                return Symbol(s)
        raise KiCadFileError(f"symbol not found: {name}")

    def insert_symbol(self, symbol_sexp: str) -> None:
        """Append a complete `(symbol ...)` node, byte-preserving the rest of the
        library. The caller supplies the full s-expression text of the node."""
        self._doc.root.insert_child_text(symbol_sexp)

    def remove_symbol(self, name: str) -> None:
        """Remove the named `(symbol ...)` node, byte-preserving the rest."""
        for s in self._doc.root.find_all("symbol"):
            if s.children[1].value == name:
                self._doc.root.remove_child(s)
                return
        raise KiCadFileError(f"symbol not found: {name}")

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)
