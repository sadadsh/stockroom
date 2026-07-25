"""Read/edit KiCad .kicad_mod footprints, focused on the 3D model link."""

from __future__ import annotations

from dataclasses import dataclass

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad


@dataclass(frozen=True)
class ModelPlacement:
    """Where a footprint's 3D model sits relative to the footprint origin.

    KiCad's units, unconverted, because converting here would hide which frame a caller is in:
    `offset` is millimetres, `rotate` is DEGREES about x/y/z, `scale` is unitless. A viewer that
    ignores this draws the body at the origin unrotated, which is what Stockroom did - and it is
    silently wrong rather than visibly broken, since a centred part looks plausible either way.
    """

    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def is_identity(self) -> bool:
        return (
            self.offset == (0.0, 0.0, 0.0)
            and self.scale == (1.0, 1.0, 1.0)
            and self.rotate == (0.0, 0.0, 0.0)
        )


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

    @property
    def model_placement(self) -> "ModelPlacement | None":
        """The model's placement transform, or None when the footprint links no model at all.

        A `(model ...)` that OMITS a sub-block is not unknown - KiCad treats it as identity - so the
        missing parts default rather than returning None, which would make every caller invent the
        same default itself. Read-only: this never touches the document, so the byte-preserving
        guarantee holds.
        """
        node = self._model_node()
        if node is None:
            return None

        def xyz(key: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
            sub = node.find(key)
            if sub is None:
                return default
            triple = sub.find("xyz")
            if triple is None:
                return default
            # children[0] is the `xyz` token itself; the three numbers follow it.
            values = triple.children[1:4]
            if len(values) != 3:
                return default
            try:
                return (float(values[0].value), float(values[1].value), float(values[2].value))
            except (TypeError, ValueError):
                # A malformed number is not worth crashing a preview over, and guessing a
                # different default would misplace the body without saying so.
                return default

        return ModelPlacement(
            offset=xyz("offset", (0.0, 0.0, 0.0)),
            scale=xyz("scale", (1.0, 1.0, 1.0)),
            rotate=xyz("rotate", (0.0, 0.0, 0.0)),
        )

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

    def hide_reference_texts(self) -> bool:
        """Hide any `(fp_text ... "${REFERENCE}" | "REF**" ...)` node - the fab-layer
        designator KiCad duplicates ON TOP OF the Reference property. hide_field only
        touches `property` nodes, so without this the preview still splashes REF** over
        the pad art (the exact "not as clean as the old app" complaint). Returns True if
        it changed anything; idempotent."""
        changed = False
        for node in self._doc.root.find_all("fp_text"):
            if not any(
                getattr(k, "value", None) in ("${REFERENCE}", "REF**")
                for k in node.children
            ):
                continue
            hide = node.find("hide")
            if hide is not None:
                if len(hide.children) >= 2 and hide.children[1].value != "yes":
                    hide.children[1].set_value("yes", quote=False)
                    changed = True
            else:
                node.insert_child_text("(hide yes)")
                changed = True
        return changed

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)
