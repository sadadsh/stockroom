"""Read/edit KiCad .kicad_mod footprints, focused on the 3D model link."""

from __future__ import annotations

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad


class Footprint:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "footprint":
            raise KiCadFileError("not a .kicad_mod file (missing footprint)")

    @classmethod
    def load(cls, path) -> "Footprint":
        return cls(SexpDocument.load(path))

    @property
    def name(self) -> str:
        return self._doc.root.children[1].value

    def set_name(self, name: str) -> None:
        """Rename the footprint (the first string token after `footprint`),
        byte-preserving everything else."""
        self._doc.root.children[1].set_value(name, quote=True)

    def _model_node(self):
        return self._doc.root.find("model")

    @property
    def model_path(self) -> str | None:
        node = self._model_node()
        return node.children[1].value if node else None

    def set_model_path(self, path: str) -> None:
        node = self._model_node()
        if node is not None:
            node.children[1].set_value(path, quote=True)
        else:
            block = (
                f"(model {quote_kicad(path)} "
                "(offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))"
            )
            self._doc.root.insert_child_text(block)

    def hide_field(self, name: str) -> bool:
        """Mark a footprint property (Reference, Value, ...) hidden by inserting
        `(hide yes)`, idempotently. Returns True if it changed anything. Used to
        produce a clean PREVIEW copy: a real board keeps its visible refdes, but the
        library preview should not splash REF** and the value across the pad art."""
        for prop in self._doc.root.find_all("property"):
            kids = prop.children
            if len(kids) >= 2 and kids[1].value == name:
                hide = prop.find("hide")
                if hide is not None:
                    if len(hide.children) >= 2 and hide.children[1].value != "yes":
                        hide.children[1].set_value("yes", quote=False)
                        return True
                    return False
                prop.insert_child_text("(hide yes)")
                return True
        return False

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)
