"""Format-neutral interactive PCB geometry from IPC-2581.

IPC-2581 is the exchange seam, not a second EDA-specific frontend. KiCad and
Altium both export it, and the browser consumes only this normalized scene.
Coordinates remain in the native export space so a rendered board and its
component hit geometry share one honest transform.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from xml.etree import ElementTree

_SCHEMA_VERSION = 1
_CONDUCTIVE_FUNCTIONS = {"SIGNAL", "POWERGROUND", "CONDUCTIVE", "CONDUCTOR"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _finite_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _net_name(value: str | None) -> str:
    name = (value or "").strip()
    return "" if name.casefold() == "no net" else name


def _coordinates(element: ElementTree.Element) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for node in element.iter():
        x = _finite_number(node.attrib.get("x"))
        y = _finite_number(node.attrib.get("y"))
        if x is not None and y is not None:
            points.append((x, y))
        start_x = _finite_number(node.attrib.get("startX"))
        start_y = _finite_number(node.attrib.get("startY"))
        if start_x is not None and start_y is not None:
            points.append((start_x, start_y))
        end_x = _finite_number(node.attrib.get("endX"))
        end_y = _finite_number(node.attrib.get("endY"))
        if end_x is not None and end_y is not None:
            points.append((end_x, end_y))
    return points


def _bounds(points: list[tuple[float, float]]) -> dict | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        return None
    return {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
        "width": width,
        "height": height,
    }


def _first_child(
    element: ElementTree.Element,
    name: str,
) -> ElementTree.Element | None:
    return next(
        (child for child in element if _local_name(child.tag) == name),
        None,
    )


def _component_side(layer: str, mirrored: bool) -> str:
    normalized = layer.casefold()
    if normalized.startswith("b.") or "bottom" in normalized or mirrored:
        return "bottom"
    return "top"


def _layer_side(layer: str, declared: str = "") -> str | None:
    normalized = layer.casefold()
    normalized_declared = declared.casefold()
    if normalized_declared == "top" or normalized.startswith("f.") or "top" in normalized:
        return "top"
    if normalized_declared == "bottom" or normalized.startswith("b.") or "bottom" in normalized:
        return "bottom"
    return None


def _standard_shapes(root: ElementTree.Element) -> dict[str, dict]:
    shapes: dict[str, dict] = {}
    for entry in root.iter():
        if _local_name(entry.tag) != "EntryStandard":
            continue
        identifier = entry.attrib.get("id", "").strip()
        primitive = next(iter(entry), None)
        if not identifier or primitive is None:
            continue
        kind = _local_name(primitive.tag)
        if kind == "Circle":
            diameter = _finite_number(primitive.attrib.get("diameter"))
            width = height = diameter
            normalized = "circle"
        else:
            width = _finite_number(primitive.attrib.get("width"))
            height = _finite_number(primitive.attrib.get("height"))
            normalized = {
                "RectCenter": "rect",
                "RectRound": "rounded-rect",
                "Oval": "oval",
            }.get(kind, "unknown")
        if width is None or height is None or width <= 0 or height <= 0:
            continue
        shapes[identifier] = {
            "kind": normalized,
            "width_mm": width,
            "height_mm": height,
        }
    return shapes


def _layer_metadata(root: ElementTree.Element) -> dict[str, dict[str, str]]:
    layers: dict[str, dict[str, str]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue
        name = element.attrib.get("name", "").strip()
        if name:
            layers[name] = {
                "function": element.attrib.get("layerFunction", "").strip(),
                "side": element.attrib.get("side", "").strip(),
            }
    return layers


def _conductive_side(
    layer: str,
    metadata: dict[str, dict[str, str]],
) -> str | None:
    declared = metadata.get(layer, {})
    side = _layer_side(layer, declared.get("side", ""))
    if side is None:
        return None
    function = declared.get("function", "").upper()
    normalized = layer.casefold()
    if (
        function in _CONDUCTIVE_FUNCTIONS
        or normalized.endswith(".cu")
        or normalized in {"toplayer", "bottomlayer"}
    ):
        return side
    return None


def _pin_row(
    element: ElementTree.Element,
    *,
    layer: str,
    net: str,
    side: str,
    shapes: dict[str, dict],
) -> tuple[str, dict] | None:
    location = _first_child(element, "Location")
    pin_ref = _first_child(element, "PinRef")
    primitive = _first_child(element, "StandardPrimitiveRef")
    if location is None or pin_ref is None:
        return None
    reference = pin_ref.attrib.get("componentRef", "").strip()
    number = pin_ref.attrib.get("pin", "").strip()
    x = _finite_number(location.attrib.get("x"))
    y = _finite_number(location.attrib.get("y"))
    if not reference or not number or x is None or y is None:
        return None
    transform = _first_child(element, "Xform")
    rotation = (
        _finite_number(transform.attrib.get("rotation"))
        if transform is not None
        else None
    )
    shape_id = primitive.attrib.get("id", "").strip() if primitive is not None else ""
    return reference, {
        "number": number,
        "net": net,
        "x_mm": x,
        "y_mm": y,
        "rotation_deg": (rotation or 0.0) % 360,
        "side": side,
        "layer": layer,
        "shape": shapes.get(shape_id),
    }


def _component_pins(root: ElementTree.Element) -> dict[str, list[dict]]:
    shapes = _standard_shapes(root)
    metadata = _layer_metadata(root)
    pins: dict[str, list[dict]] = {}

    # KiCad revision C places conductive pads inside each LayerFeature/Set.
    for feature in root.iter():
        if _local_name(feature.tag) != "LayerFeature":
            continue
        layer = feature.attrib.get("layerRef", "").strip()
        side = _conductive_side(layer, metadata)
        if side is None:
            continue
        for group in feature:
            if _local_name(group.tag) != "Set":
                continue
            net = _net_name(group.attrib.get("net"))
            for element in group:
                if _local_name(element.tag) != "Pad":
                    continue
                row = _pin_row(
                    element,
                    layer=layer,
                    net=net,
                    side=side,
                    shapes=shapes,
                )
                if row is not None:
                    pins.setdefault(row[0], []).append(row[1])

    # Altium revision B places absolute component pads in top-level PadStacks.
    for stack in root.iter():
        if _local_name(stack.tag) != "PadStack":
            continue
        net = _net_name(stack.attrib.get("net"))
        for element in stack:
            if _local_name(element.tag) != "LayerPad":
                continue
            layer = element.attrib.get("layerRef", "").strip()
            side = _conductive_side(layer, metadata)
            if side is None:
                continue
            row = _pin_row(
                element,
                layer=layer,
                net=net,
                side=side,
                shapes=shapes,
            )
            if row is not None:
                pins.setdefault(row[0], []).append(row[1])

    for rows in pins.values():
        rows.sort(
            key=lambda row: (
                row["number"].casefold(),
                row["side"],
                row["x_mm"],
                row["y_mm"],
            )
        )
    return pins


def _via_sides(
    layer: str,
    *,
    from_layer: str,
    to_layer: str,
    metadata: dict[str, dict[str, str]],
) -> list[str]:
    sides: set[str] = set()
    for candidate in (layer, from_layer, to_layer):
        if not candidate:
            continue
        normalized = candidate.casefold()
        declared = metadata.get(candidate, {}).get("side", "")
        side = _layer_side(candidate, declared)
        if side is not None:
            sides.add(side)
        if normalized.startswith("f.") or "f.cu" in normalized or "top" in normalized:
            sides.add("top")
        if normalized.startswith("b.") or "b.cu" in normalized or "bottom" in normalized:
            sides.add("bottom")
    return [side for side in ("top", "bottom") if side in sides]


def _via_row(
    element: ElementTree.Element,
    *,
    layer: str,
    net: str,
    metadata: dict[str, dict[str, str]],
) -> dict | None:
    if element.attrib.get("platingStatus", "").strip().upper() != "VIA":
        return None
    x = _finite_number(element.attrib.get("x"))
    y = _finite_number(element.attrib.get("y"))
    diameter = _finite_number(element.attrib.get("diameter"))
    if x is None or y is None or diameter is None or diameter <= 0:
        return None
    span = _first_child(element, "Span")
    from_layer = span.attrib.get("fromLayer", "").strip() if span is not None else ""
    to_layer = span.attrib.get("toLayer", "").strip() if span is not None else ""
    sides = _via_sides(
        layer,
        from_layer=from_layer,
        to_layer=to_layer,
        metadata=metadata,
    )
    if not sides:
        return None
    return {
        "name": element.attrib.get("name", "").strip(),
        "net": net,
        "x_mm": x,
        "y_mm": y,
        "diameter_mm": diameter,
        "from_layer": from_layer,
        "to_layer": to_layer,
        "sides": sides,
    }


def _vias(root: ElementTree.Element) -> list[dict]:
    metadata = _layer_metadata(root)
    rows: list[dict] = []
    seen: set[tuple[str, float, float, float]] = set()

    def add(row: dict | None) -> None:
        if row is None:
            return
        key = (
            row["net"].casefold(),
            row["x_mm"],
            row["y_mm"],
            row["diameter_mm"],
        )
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    # Altium revision B carries net and layer-span truth in each PadStack.
    for stack in root.iter():
        if _local_name(stack.tag) != "PadStack":
            continue
        net = _net_name(stack.attrib.get("net"))
        for element in stack:
            if _local_name(element.tag) != "LayerHole":
                continue
            add(
                _via_row(
                    element,
                    layer="",
                    net=net,
                    metadata=metadata,
                )
            )

    # KiCad revision C carries vias in a net-bearing drill LayerFeature/Set.
    for feature in root.iter():
        if _local_name(feature.tag) != "LayerFeature":
            continue
        layer = feature.attrib.get("layerRef", "").strip()
        for group in feature:
            if _local_name(group.tag) != "Set":
                continue
            net = _net_name(group.attrib.get("net"))
            if not net:
                continue
            for element in group:
                if _local_name(element.tag) == "Hole":
                    add(
                        _via_row(
                            element,
                            layer=layer,
                            net=net,
                            metadata=metadata,
                        )
                    )

    rows.sort(
        key=lambda row: (
            row["net"].casefold(),
            row["name"].casefold(),
            row["x_mm"],
            row["y_mm"],
        )
    )
    return rows


def _line_widths(root: ElementTree.Element) -> dict[str, float]:
    widths: dict[str, float] = {}
    for entry in root.iter():
        if _local_name(entry.tag) != "EntryLineDesc":
            continue
        identifier = entry.attrib.get("id", "").strip()
        description = _first_child(entry, "LineDesc")
        width = (
            _finite_number(description.attrib.get("lineWidth"))
            if description is not None
            else None
        )
        if identifier and width is not None and width > 0:
            widths[identifier] = width
    return widths


def _track_row(
    element: ElementTree.Element,
    *,
    layer: str,
    side: str,
    net: str,
    widths: dict[str, float],
) -> dict | None:
    start_x = _finite_number(element.attrib.get("startX"))
    start_y = _finite_number(element.attrib.get("startY"))
    end_x = _finite_number(element.attrib.get("endX"))
    end_y = _finite_number(element.attrib.get("endY"))
    if None in {start_x, start_y, end_x, end_y}:
        return None
    description = _first_child(element, "LineDesc")
    reference = _first_child(element, "LineDescRef")
    width = (
        _finite_number(description.attrib.get("lineWidth"))
        if description is not None
        else None
    )
    if width is None and reference is not None:
        width = widths.get(reference.attrib.get("id", "").strip())
    if width is None or width <= 0:
        return None
    return {
        "net": net,
        "layer": layer,
        "side": side,
        "start_x_mm": start_x,
        "start_y_mm": start_y,
        "end_x_mm": end_x,
        "end_y_mm": end_y,
        "width_mm": width,
    }


def _tracks(root: ElementTree.Element) -> list[dict]:
    metadata = _layer_metadata(root)
    widths = _line_widths(root)
    rows: list[dict] = []
    seen: set[tuple[str, str, float, float, float, float, float]] = set()
    for feature in root.iter():
        if _local_name(feature.tag) != "LayerFeature":
            continue
        layer = feature.attrib.get("layerRef", "").strip()
        side = _conductive_side(layer, metadata)
        if side is None:
            continue
        for group in feature:
            if _local_name(group.tag) != "Set":
                continue
            net = _net_name(group.attrib.get("net"))
            if not net:
                continue
            for features in group:
                if _local_name(features.tag) != "Features":
                    continue
                for element in features.iter():
                    if _local_name(element.tag) != "Line":
                        continue
                    row = _track_row(
                        element,
                        layer=layer,
                        side=side,
                        net=net,
                        widths=widths,
                    )
                    if row is None:
                        continue
                    key = (
                        row["net"].casefold(),
                        row["layer"].casefold(),
                        row["start_x_mm"],
                        row["start_y_mm"],
                        row["end_x_mm"],
                        row["end_y_mm"],
                        row["width_mm"],
                    )
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["net"].casefold(),
            row["side"],
            row["layer"].casefold(),
            row["start_x_mm"],
            row["start_y_mm"],
        )
    )
    return rows


def parse_ipc2581_board_scene(source: Path, *, board: str) -> dict:
    """Parse board, component, and selected-footprint pin geometry from IPC-2581."""

    source = Path(source)
    content = source.read_bytes()
    root = ElementTree.fromstring(content)

    profile_points: list[tuple[float, float]] = []
    packages: dict[str, dict | None] = {}
    components: list[dict] = []
    pins = _component_pins(root)
    vias = _vias(root)
    tracks = _tracks(root)

    for element in root.iter():
        kind = _local_name(element.tag)
        if kind == "Profile":
            profile_points.extend(_coordinates(element))
        elif kind == "Package":
            name = element.attrib.get("name", "").strip()
            outline = _first_child(element, "Outline")
            if name:
                packages[name] = _bounds(_coordinates(outline)) if outline is not None else None

    for element in root.iter():
        if _local_name(element.tag) != "Component":
            continue
        reference = element.attrib.get("refDes", "").strip()
        location = _first_child(element, "Location")
        if not reference or location is None:
            continue
        x = _finite_number(location.attrib.get("x"))
        y = _finite_number(location.attrib.get("y"))
        if x is None or y is None:
            continue
        transform = _first_child(element, "Xform")
        rotation = (
            _finite_number(transform.attrib.get("rotation"))
            if transform is not None
            else None
        )
        mirrored = (
            transform is not None
            and transform.attrib.get("mirror", "").casefold() in {"true", "1"}
        )
        package = element.attrib.get("packageRef", "").strip()
        components.append(
            {
                "reference": reference,
                "x_mm": x,
                "y_mm": y,
                "rotation_deg": (rotation or 0.0) % 360,
                "side": _component_side(
                    element.attrib.get("layerRef", ""),
                    mirrored,
                ),
                "package": package,
                "part": element.attrib.get("part", "").strip(),
                "bounds": packages.get(package),
                "pins": pins.get(reference, []),
            }
        )

    board_bounds = _bounds(profile_points)
    if board_bounds is None:
        raise ValueError("IPC-2581 board profile has no usable area")
    components.sort(key=lambda row: row["reference"].casefold())
    body = {
        "schema_version": _SCHEMA_VERSION,
        "board": Path(board).as_posix(),
        "units": "mm",
        "bounds": board_bounds,
        "components": components,
        "vias": vias,
        "tracks": tracks,
        "summary": {
            "components": len(components),
            "pins": sum(len(row["pins"]) for row in components),
            "vias": len(vias),
            "tracks": len(tracks),
            "top": sum(row["side"] == "top" for row in components),
            "bottom": sum(row["side"] == "bottom" for row in components),
        },
        "source": {
            "format": "ipc-2581",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }
    return body
