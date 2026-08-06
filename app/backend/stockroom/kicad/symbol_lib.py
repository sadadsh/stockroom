"""Read/edit KiCad .kicad_sym symbol libraries with byte preservation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad

# How finely an arc is walked when it is emitted as a polyline. One segment per ~11 degrees,
# which is below the width of the stroke that draws it at any preview scale a person reads.
_ARC_STEP = math.pi / 16


@dataclass(frozen=True)
class SymbolPin:
    """One terminal of a symbol, in KiCad's own units and frame.

    `at` is the CONNECTION point in millimetres and `angle` is the direction the pin body runs
    from it, both exactly as KiCad stores them (+Y up in a schematic, unlike a footprint). They
    are left unconverted for the same reason `kicad.footprint.Pad` leaves its frame alone: a
    caller always knows which frame it is in.

    `electrical` is the pin's electrical type (`input`, `power_in`, `passive`, ...) and is a
    property of the SYMBOL, not of any application that can read it. It is carried separately
    from the name and the number because a person inspecting a symbol is asking three different
    questions - what is this pin called, which package terminal is it, and what does it do -
    and answering them as one string is what forced the preview to draw all three or none.
    """

    number: str = ""
    name: str = ""
    electrical: str = "unspecified"
    style: str = "line"
    at: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    length: float = 2.54
    hidden: bool = False

    @property
    def body_end(self) -> tuple[float, float]:
        """Where the pin meets the symbol body. The far end of the drawn line."""
        radians = math.radians(self.angle)
        return (
            self.at[0] + self.length * math.cos(radians),
            self.at[1] + self.length * math.sin(radians),
        )


@dataclass(frozen=True)
class SymbolGraphic:
    """One drawn shape of the symbol body.

    Rectangles and circles keep their own identity rather than being flattened to points: they
    are what the file says, and a renderer that has both primitives should not be handed a
    tessellation of them. Arcs ARE flattened, because a three-point arc has no direct SVG
    equivalent and every consumer would otherwise solve the same circumcentre.
    """

    kind: str = "polyline"
    points: tuple[tuple[float, float], ...] = ()
    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    width: float = 0.0
    fill: str = "none"
    closed: bool = False


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

    def hide_redundant_pin_names(self) -> bool:
        """Hide pin names in a rendering copy when every name repeats its number.

        Some provider KiCad exports write pin name ``"1"`` and pin number ``"1"`` even when
        the sibling P-CAD source explicitly hides pin names. Rendering both produces ``1 1``
        around every terminal and makes a correct symbol look corrupt. This preview-only cleanup
        changes no library evidence and leaves meaningful names (GND, VCC, ...) untouched.
        """
        pins = [node for node in self._node.iter_descendants() if node.name == "pin"]
        pairs: list[tuple[str, str]] = []
        for pin in pins:
            name = pin.find("name")
            number = pin.find("number")
            if name is None or number is None or len(name.children) < 2 or len(number.children) < 2:
                continue
            pairs.append((name.children[1].value, number.children[1].value))
        if not pairs or any(not name or name != number for name, number in pairs):
            return False
        pin_names = self._node.find("pin_names")
        if pin_names is None:
            self._node.insert_child_text("(pin_names (hide yes))")
            return True
        hide = pin_names.find("hide")
        if hide is None:
            pin_names.insert_child_text("(hide yes)")
        elif len(hide.children) >= 2 and hide.children[1].value != "yes":
            hide.children[1].set_value("yes", quote=False)
        return True

    # ------------------------------------------------------------- geometry
    #
    # A symbol's pins and body are read here rather than inferred from a rendered SVG, because
    # the questions the CAD column has to answer about a symbol are questions about the DATA:
    # how many pins there are, whether two share a number, whether a name is meaningful, what
    # each pin's electrical type is. None of those survive rasterisation, and a preview that
    # cannot answer them can only show a picture and hope.

    @staticmethod
    def _number(node: SexpNode | None, index: int, default: float) -> float:
        if node is None or len(node.children) <= index:
            return default
        try:
            return float(node.children[index].value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _point(cls, node: SexpNode | None) -> tuple[float, float] | None:
        if node is None or len(node.children) < 3:
            return None
        try:
            return (float(node.children[1].value), float(node.children[2].value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hidden(node: SexpNode | None) -> bool:
        if node is None:
            return False
        hide = node.find("hide")
        if hide is not None:
            # KiCad 7+ writes `(hide yes)`; a lone `(hide)` block still means hidden.
            return len(hide.children) < 2 or hide.children[1].value == "yes"
        # KiCad 6 wrote a BARE `hide` token inside the pin rather than a block, and a library
        # exported by an older provider tool is still a library a person owns. Reading only the
        # block form would draw a deliberately hidden power pin on every such symbol.
        return any(child.is_atom and child.value == "hide" for child in node.children)

    @classmethod
    def _stroke_width(cls, node: SexpNode) -> float:
        stroke = node.find("stroke")
        return cls._number(stroke.find("width") if stroke else None, 1, 0.0)

    @staticmethod
    def _fill(node: SexpNode) -> str:
        fill = node.find("fill")
        kind = fill.find("type") if fill is not None else None
        return (
            str(kind.children[1].value) if kind is not None and len(kind.children) > 1 else "none"
        )

    def _body_units(self) -> list[SexpNode]:
        """The drawing units this preview shows: the common unit and the first real one.

        A multi-unit symbol (a quad op-amp, a relay) draws one gate at a time, and stacking
        every unit on top of the others produces a smear that is not any of them. Unit 0 is
        KiCad's "common to all units" and is always included.
        """
        units: list[SexpNode] = []
        chosen: int | None = None
        for child in self._node.find_all("symbol"):
            name = str(child.children[1].value) if len(child.children) > 1 else ""
            parts = name.rsplit("_", 2)
            try:
                unit = int(parts[-2]) if len(parts) == 3 else 0
            except ValueError:
                unit = 0
            if unit == 0:
                units.append(child)
                continue
            if chosen is None:
                chosen = unit
            if unit == chosen:
                units.append(child)
        return units

    @property
    def pins(self) -> list[SymbolPin]:
        """Every pin of the shown unit, with its number, name and electrical type."""
        out: list[SymbolPin] = []
        for unit in self._body_units():
            for node in unit.find_all("pin"):
                kids = node.children
                at = node.find("at")
                name = node.find("name")
                number = node.find("number")
                out.append(
                    SymbolPin(
                        number=(
                            str(number.children[1].value)
                            if number is not None and len(number.children) > 1
                            else ""
                        ),
                        name=(
                            str(name.children[1].value)
                            if name is not None and len(name.children) > 1
                            else ""
                        ),
                        electrical=str(kids[1].value) if len(kids) > 1 else "unspecified",
                        style=str(kids[2].value) if len(kids) > 2 else "line",
                        at=self._point(at) or (0.0, 0.0),
                        angle=self._number(at, 3, 0.0),
                        length=self._number(node.find("length"), 1, 2.54),
                        hidden=self._hidden(node),
                    )
                )
        return out

    @property
    def graphics(self) -> list[SymbolGraphic]:
        """The body of the shown unit: rectangles, polylines, circles and flattened arcs."""
        out: list[SymbolGraphic] = []
        for unit in self._body_units():
            for node in unit.find_all("rectangle"):
                start, end = self._point(node.find("start")), self._point(node.find("end"))
                if start is None or end is None:
                    continue
                out.append(
                    SymbolGraphic(
                        kind="rectangle",
                        points=(start, end),
                        width=self._stroke_width(node),
                        fill=self._fill(node),
                    )
                )
            for node in unit.find_all("circle"):
                center = self._point(node.find("center"))
                radius = self._number(node.find("radius"), 1, 0.0)
                if center is None or radius <= 0:
                    continue
                out.append(
                    SymbolGraphic(
                        kind="circle",
                        center=center,
                        radius=radius,
                        width=self._stroke_width(node),
                        fill=self._fill(node),
                    )
                )
            for node in unit.find_all("polyline"):
                pts = node.find("pts")
                points = tuple(
                    point
                    for point in (self._point(xy) for xy in (pts.find_all("xy") if pts else []))
                    if point is not None
                )
                if len(points) < 2:
                    continue
                out.append(
                    SymbolGraphic(
                        kind="polyline",
                        points=points,
                        width=self._stroke_width(node),
                        fill=self._fill(node),
                        closed=points[0] == points[-1],
                    )
                )
            for node in unit.find_all("arc"):
                arc = self._arc_points(node)
                if arc is None:
                    continue
                out.append(
                    SymbolGraphic(
                        kind="polyline",
                        points=arc,
                        width=self._stroke_width(node),
                        fill=self._fill(node),
                    )
                )
        return out

    @classmethod
    def _arc_points(cls, node: SexpNode) -> tuple[tuple[float, float], ...] | None:
        """A three-point KiCad arc walked start -> mid -> end, so it curves the way it was drawn.

        Three collinear points have no circumcentre; that is a straight line and is emitted as
        one rather than being dropped, because a symbol that draws a degenerate arc still draws
        something.
        """
        a, m, b = (
            cls._point(node.find("start")),
            cls._point(node.find("mid")),
            cls._point(node.find("end")),
        )
        if a is None or m is None or b is None:
            return None
        d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
        if abs(d) < 1e-12:
            return (a, b)
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
        radius = math.hypot(a[0] - ux, a[1] - uy)

        def normalize(value: float) -> float:
            while value <= -math.pi:
                value += 2 * math.pi
            while value > math.pi:
                value -= 2 * math.pi
            return value

        a0 = math.atan2(a[1] - uy, a[0] - ux)
        sweep = normalize(math.atan2(m[1] - uy, m[0] - ux) - a0) + normalize(
            math.atan2(b[1] - uy, b[0] - ux) - math.atan2(m[1] - uy, m[0] - ux)
        )
        steps = max(6, int(abs(sweep) / _ARC_STEP) + 1)
        return tuple(
            (
                ux + radius * math.cos(a0 + sweep * i / steps),
                uy + radius * math.sin(a0 + sweep * i / steps),
            )
            for i in range(steps + 1)
        )

    @property
    def names_hidden(self) -> bool:
        """Whether the symbol asks for its pin NAMES not to be drawn."""
        return self._hidden(self._node.find("pin_names"))

    @property
    def numbers_hidden(self) -> bool:
        """Whether the symbol asks for its pin NUMBERS not to be drawn."""
        return self._hidden(self._node.find("pin_numbers"))


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
