"""Resolve a parsed P-CAD library into deterministic integer geometry."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from stockroom.pcad.errors import PcadNormalizeError, PcadParseError
from stockroom.pcad.model import (
    Attribute,
    Footprint,
    Graphic,
    Library,
    Pad,
    Pin,
    Point,
    Symbol,
    TextStyle,
)
from stockroom.pcad.parser import Document, Node


@dataclass(frozen=True, slots=True)
class _PadStyle:
    name: str
    hole_nm: int
    shape: str
    width_nm: int
    height_nm: int


def _fail(message: str, node: Node | None = None) -> PcadNormalizeError:
    suffix = f" at line {node.line}" if node is not None else ""
    return PcadNormalizeError(f"{message}{suffix}")


def _one_argument(node: Node, what: str) -> str:
    if len(node.arguments) != 1:
        raise _fail(f"{what} requires exactly one value", node)
    return node.arguments[0]


def _decimal(value: str, what: str, node: Node) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _fail(f"invalid {what} value {value!r}", node) from exc
    if not result.is_finite():
        raise _fail(f"non-finite {what} value {value!r}", node)
    return result


def _integer(value: str, what: str, node: Node) -> int:
    number = _decimal(value, what, node)
    if number != number.to_integral_value():
        raise _fail(f"{what} must be an integer, got {value!r}", node)
    return int(number)


def _bool(value: str, what: str, node: Node) -> bool:
    folded = value.casefold()
    if folded == "true":
        return True
    if folded == "false":
        return False
    raise _fail(f"{what} must be True or False, got {value!r}", node)


def _nm(value: str, unit_scale_nm: Decimal, what: str, node: Node) -> int:
    scaled = _decimal(value, what, node) * unit_scale_nm
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _angle(value: str, what: str, node: Node) -> int:
    scaled = _decimal(value, what, node) * Decimal(1_000_000)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _point(node: Node, unit_scale_nm: Decimal) -> Point:
    if len(node.arguments) != 2:
        raise _fail("pt requires exactly two coordinates", node)
    return Point(
        _nm(node.arguments[0], unit_scale_nm, "x coordinate", node),
        _nm(node.arguments[1], unit_scale_nm, "y coordinate", node),
    )


def _required_value(parent: Node, name: str) -> str:
    try:
        child = parent.child(name, required=True)
    except PcadParseError as exc:
        raise _fail(str(exc), parent) from exc
    assert child is not None
    return _one_argument(child, name)


def _optional_value(parent: Node, name: str, default: str) -> str:
    try:
        child = parent.child(name)
    except PcadParseError as exc:
        raise _fail(str(exc), parent) from exc
    return default if child is None else _one_argument(child, name)


def _name(node: Node, what: str) -> str:
    if not node.arguments:
        raise _fail(f"{what} has no name", node)
    return node.arguments[0]


def _attributes(nodes: tuple[Node, ...], layer: int | None = None) -> tuple[Attribute, ...]:
    result: list[Attribute] = []
    for node in nodes:
        if len(node.arguments) < 2:
            raise _fail("attr requires a name and value", node)
        result.append(Attribute(node.arguments[0], node.arguments[1], layer))
    return tuple(result)


def _text_styles(
    library: Node, unit_scale_nm: Decimal
) -> tuple[tuple[TextStyle, ...], frozenset[str]]:
    styles: list[TextStyle] = []
    seen: set[str] = set()
    for node in library.children_named("textStyleDef"):
        name = _name(node, "textStyleDef")
        folded = name.casefold()
        if folded in seen:
            raise _fail(f"duplicate text style {name!r}", node)
        seen.add(folded)
        font = node.child("font", required=True)
        assert font is not None
        font_type = _required_value(font, "fontType")
        if font_type.casefold() != "stroke":
            raise _fail(f"unsupported font type {font_type!r}", font)
        family = _required_value(font, "fontFamily")
        face = _required_value(font, "fontFace")
        height = _nm(_required_value(font, "fontHeight"), unit_scale_nm, "font height", font)
        stroke = _nm(_required_value(font, "strokeWidth"), unit_scale_nm, "stroke width", font)
        styles.append(TextStyle(name, font_type, family, face, height, stroke))
    return tuple(styles), frozenset(seen)


def _pad_styles(library: Node, unit_scale_nm: Decimal) -> dict[str, _PadStyle]:
    styles: dict[str, _PadStyle] = {}
    for node in library.children_named("padStyleDef"):
        name = _name(node, "padStyleDef")
        key = name.casefold()
        if key in styles:
            raise _fail(f"duplicate pad style {name!r}", node)
        hole = _nm(_required_value(node, "holeDiam"), unit_scale_nm, "hole diameter", node)
        if hole < 0:
            raise _fail(f"negative hole diameter in pad style {name!r}", node)
        candidates: list[tuple[int, str, int, int]] = []
        for shape_node in node.children_named("padShape"):
            shape_name = _required_value(shape_node, "padShapeType").casefold()
            width_node = shape_node.child("shapeWidth")
            height_node = shape_node.child("shapeHeight")
            if width_node is None or height_node is None:
                layer_type_node = shape_node.child("layerType")
                layer_type = (
                    _one_argument(layer_type_node, "layerType").casefold()
                    if layer_type_node is not None
                    else ""
                )
                # P-CAD's Thrm* plane entry is a plane-connection rule, not the pad's physical
                # copper geometry. Ultra Librarian emits a real outside/inside diameter here
                # even for SMD pads whose top-copper Rect/Ellipse is already explicit. Altium's
                # library pad is defined by that physical layer shape; rejecting the whole part
                # because its source also describes a PCB-plane thermal throws valid CAD away.
                if layer_type == "plane" and shape_name.startswith("thrm"):
                    continue
                outside = _optional_value(shape_node, "outsideDiam", "0")
                inside = _optional_value(shape_node, "insideDiam", "0")
                if (
                    _decimal(outside, "outside diameter", shape_node) != 0
                    or _decimal(inside, "inside diameter", shape_node) != 0
                ):
                    raise _fail(f"unsupported physical pad shape {shape_name!r}", shape_node)
                continue
            width = _nm(
                _one_argument(width_node, "shapeWidth"), unit_scale_nm, "pad width", width_node
            )
            height = _nm(
                _one_argument(height_node, "shapeHeight"),
                unit_scale_nm,
                "pad height",
                height_node,
            )
            if width == 0 and height == 0:
                continue
            if width <= 0 or height <= 0:
                raise _fail(f"invalid dimensions in pad style {name!r}", shape_node)
            if shape_name not in {"rect", "ellipse"}:
                raise _fail(f"unsupported physical pad shape {shape_name!r}", shape_node)
            layer_ref = shape_node.child("layerNumRef")
            priority = 0
            if layer_ref is not None:
                layer = _integer(_one_argument(layer_ref, "layerNumRef"), "layer number", layer_ref)
                priority = 2 if layer == 1 else 1
            elif shape_node.child("layerType") is not None:
                priority = 1
            candidates.append((priority, shape_name, width, height))
        if not candidates:
            raise _fail(f"pad style {name!r} has no physical copper shape", node)
        candidates.sort(reverse=True)
        best = candidates[0]
        same_priority = {candidate[1:] for candidate in candidates if candidate[0] == best[0]}
        if len(same_priority) != 1:
            raise _fail(f"pad style {name!r} has conflicting copper shapes", node)
        styles[key] = _PadStyle(name, hole, best[1], best[2], best[3])
    return styles


def _validate_text_style(node: Node, known_styles: frozenset[str]) -> str | None:
    reference = node.child("textStyleRef")
    if reference is None:
        return None
    style = _one_argument(reference, "textStyleRef")
    if style.casefold() not in known_styles:
        raise _fail(f"unresolved text style {style!r}", reference)
    return style


def _graphic(
    node: Node,
    unit_scale_nm: Decimal,
    layer: int | None,
    known_styles: frozenset[str],
) -> Graphic:
    kind = node.name.casefold()
    if kind == "line":
        points = tuple(_point(point, unit_scale_nm) for point in node.children_named("pt"))
        if len(points) != 2:
            raise _fail("line requires exactly two points", node)
        width_node = node.child("width")
        width = (
            0
            if width_node is None
            else _nm(_one_argument(width_node, "width"), unit_scale_nm, "line width", width_node)
        )
        return Graphic("line", layer, points=points, width_nm=width)
    if kind == "poly":
        points = tuple(_point(point, unit_scale_nm) for point in node.children_named("pt"))
        if len(points) < 3:
            raise _fail("poly requires at least three points", node)
        width_node = node.child("width")
        width = (
            0
            if width_node is None
            else _nm(_one_argument(width_node, "width"), unit_scale_nm, "polygon width", width_node)
        )
        return Graphic("polygon", layer, points=points, width_nm=width)
    if kind == "arc":
        points = tuple(_point(point, unit_scale_nm) for point in node.children_named("pt"))
        if len(points) != 1:
            raise _fail("arc requires exactly one center point", node)
        radius = _nm(_required_value(node, "radius"), unit_scale_nm, "arc radius", node)
        width = _nm(_required_value(node, "width"), unit_scale_nm, "arc width", node)
        return Graphic(
            "arc",
            layer,
            points=points,
            width_nm=width,
            radius_nm=radius,
            start_angle_udeg=_angle(_required_value(node, "startAngle"), "start angle", node),
            sweep_angle_udeg=_angle(_required_value(node, "sweepAngle"), "sweep angle", node),
        )
    if kind == "text":
        points = tuple(_point(point, unit_scale_nm) for point in node.children_named("pt"))
        if len(points) != 1 or len(node.arguments) != 1:
            raise _fail("text requires exactly one point and one string", node)
        justify_node = node.child("justify")
        return Graphic(
            "text",
            layer,
            points=points,
            text=node.arguments[0],
            text_style=_validate_text_style(node, known_styles),
            justify=None if justify_node is None else _one_argument(justify_node, "justify"),
        )
    raise _fail(f"unsupported geometry {node.name!r}", node)


def _footprints(
    library: Node,
    unit_scale_nm: Decimal,
    styles: dict[str, _PadStyle],
    known_text_styles: frozenset[str],
    default_name: str,
) -> tuple[Footprint, ...]:
    footprints: list[Footprint] = []
    seen: set[str] = set()
    for node in library.children_named("patternDef"):
        name = _name(node, "patternDef")
        if name.casefold() in seen:
            raise _fail(f"duplicate pattern {name!r}", node)
        seen.add(name.casefold())
        allowed = {"originalname", "multilayer", "layercontents"}
        unknown = [
            child.name
            for child in node.items[1:]
            if isinstance(child, Node) and child.name.casefold() not in allowed
        ]
        if unknown:
            raise _fail(f"unsupported pattern construct {unknown[0]!r}", node)
        multi = node.child("multiLayer", required=True)
        assert multi is not None
        for child in multi.items[1:]:
            if isinstance(child, Node) and child.name.casefold() not in {"pad", "pickpoint"}:
                raise _fail(f"unsupported electrical construct {child.name!r}", child)
        pads: list[Pad] = []
        pad_numbers: set[str] = set()
        for pad_node in multi.children_named("pad"):
            number = _required_value(pad_node, "padNum")
            if number in pad_numbers:
                raise _fail(f"duplicate pad {number!r} in pattern {name!r}", pad_node)
            pad_numbers.add(number)
            style_name = _required_value(pad_node, "padStyleRef")
            style = styles.get(style_name.casefold())
            if style is None:
                raise _fail(f"unresolved pad style {style_name!r}", pad_node)
            point_node = pad_node.child("pt", required=True)
            assert point_node is not None
            rotation = _angle(_optional_value(pad_node, "rotation", "0"), "pad rotation", pad_node)
            pads.append(
                Pad(
                    number,
                    style.name,
                    "smd" if style.hole_nm == 0 else "through_hole",
                    style.shape,
                    _point(point_node, unit_scale_nm),
                    style.width_nm,
                    style.height_nm,
                    rotation,
                    style.hole_nm,
                    style.hole_nm > 0,
                )
            )
        if not pads:
            raise _fail(f"pattern {name!r} has no pads", node)

        graphics: list[Graphic] = []
        attributes: list[Attribute] = []
        for contents in node.children_named("layerContents"):
            layer = _integer(_required_value(contents, "layerNumRef"), "layer number", contents)
            for child in contents.items[1:]:
                if not isinstance(child, Node) or child.name.casefold() == "layernumref":
                    continue
                if child.name.casefold() == "attr":
                    _validate_text_style(child, known_text_styles)
                    attributes.extend(_attributes((child,), layer))
                elif child.name.casefold() in {"line", "poly", "arc", "text"}:
                    graphics.append(_graphic(child, unit_scale_nm, layer, known_text_styles))
                else:
                    raise _fail(f"unsupported pattern geometry {child.name!r}", child)
        footprints.append(
            Footprint(
                name,
                name.casefold() == default_name.casefold(),
                tuple(pads),
                tuple(graphics),
                tuple(attributes),
            )
        )
    if default_name.casefold() not in seen:
        raise _fail(f"unresolved attached pattern {default_name!r}")
    default_pads = next(fp.pads for fp in footprints if fp.default)
    expected_numbers = {pad.number for pad in default_pads}
    for footprint in footprints:
        if {pad.number for pad in footprint.pads} != expected_numbers:
            raise _fail(f"variant {footprint.name!r} has a different electrical pad set")
    return tuple(footprints)


def _symbol(
    symbol_node: Node,
    comp_pins: dict[str, tuple[str, int, int, str]],
    unit_scale_nm: Decimal,
    known_text_styles: frozenset[str],
) -> Symbol:
    allowed = {"originalname", "pin", "line", "poly", "arc", "text", "attr"}
    for child in symbol_node.items[1:]:
        if isinstance(child, Node) and child.name.casefold() not in allowed:
            raise _fail(f"unsupported symbol geometry {child.name!r}", child)
    pin_nodes = symbol_node.children_named("pin")
    by_symbol_number: dict[int, Node] = {}
    for pin_node in pin_nodes:
        number = _integer(_required_value(pin_node, "pinNum"), "symbol pin number", pin_node)
        if number in by_symbol_number:
            raise _fail(f"duplicate symbol pin {number}", pin_node)
        by_symbol_number[number] = pin_node

    pins: list[Pin] = []
    for comp_number, (name, part, symbol_number, electrical_type) in comp_pins.items():
        pin_node = by_symbol_number.get(symbol_number)
        if pin_node is None:
            raise _fail(
                f"component pin {comp_number!r} refers to missing symbol pin {symbol_number}"
            )
        point_node = pin_node.child("pt", required=True)
        assert point_node is not None
        display = pin_node.child("pinDisplay")
        show_number = True
        show_name = True
        if display is not None:
            show_number = _bool(
                _optional_value(display, "dispPinDes", "True"), "dispPinDes", display
            )
            show_name = _bool(
                _optional_value(display, "dispPinName", "True"), "dispPinName", display
            )
        for text_holder_name in ("pinDes", "pinName"):
            holder = pin_node.child(text_holder_name)
            if holder is not None:
                text_node = holder.child("text", required=True)
                assert text_node is not None
                _validate_text_style(text_node, known_text_styles)
        pins.append(
            Pin(
                comp_number,
                name,
                part,
                electrical_type.casefold(),
                _point(point_node, unit_scale_nm),
                _nm(_required_value(pin_node, "pinLength"), unit_scale_nm, "pin length", pin_node),
                _angle(_optional_value(pin_node, "rotation", "0"), "pin rotation", pin_node),
                show_name,
                show_number,
            )
        )
    if set(by_symbol_number) != {value[2] for value in comp_pins.values()}:
        raise _fail("symbol contains pins that are not mapped by the component")

    graphics: list[Graphic] = []
    for child in symbol_node.items[1:]:
        if isinstance(child, Node) and child.name.casefold() in {"line", "poly", "arc", "text"}:
            graphics.append(_graphic(child, unit_scale_nm, None, known_text_styles))
    for attr in symbol_node.children_named("attr"):
        _validate_text_style(attr, known_text_styles)
    return Symbol(
        _name(symbol_node, "symbolDef"),
        tuple(pins),
        tuple(graphics),
        _attributes(symbol_node.children_named("attr")),
    )


def normalize(document: Document) -> Library:
    """Normalize one P-CAD component library or fail before dropping data."""
    header = document.root("asciiHeader")
    version = header.child("asciiVersion", required=True)
    assert version is not None
    if version.arguments != ("3", "0"):
        raise _fail(f"unsupported P-CAD ASCII version {' '.join(version.arguments)!r}", version)
    units = _required_value(header, "fileUnits")
    if units.casefold() == "mil":
        scale = Decimal(25_400)
    elif units.casefold() in {"mm", "millimeter"}:
        scale = Decimal(1_000_000)
    else:
        raise _fail(f"unsupported P-CAD units {units!r}", header)

    library_node = document.root("library")
    library_name = _name(library_node, "library")
    text_styles, known_text_styles = _text_styles(library_node, scale)
    pad_styles = _pad_styles(library_node, scale)
    component_nodes = library_node.children_named("compDef")
    if len(component_nodes) != 1:
        raise _fail(f"expected exactly one compDef, found {len(component_nodes)}", library_node)
    component = component_nodes[0]
    allowed_component_constructs = {
        "originalname",
        "compheader",
        "comppin",
        "attachedsymbol",
        "attachedpattern",
        "attr",
    }
    for child in component.items[1:]:
        if isinstance(child, Node) and child.name.casefold() not in allowed_component_constructs:
            raise _fail(f"unsupported component construct {child.name!r}", child)
    header_node = component.child("compHeader", required=True)
    assert header_node is not None
    expected_pin_count = _integer(_required_value(header_node, "numPins"), "pin count", header_node)
    expected_part_count = _integer(
        _required_value(header_node, "numParts"), "part count", header_node
    )
    if expected_part_count != 1:
        raise _fail("multi-part P-CAD symbols are not yet supported", header_node)

    comp_pins: dict[str, tuple[str, int, int, str]] = {}
    for pin_node in component.children_named("compPin"):
        number = _name(pin_node, "compPin")
        if number in comp_pins:
            raise _fail(f"duplicate component pin {number!r}", pin_node)
        comp_pins[number] = (
            _required_value(pin_node, "pinName"),
            _integer(_required_value(pin_node, "partNum"), "part number", pin_node),
            _integer(_required_value(pin_node, "symPinNum"), "symbol pin number", pin_node),
            _required_value(pin_node, "pinType"),
        )
    if len(comp_pins) != expected_pin_count:
        raise _fail(
            f"compHeader declares {expected_pin_count} pins but {len(comp_pins)} were found",
            component,
        )
    if any(part != 1 for _, part, _, _ in comp_pins.values()):
        raise _fail("component pin refers to an unsupported symbol part", component)

    attached_symbol = component.child("attachedSymbol", required=True)
    assert attached_symbol is not None
    attached_part = _integer(
        _required_value(attached_symbol, "partNum"), "attached symbol part", attached_symbol
    )
    if attached_part != 1:
        raise _fail("attached symbol refers to an unsupported part", attached_symbol)
    symbol_name = _required_value(attached_symbol, "symbolName")
    symbol_nodes = {
        _name(node, "symbolDef").casefold(): node
        for node in library_node.children_named("symbolDef")
    }
    symbol_node = symbol_nodes.get(symbol_name.casefold())
    if symbol_node is None:
        raise _fail(f"unresolved attached symbol {symbol_name!r}", attached_symbol)
    symbol = _symbol(symbol_node, comp_pins, scale, known_text_styles)

    attached_pattern = component.child("attachedPattern", required=True)
    assert attached_pattern is not None
    default_pattern = _required_value(attached_pattern, "patternName")
    expected_pad_count = _integer(
        _required_value(attached_pattern, "numPads"), "pad count", attached_pattern
    )
    map_node = attached_pattern.child("padPinMap", required=True)
    assert map_node is not None
    map_items = [item for item in map_node.items[1:] if isinstance(item, Node)]
    pad_pin_map: list[tuple[str, str]] = []
    index = 0
    while index < len(map_items):
        pad_node = map_items[index]
        if pad_node.name.casefold() != "padnum" or index + 1 >= len(map_items):
            raise _fail("padPinMap must contain PadNum/CompPinRef pairs", map_node)
        pin_node = map_items[index + 1]
        if pin_node.name.casefold() != "comppinref":
            raise _fail("padPinMap must contain PadNum/CompPinRef pairs", map_node)
        pair = (_one_argument(pad_node, "PadNum"), _one_argument(pin_node, "CompPinRef"))
        if pair[1] not in comp_pins:
            raise _fail(f"pad map refers to missing component pin {pair[1]!r}", pin_node)
        pad_pin_map.append(pair)
        index += 2
    mapped_pads = {pad for pad, _ in pad_pin_map}
    mapped_pins = {pin for _, pin in pad_pin_map}
    if (
        len(pad_pin_map) != expected_pad_count
        or len(mapped_pads) != len(pad_pin_map)
        or len(mapped_pins) != len(pad_pin_map)
        or mapped_pins != set(comp_pins)
    ):
        raise _fail("padPinMap does not match the declared unique pad count", map_node)

    footprints = _footprints(library_node, scale, pad_styles, known_text_styles, default_pattern)
    default_pads = next(footprint.pads for footprint in footprints if footprint.default)
    # The electrical map must resolve to real footprint pads, but the footprint may legitimately
    # contain additional physical pads. Ultra Librarian uses that for exposed-pad thermal drill
    # arrays: TPS62130RGTR maps electrical pads 1-17 and keeps physical thermal-via pads 18-21.
    # Requiring equality discarded the entire valid library; requiring the mapped set to exist
    # preserves those physical features without inventing electrical component pins.
    physical_pad_numbers = {pad.number for pad in default_pads}
    mapped_pad_numbers = {pad for pad, _ in pad_pin_map}
    if not mapped_pad_numbers.issubset(physical_pad_numbers):
        raise _fail("default pattern is missing a pad from padPinMap", attached_pattern)

    component_attributes = _attributes(component.children_named("attr"))
    attr_by_name = {
        attribute.name.casefold(): attribute.value for attribute in component_attributes
    }
    manufacturer = attr_by_name.get("manufacturer_name")
    mpn = attr_by_name.get("manufacturer_part_number")
    if not manufacturer or not mpn:
        raise _fail(
            "component is missing exact manufacturer or manufacturer part number", component
        )
    return Library(
        document.source_sha256,
        units,
        library_name,
        manufacturer,
        mpn,
        _required_value(header_node, "refDesPrefix"),
        symbol,
        footprints,
        default_pattern,
        tuple(pad_pin_map),
        text_styles,
    )
