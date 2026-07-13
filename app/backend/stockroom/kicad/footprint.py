"""Read/edit KiCad .kicad_mod footprints, focused on the 3D model link."""

from __future__ import annotations

from pathlib import Path

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

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
