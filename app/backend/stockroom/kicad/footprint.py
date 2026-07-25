"""Read/edit KiCad .kicad_mod footprints, focused on the 3D model link."""

from __future__ import annotations

import math
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


@dataclass(frozen=True)
class Pad:
    """One pad of the land pattern, in KiCad's own units and frame.

    `at` is millimetres from the footprint origin and `rotation` is degrees; Y is left EXACTLY as
    KiCad stores it (+Y down on screen) rather than flipped here, so a caller always knows which
    frame it is in - the same reasoning as ModelPlacement.
    """

    number: str
    at: tuple[float, float]
    size: tuple[float, float]
    shape: str = "rect"
    rotation: float = 0.0
    # Hole diameter in mm for a through-hole pad, 0 for SMD. MEASURED: 44% of pads in the real
    # KiCad library are through-hole, and drawing them as solid copper with no hole is simply not
    # what was downloaded.
    drill: float = 0.0
    # "thru_hole" / "smd" / "np_thru_hole" - a non-plated hole has no copper at all.
    pad_type: str = "smd"


@dataclass(frozen=True)
class GraphicLine:
    """One drawn segment of the footprint - silkscreen outline, pin-1 marker, courtyard.

    Millimetres in KiCad's frame, like Pad. The LAYER is kept rather than filtered here, because
    what a viewer wants to draw differs by context: silkscreen is the human-readable outline,
    the courtyard is a keep-out, and a caller should decide which it needs.
    """

    start: tuple[float, float]
    end: tuple[float, float]
    layer: str
    width: float = 0.12


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
    def graphics(self) -> list["GraphicLine"]:
        """Every `fp_line` the footprint draws, with its layer - the silkscreen and courtyard that
        make a land pattern recognisable. Pads are NOT included; they come from `pads`."""
        out: list[GraphicLine] = []

        def _pt(node, key: str) -> tuple[float, float] | None:
            sub = node.find(key)
            if sub is None or len(sub.children) < 3:
                return None
            try:
                return (float(sub.children[1].value), float(sub.children[2].value))
            except (TypeError, ValueError):
                return None

        def _layer_width(node) -> tuple[str, float]:
            layer_node = node.find("layer")
            layer = (
                str(layer_node.children[1].value)
                if layer_node is not None and len(layer_node.children) > 1
                else ""
            )
            width = 0.12
            stroke = node.find("stroke")
            if stroke is not None:
                w = stroke.find("width")
                if w is not None and len(w.children) > 1:
                    try:
                        width = float(w.children[1].value)
                    except (TypeError, ValueError):
                        width = 0.12
            return layer, width

        # RECTANGLES - measured at 63% of real KiCad footprints, second only to fp_line, and
        # previously drawn as nothing at all. Emitted as four segments so every consumer needs
        # only ONE primitive: a caller that can draw a line can draw the whole land pattern.
        for node in self._doc.root.find_all("fp_rect"):
            a, b = _pt(node, "start"), _pt(node, "end")
            if a is None or b is None:
                continue
            layer, width = _layer_width(node)
            corners = [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])]
            for i in range(4):
                out.append(
                    GraphicLine(
                        start=corners[i], end=corners[(i + 1) % 4], layer=layer, width=width
                    )
                )

        # CIRCLES (10%) - KiCad stores a centre and a point ON the rim; approximated as a closed
        # polyline, which is what a renderer would tessellate it into anyway.
        for node in self._doc.root.find_all("fp_circle"):
            c, edge = _pt(node, "center"), _pt(node, "end")
            if c is None or edge is None:
                continue
            layer, width = _layer_width(node)
            r = ((edge[0] - c[0]) ** 2 + (edge[1] - c[1]) ** 2) ** 0.5
            if r <= 0:
                continue
            segments = 32
            prev = (c[0] + r, c[1])
            for i in range(1, segments + 1):
                ang = 2 * math.pi * i / segments
                cur = (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
                out.append(GraphicLine(start=prev, end=cur, layer=layer, width=width))
                prev = cur

        # POLYGONS (6%) - the pin-1 wedge on many parts. Closed, because KiCad implies closure.
        for node in self._doc.root.find_all("fp_poly"):
            poly = node.find("pts")
            if poly is None:
                continue
            points: list[tuple[float, float]] = []
            for xy in poly.find_all("xy"):
                if len(xy.children) < 3:
                    continue
                try:
                    points.append((float(xy.children[1].value), float(xy.children[2].value)))
                except (TypeError, ValueError):
                    continue
            if len(points) < 2:
                continue
            layer, width = _layer_width(node)
            for i in range(len(points)):
                out.append(
                    GraphicLine(
                        start=points[i],
                        end=points[(i + 1) % len(points)],
                        layer=layer,
                        width=width,
                    )
                )

        # ARCS (9% of real footprints). KiCad stores THREE POINTS on the curve (start/mid/end), not
        # a centre and angles, so the centre is solved as the circumcentre of that triangle. Three
        # collinear points have no circumcentre - that is a straight line, so it is emitted as one.
        for node in self._doc.root.find_all("fp_arc"):
            a, m, b = _pt(node, "start"), _pt(node, "mid"), _pt(node, "end")
            if a is None or m is None or b is None:
                continue
            layer, width = _layer_width(node)
            d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
            if abs(d) < 1e-12:
                out.append(GraphicLine(start=a, end=b, layer=layer, width=width))
                continue
            ux = (
                (a[0] ** 2 + a[1] ** 2) * (m[1] - b[1])
                + (m[0] ** 2 + m[1] ** 2) * (b[1] - a[1])
                + (b[0] ** 2 + b[1] ** 2) * (a[1] - m[1])
            ) / d
            uy = (
                (a[0] ** 2 + a[1] ** 2) * (b[0] - m[0])
                + (m[0] ** 2 + m[1] ** 2) * (a[0] - b[0])
                + (b[0] ** 2 + b[1] ** 2) * (m[0] - a[0])
            ) / d
            r = math.hypot(a[0] - ux, a[1] - uy)
            a0 = math.atan2(a[1] - uy, a[0] - ux)
            a1 = math.atan2(m[1] - uy, m[0] - ux)
            a2 = math.atan2(b[1] - uy, b[0] - ux)
            # walk start -> mid -> end so the arc goes the way KiCad drew it, not the short way
            def _norm(x: float) -> float:
                while x <= -math.pi:
                    x += 2 * math.pi
                while x > math.pi:
                    x -= 2 * math.pi
                return x

            sweep = _norm(a1 - a0) + _norm(a2 - a1)
            steps = max(6, int(abs(sweep) / (math.pi / 16)) + 1)
            prev = a
            for i in range(1, steps + 1):
                ang = a0 + sweep * (i / steps)
                cur = (ux + r * math.cos(ang), uy + r * math.sin(ang))
                out.append(GraphicLine(start=prev, end=cur, layer=layer, width=width))
                prev = cur

        for node in self._doc.root.find_all("fp_line"):

            def pt(key: str) -> tuple[float, float] | None:
                sub = node.find(key)
                if sub is None or len(sub.children) < 3:
                    return None
                try:
                    return (float(sub.children[1].value), float(sub.children[2].value))
                except (TypeError, ValueError):
                    return None

            start, end = pt("start"), pt("end")
            if start is None or end is None:
                continue
            layer_node = node.find("layer")
            layer = (
                str(layer_node.children[1].value)
                if layer_node is not None and len(layer_node.children) > 1
                else ""
            )
            width = 0.12
            stroke = node.find("stroke")
            if stroke is not None:
                w = stroke.find("width")
                if w is not None and len(w.children) > 1:
                    try:
                        width = float(w.children[1].value)
                    except (TypeError, ValueError):
                        width = 0.12
            out.append(GraphicLine(start=start, end=end, layer=layer, width=width))
        return out

    @property
    def pads(self) -> list["Pad"]:
        """Every pad in the land pattern, so a 3D view can draw what the body sits on.

        Each `(size ...)` is read from INSIDE its own pad node, never by scanning the file: a
        footprint also carries `(size ...)` inside text `(effects (font ...))`, and taking the
        first one in the document would silently mis-size every pad.
        """
        out: list[Pad] = []
        for node in self._doc.root.find_all("pad"):
            kids = node.children
            # (pad "<number>" <type> <shape> ...)
            number = kids[1].value if len(kids) > 1 else ""
            pad_type = kids[2].value if len(kids) > 2 else "smd"
            shape = kids[3].value if len(kids) > 3 else "rect"

            def pair(key: str, default: tuple[float, float]) -> tuple[float, float]:
                sub = node.find(key)
                if sub is None or len(sub.children) < 3:
                    return default
                try:
                    return (float(sub.children[1].value), float(sub.children[2].value))
                except (TypeError, ValueError):
                    return default

            at_node = node.find("at")
            rotation = 0.0
            if at_node is not None and len(at_node.children) >= 4:
                try:
                    rotation = float(at_node.children[3].value)
                except (TypeError, ValueError):
                    rotation = 0.0

            drill = 0.0
            drill_node = node.find("drill")
            if drill_node is not None and len(drill_node.children) > 1:
                try:
                    drill = float(drill_node.children[1].value)
                except (TypeError, ValueError):
                    drill = 0.0

            out.append(
                Pad(
                    number=str(number),
                    at=pair("at", (0.0, 0.0)),
                    size=pair("size", (0.0, 0.0)),
                    shape=str(shape),
                    rotation=rotation,
                    drill=drill,
                    pad_type=str(pad_type),
                )
            )
        return out

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
