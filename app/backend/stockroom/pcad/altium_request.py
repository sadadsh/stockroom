"""Translate normalized P-CAD libraries into the native writer request contract.

The translation is intentionally boring and deterministic: P-CAD integer nanometres
become JSON millimetres, known provider layers become explicit Altium layers, and
geometry which has no physical extent is omitted.  No Altium installation is involved.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from stockroom.model.part_id import FALLBACK_STEM, mpn_fingerprint, slug_mpn
from stockroom.pcad.model import Footprint, Graphic, Library, Point, TextStyle

REQUEST_SCHEMA = "stockroom.cad-converter/request/1"

# P-CAD and Altium do not share numeric layer identifiers.  These mappings are the
# semantic layers emitted by Ultra Librarian's P-CAD V15 exporter for component
# libraries.  Mechanical layers keep non-electrical provider geometry out of copper.
_PCAD_TO_ALTIUM_LAYER = {
    1: 1,  # Top copper
    2: 32,  # Bottom copper
    4: 37,  # Top solder mask opening
    6: 33,  # Top silkscreen / overlay
    7: 34,  # Bottom silkscreen / overlay
    8: 35,  # Top paste opening
    10: 57,  # Top assembly / fabrication
    11: 58,  # Bottom assembly / fabrication
    92: 71,  # Courtyard (Mechanical 15)
    94: 59,  # Component boundary (Mechanical 3)
    96: 60,  # Package/body outline (Mechanical 4)
}

# UL's same-bundle KiCad output emits the actual footprint from layers 6, 10, and 92.
# Layers 94/96 are provider construction/body guides and layer 98 is the generator
# worksheet.  They are useful while deriving the STEP body outline, but are not part
# of the imported land pattern Altium should display.
_NON_FOOTPRINT_OUTPUT_LAYERS = frozenset({94, 96, 98})
_DEFAULT_GRAPHIC_WIDTH_MM = 0.0254
_MASK_AND_PASTE_LAYERS = frozenset({35, 36, 37, 38})
_OUTPUT_STEM_LIMIT = 100


def _output_stem(mpn: str) -> str:
    """Return a bounded native filename without weakening the exact MPN.

    ``outputStem`` names only the two files produced by the converter.  It is not
    component identity: the request's ``mpn`` field and the symbol parameters retain
    the provider's exact punctuation.  The fingerprint keeps punctuation variants
    distinct even when their human-readable slugs collide.
    """

    fingerprint = mpn_fingerprint(mpn)
    readable_limit = _OUTPUT_STEM_LIMIT - len(fingerprint) - 1
    readable = (slug_mpn(mpn) or FALLBACK_STEM)[:readable_limit].rstrip("-")
    return f"{readable or FALLBACK_STEM}-{fingerprint}"


def _mm(nanometres: int) -> float:
    return nanometres / 1_000_000


def _degrees(microdegrees: int) -> float:
    return microdegrees / 1_000_000


def _point(point: Point) -> dict[str, float]:
    return {"xmm": _mm(point.x_nm), "ymm": _mm(point.y_nm)}


def _pin_orientation(microdegrees: int) -> str:
    """Map P-CAD's outward pin vector onto Altium's pin orientation.

    P-CAD stores the pin location at the symbol-body end and measures rotation
    counter-clockwise from +X.  Altium likewise derives the electrical tip by
    adding the pin length along its orientation, so the mapping is direct.  It
    must not use KiCad's opposite-facing pin enum (where the angle describes
    the direction from the electrical end back toward the symbol body).
    """
    angle = microdegrees % 360_000_000
    orientations = {
        0: "right",
        90_000_000: "up",
        180_000_000: "left",
        270_000_000: "down",
    }
    try:
        return orientations[angle]
    except KeyError as exc:
        raise ValueError(f"unsupported non-orthogonal P-CAD pin rotation: {_degrees(angle)}") from exc


def _electrical_type(value: str) -> str:
    folded = value.replace("_", "").replace("-", "").casefold()
    aliases = {
        "input": "input",
        "bidirectional": "inputOutput",
        "inputoutput": "inputOutput",
        "output": "output",
        "opencollector": "openCollector",
        "passive": "passive",
        "hiz": "hiZ",
        "openemitter": "openEmitter",
        "power": "power",
    }
    try:
        return aliases[folded]
    except KeyError as exc:
        raise ValueError(f"unsupported P-CAD pin electrical type: {value}") from exc


def _altium_layer(number: int | None) -> int:
    if number is None:
        raise ValueError("footprint graphic is missing its P-CAD layer")
    try:
        return _PCAD_TO_ALTIUM_LAYER[number]
    except KeyError as exc:
        raise ValueError(f"unsupported P-CAD footprint layer: {number}") from exc


def _text_style(styles: dict[str, TextStyle], name: str | None) -> TextStyle:
    if name is None:
        raise ValueError("P-CAD footprint text is missing its text style")
    try:
        return styles[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"unresolved P-CAD text style: {name}") from exc


def _symbol_graphics(graphics: tuple[Graphic, ...]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "lines": [],
        "rectangles": [],
        "polylines": [],
        "arcs": [],
        "ellipses": [],
        "labels": [],
    }
    for graphic in graphics:
        if graphic.kind == "line":
            start, end = graphic.points
            if start == end:
                continue
            result["lines"].append(
                {
                    "x1mm": _mm(start.x_nm),
                    "y1mm": _mm(start.y_nm),
                    "x2mm": _mm(end.x_nm),
                    "y2mm": _mm(end.y_nm),
                    "widthMm": _mm(graphic.width_nm),
                    "color": 0xFF0000,
                    "ownerPartId": 1,
                }
            )
        elif graphic.kind == "polygon":
            result["polylines"].append(
                {
                    "points": [_point(item) for item in graphic.points],
                    "lineWidth": 0,
                    "ownerPartId": 1,
                }
            )
        elif graphic.kind == "arc":
            if graphic.radius_nm <= 0:
                continue
            start = _degrees(graphic.start_angle_udeg) % 360
            sweep = _degrees(graphic.sweep_angle_udeg)
            result["arcs"].append(
                {
                    "xmm": _mm(graphic.points[0].x_nm),
                    "ymm": _mm(graphic.points[0].y_nm),
                    "radiusMm": _mm(graphic.radius_nm),
                    "startAngle": start,
                    "endAngle": 360 if abs(sweep) >= 360 else (start + sweep) % 360,
                    "lineWidth": 0,
                    "ownerPartId": 1,
                }
            )
        elif graphic.kind == "text":
            result["labels"].append(
                {
                    "text": graphic.text or "",
                    "xmm": _mm(graphic.points[0].x_nm),
                    "ymm": _mm(graphic.points[0].y_nm),
                    "ownerPartId": 1,
                }
            )
        else:
            raise ValueError(f"unsupported normalized symbol graphic: {graphic.kind}")
    return result


def _closed_line_outline(footprint: Footprint) -> tuple[Point, ...] | None:
    """Return the smallest closed body/assembly line loop, if the provider supplied one."""
    for layer in (96, 10):
        edges = [
            (graphic.points[0], graphic.points[1])
            for graphic in footprint.graphics
            if graphic.kind == "line"
            and graphic.layer_number == layer
            and graphic.points[0] != graphic.points[1]
        ]
        adjacency: dict[Point, list[Point]] = defaultdict(list)
        for start, end in edges:
            adjacency[start].append(end)
            adjacency[end].append(start)
        candidates: list[tuple[Point, ...]] = []
        seen: set[Point] = set()
        for origin in adjacency:
            if origin in seen:
                continue
            stack = [origin]
            component: set[Point] = set()
            while stack:
                point = stack.pop()
                if point in component:
                    continue
                component.add(point)
                stack.extend(adjacency[point])
            seen.update(component)
            if len(component) < 3 or any(len(adjacency[point]) != 2 for point in component):
                continue
            ordered = [origin]
            previous: Point | None = None
            current = origin
            while True:
                following = next(item for item in adjacency[current] if item != previous)
                if following == origin:
                    break
                ordered.append(following)
                previous, current = current, following
                if len(ordered) > len(component):
                    break
            if len(ordered) == len(component):
                candidates.append(tuple(ordered))
        if candidates:
            return min(
                candidates,
                key=lambda points: (
                    (max(item.x_nm for item in points) - min(item.x_nm for item in points))
                    * (max(item.y_nm for item in points) - min(item.y_nm for item in points)),
                    len(points),
                ),
            )
    return None


def _pad_outline(footprint: Footprint) -> tuple[Point, ...]:
    left = min(item.position.x_nm - item.width_nm // 2 for item in footprint.pads)
    right = max(item.position.x_nm + item.width_nm // 2 for item in footprint.pads)
    bottom = min(item.position.y_nm - item.height_nm // 2 for item in footprint.pads)
    top = max(item.position.y_nm + item.height_nm // 2 for item in footprint.pads)
    return (Point(left, bottom), Point(right, bottom), Point(right, top), Point(left, top))


def _footprint_graphics(
    footprint: Footprint,
    styles: dict[str, TextStyle],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "lines": [],
        "arcs": [],
        "texts": [],
        "fills": [],
    }
    for graphic in footprint.graphics:
        if graphic.layer_number in _NON_FOOTPRINT_OUTPUT_LAYERS:
            continue
        layer = _altium_layer(graphic.layer_number)
        if graphic.kind == "line":
            start, end = graphic.points
            if start == end:
                continue
            result["lines"].append(
                {
                    "x1mm": _mm(start.x_nm),
                    "y1mm": _mm(start.y_nm),
                    "x2mm": _mm(end.x_nm),
                    "y2mm": _mm(end.y_nm),
                    "widthMm": _mm(graphic.width_nm) or _DEFAULT_GRAPHIC_WIDTH_MM,
                    "layer": layer,
                }
            )
        elif graphic.kind == "polygon":
            width = _mm(graphic.width_nm) or _DEFAULT_GRAPHIC_WIDTH_MM
            points = graphic.points
            coordinates = {(point.x_nm, point.y_nm) for point in points}
            xs = {point.x_nm for point in points}
            ys = {point.y_nm for point in points}
            rectangle = {
                (x, y)
                for x in xs
                for y in ys
            }
            if (
                layer in _MASK_AND_PASTE_LAYERS
                and len(points) == 4
                and len(xs) == 2
                and len(ys) == 2
                and coordinates == rectangle
            ):
                result["fills"].append(
                    {
                        "x1mm": _mm(min(xs)),
                        "y1mm": _mm(min(ys)),
                        "x2mm": _mm(max(xs)),
                        "y2mm": _mm(max(ys)),
                        "layer": layer,
                        "rotation": 0,
                    }
                )
                continue
            for start, end in zip(points, (*points[1:], points[0]), strict=True):
                if start == end:
                    continue
                result["lines"].append(
                    {
                        "x1mm": _mm(start.x_nm),
                        "y1mm": _mm(start.y_nm),
                        "x2mm": _mm(end.x_nm),
                        "y2mm": _mm(end.y_nm),
                        "widthMm": width,
                        "layer": layer,
                    }
                )
        elif graphic.kind == "arc":
            if graphic.radius_nm <= 0:
                continue
            start = _degrees(graphic.start_angle_udeg) % 360
            sweep = _degrees(graphic.sweep_angle_udeg)
            result["arcs"].append(
                {
                    "xmm": _mm(graphic.points[0].x_nm),
                    "ymm": _mm(graphic.points[0].y_nm),
                    "radiusMm": _mm(graphic.radius_nm),
                    "startAngle": start,
                    "endAngle": 360 if abs(sweep) >= 360 else (start + sweep) % 360,
                    "widthMm": _mm(graphic.width_nm) or _DEFAULT_GRAPHIC_WIDTH_MM,
                    "layer": layer,
                }
            )
        elif graphic.kind == "text":
            style = _text_style(styles, graphic.text_style)
            result["texts"].append(
                {
                    "text": graphic.text or "",
                    "xmm": _mm(graphic.points[0].x_nm),
                    "ymm": _mm(graphic.points[0].y_nm),
                    "heightMm": _mm(style.height_nm),
                    "strokeWidthMm": _mm(style.stroke_nm) or _DEFAULT_GRAPHIC_WIDTH_MM,
                    "layer": layer,
                }
            )
        else:
            raise ValueError(f"unsupported normalized footprint graphic: {graphic.kind}")
    return result


def _overall_height_mm(footprint: Footprint, source_units: str) -> float:
    value = next(
        (item.value for item in footprint.attributes if item.name.casefold() == "height"),
        "0",
    )
    try:
        height = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid P-CAD package height: {value}") from exc
    return height * (0.0254 if source_units.casefold() == "mil" else 1.0)


def build_altium_writer_request(
    library: Library,
    *,
    output_directory: Path,
    step_model: Path | None = None,
) -> dict[str, Any]:
    """Build the strict JSON value consumed by ``Stockroom.CadConverter.exe``."""
    styles = {item.name.casefold(): item for item in library.text_styles}
    symbol_graphics = _symbol_graphics(library.symbol.graphics)
    parameters = [
        {"name": item.name, "value": item.value, "visible": False}
        for item in library.symbol.attributes
    ]
    parameters.append(
        {"name": "Footprint", "value": library.default_footprint, "visible": False}
    )
    symbol = {
        "name": library.mpn,
        "description": f"{library.manufacturer} {library.mpn}",
        "designatorPrefix": library.reference_prefix,
        "partCount": 1,
        "pins": [
            {
                "designator": item.number,
                "name": item.name,
                "xmm": _mm(item.position.x_nm),
                "ymm": _mm(item.position.y_nm),
                "lengthMm": _mm(item.length_nm),
                "orientation": _pin_orientation(item.rotation_udeg),
                "electricalType": _electrical_type(item.electrical_type),
                "showName": item.show_name,
                "showDesignator": item.show_number,
                "ownerPartId": 1,
            }
            for item in library.symbol.pins
        ],
        "parameters": parameters,
        **symbol_graphics,
    }

    model_id = None
    if step_model is not None:
        step_model = step_model.resolve(strict=True)
        model_digest = hashlib.sha256(step_model.read_bytes()).digest()
        # Altium stores MODELID as a brace-delimited GUID. Its native loader rejects
        # arbitrary stable strings even though AltiumSharp can read them back.
        model_id = "{" + str(uuid.UUID(bytes=model_digest[:16])).upper() + "}"

    footprints: list[dict[str, Any]] = []
    for footprint in library.footprints:
        graphics = _footprint_graphics(footprint, styles)
        attributes = {item.name: item.value for item in footprint.attributes}
        attributes.update(
            {
                "PcadSourceSha256": library.source_sha256,
                "PcadSourceUnits": library.source_units,
            }
        )
        definition: dict[str, Any] = {
            "name": footprint.name,
            "description": f"{library.manufacturer} {library.mpn} - {footprint.name}",
            "pads": [
                {
                    "designator": item.number,
                    "xmm": _mm(item.position.x_nm),
                    "ymm": _mm(item.position.y_nm),
                    "sizeXmm": _mm(item.width_nm),
                    "sizeYmm": _mm(item.height_nm),
                    "holeSizeMm": _mm(item.hole_nm),
                    "rotation": _degrees(item.rotation_udeg),
                    "layer": 74 if item.kind == "through_hole" else 1,
                    "shape": "rectangular" if item.shape == "rect" else "round",
                    "holeType": "round",
                    "plated": item.plated,
                }
                for item in footprint.pads
            ],
            "parameters": attributes,
            **graphics,
        }
        if step_model is not None and model_id is not None:
            outline = _closed_line_outline(footprint) or _pad_outline(footprint)
            definition["model"] = {
                "path": str(step_model),
                "id": model_id,
                "name": step_model.name,
                "bodyOutline": [_point(item) for item in outline],
                "overallHeightMm": _overall_height_mm(footprint, library.source_units),
                # Altium's STEP frame is rotated 90 degrees around X relative to
                # the PCB plane. Native Altium-authored embedded bodies use the
                # same mounting transform; zero leaves a thin package edge-on.
                "rotationX": 90,
            }
        footprints.append(definition)

    return {
        "schema": REQUEST_SCHEMA,
        "outputDirectory": str(output_directory.resolve()),
        "outputStem": _output_stem(library.mpn),
        "manufacturer": library.manufacturer,
        "mpn": library.mpn,
        "defaultFootprint": library.default_footprint,
        "padPinMap": [
            {"pad": pad, "pin": pin} for pad, pin in library.pad_pin_map
        ],
        "symbol": symbol,
        "footprints": footprints,
    }


__all__ = ["REQUEST_SCHEMA", "build_altium_writer_request"]
