"""Deterministic KiCad 10 projection and semantic readback for component IR."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from stockroom.domain.component_definition import (
    NM_PER_MM,
    ComponentDefinition,
    PointNm,
    ProductionBlocker,
    TerminalDefinition,
)
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad

_SYMBOL_BODY_HALF_NM = 15_240_000
_SYMBOL_PIN_LENGTH_NM = 2_540_000
_SYMBOL_PIN_OUTER_NM = _SYMBOL_BODY_HALF_NM + _SYMBOL_PIN_LENGTH_NM
_SYMBOL_TANGENT_START_NM = -13_970_000
_SYMBOL_PIN_PITCH_NM = 2_540_000


class KiCadGenerationError(ValueError):
    """Generated KiCad bytes are malformed or disagree with the source definition."""


@dataclass(frozen=True, slots=True)
class KiCadArtifact:
    file_name: str
    content: bytes
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.file_name or self.file_name != self.file_name.strip():
            raise ValueError("artifact file name must be non-blank")
        if not self.content.endswith(b"\n"):
            raise ValueError("KiCad artifact must end in one LF")
        object.__setattr__(self, "digest", f"sha256:{hashlib.sha256(self.content).hexdigest()}")


@dataclass(frozen=True, slots=True)
class ObservedPin:
    number: str
    electrical_type: str
    center: PointNm
    rotation_udeg: int


@dataclass(frozen=True, slots=True)
class ObservedPad:
    number: str
    pad_type: str
    shape: str
    center: PointNm
    size_x_nm: int
    size_y_nm: int
    drill_diameter_nm: int


@dataclass(frozen=True, slots=True)
class KiCadComponentReadback:
    symbol_name: str
    symbol_value: str
    manufacturer: str
    mpn: str
    footprint_reference: str
    footprint_name: str
    pins: tuple[ObservedPin, ...]
    plated_pads: tuple[ObservedPad, ...]
    mounting_holes: tuple[ObservedPad, ...]
    model_path: None

    @property
    def pin_numbers(self) -> tuple[str, ...]:
        return tuple(pin.number for pin in self.pins)

    @property
    def pad_numbers(self) -> tuple[str, ...]:
        return tuple(pad.number for pad in self.plated_pads)


@dataclass(frozen=True, slots=True)
class GeneratedKiCadComponent:
    definition_digest: str
    symbol: KiCadArtifact
    footprint: KiCadArtifact
    readback: KiCadComponentReadback
    blockers: tuple[ProductionBlocker, ...]
    production_ready: bool = field(default=False, init=False)


def _nm_to_mm(value_nm: int) -> str:
    if type(value_nm) is not int:
        raise TypeError("KiCad geometry must be integer nanometres")
    sign = "-" if value_nm < 0 else ""
    whole, fraction = divmod(abs(value_nm), NM_PER_MM)
    if not fraction:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:06d}".rstrip("0")


def _udeg_to_deg(value_udeg: int) -> str:
    return _nm_to_mm(value_udeg)


def _atom_to_fixed(value: str, scale: int, field_name: str) -> int:
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise KiCadGenerationError(f"{field_name} is not a decimal number: {value!r}") from exc
    if not decimal.is_finite():
        raise KiCadGenerationError(f"{field_name} must be finite")
    scaled = decimal * scale
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise KiCadGenerationError(
            f"{field_name} is not representable at fixed-point scale {scale}"
        )
    return int(integral)


def _child_atom(node: SexpNode, name: str, index: int, field_name: str) -> str:
    child = node.find(name)
    if child is None or len(child.children) <= index:
        raise KiCadGenerationError(f"missing {field_name}")
    return child.children[index].value


def _symbol_pin_geometry(terminal: TerminalDefinition) -> tuple[PointNm, int]:
    tangent = _SYMBOL_TANGENT_START_NM + terminal.side_index * _SYMBOL_PIN_PITCH_NM
    if terminal.side == "left":
        return PointNm(-_SYMBOL_PIN_OUTER_NM, tangent), 0
    if terminal.side == "bottom":
        return PointNm(tangent, _SYMBOL_PIN_OUTER_NM), 90_000_000
    if terminal.side == "right":
        return PointNm(_SYMBOL_PIN_OUTER_NM, -tangent), 180_000_000
    return PointNm(-tangent, -_SYMBOL_PIN_OUTER_NM), 270_000_000


def _property_line(name: str, value: str, x_nm: int, y_nm: int, *, hide: bool = False) -> str:
    hidden = " (hide yes)" if hide else ""
    return (
        f"\t\t(property {quote_kicad(name)} {quote_kicad(value)} "
        f"(at {_nm_to_mm(x_nm)} {_nm_to_mm(y_nm)} 0){hidden} "
        "(effects (font (size 1.27 1.27))))"
    )


def _render_symbol(definition: ComponentDefinition) -> bytes:
    identity = definition.identity
    lines = [
        "(kicad_symbol_lib",
        "\t(version 20251024)",
        '\t(generator "stockroom")',
        '\t(generator_version "10.0")',
        f"\t(symbol {quote_kicad(identity.symbol_name)}",
        "\t\t(pin_names (offset 1.016))",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        "\t\t(in_pos_files yes)",
        "\t\t(duplicate_pin_numbers_are_jumpers no)",
        _property_line("Reference", identity.reference_prefix, 0, -19_050_000),
        _property_line("Value", identity.mpn, 0, 19_050_000),
        _property_line(
            "Footprint",
            f"Stockroom:{identity.footprint_name}",
            0,
            0,
            hide=True,
        ),
        _property_line("Datasheet", "", 0, 0, hide=True),
        _property_line("Manufacturer", identity.manufacturer, 0, 0, hide=True),
        _property_line("Manufacturer Part Number", identity.mpn, 0, 0, hide=True),
        _property_line(
            "Description",
            "48-contact Yamaichi IC test socket; provisional land pattern",
            0,
            0,
            hide=True,
        ),
        f"\t\t(symbol {quote_kicad(identity.symbol_name + '_0_1')}",
        "\t\t\t(rectangle",
        (f"\t\t\t\t(start {_nm_to_mm(-_SYMBOL_BODY_HALF_NM)} {_nm_to_mm(-_SYMBOL_BODY_HALF_NM)})"),
        (f"\t\t\t\t(end {_nm_to_mm(_SYMBOL_BODY_HALF_NM)} {_nm_to_mm(_SYMBOL_BODY_HALF_NM)})"),
        "\t\t\t\t(stroke (width 0.254) (type default))",
        "\t\t\t\t(fill (type background))",
        "\t\t\t)",
        "\t\t)",
        f"\t\t(symbol {quote_kicad(identity.symbol_name + '_1_1')}",
    ]
    for terminal in definition.terminals:
        center, rotation_udeg = _symbol_pin_geometry(terminal)
        lines.extend(
            (
                "\t\t\t(pin passive line",
                (
                    f"\t\t\t\t(at {_nm_to_mm(center.x_nm)} {_nm_to_mm(center.y_nm)} "
                    f"{_udeg_to_deg(rotation_udeg)})"
                ),
                f"\t\t\t\t(length {_nm_to_mm(_SYMBOL_PIN_LENGTH_NM)})",
                (
                    f"\t\t\t\t(name {quote_kicad('Pin ' + terminal.number)} "
                    "(effects (font (size 1.27 1.27))))"
                ),
                (
                    f"\t\t\t\t(number {quote_kicad(terminal.number)} "
                    "(effects (font (size 1.27 1.27))))"
                ),
                "\t\t\t)",
            )
        )
    lines.extend(("\t\t)", "\t)", ")", ""))
    return "\n".join(lines).encode("utf-8")


def _fp_rect(
    start: PointNm,
    end: PointNm,
    layer: str,
    width_nm: int,
) -> list[str]:
    return [
        "\t(fp_rect",
        f"\t\t(start {_nm_to_mm(start.x_nm)} {_nm_to_mm(start.y_nm)})",
        f"\t\t(end {_nm_to_mm(end.x_nm)} {_nm_to_mm(end.y_nm)})",
        f"\t\t(stroke (width {_nm_to_mm(width_nm)}) (type solid))",
        "\t\t(fill no)",
        f"\t\t(layer {quote_kicad(layer)})",
        "\t)",
    ]


def _render_footprint(definition: ComponentDefinition) -> bytes:
    identity = definition.identity
    half_width_nm = definition.body.width_nm // 2
    half_depth_nm = definition.body.depth_nm // 2
    lines = [
        f"(footprint {quote_kicad(identity.footprint_name)}",
        "\t(version 20240108)",
        '\t(generator "stockroom")',
        '\t(layer "F.Cu")',
        (
            "\t(descr "
            + quote_kicad(
                "Yamaichi Electronics IC51-0484-806, 48-contact test socket; "
                "policy-derived 1.20 mm lands; not production ready"
            )
            + ")"
        ),
        '\t(tags "IC51 test socket through-hole provisional")',
    ]
    lines.extend(
        (
            (
                f"\t(fp_text reference {quote_kicad(identity.reference_prefix)} "
                f"(at 0 {_nm_to_mm(-half_depth_nm - 1_500_000)}) "
                '(layer "F.SilkS") '
                "(effects (font (size 1 1) (thickness 0.15))))"
            ),
            (
                f"\t(fp_text value {quote_kicad(identity.mpn)} "
                f"(at 0 {_nm_to_mm(half_depth_nm + 1_500_000)}) "
                '(layer "F.Fab") '
                "(effects (font (size 1 1) (thickness 0.15))))"
            ),
        )
    )
    lines.append("\t(attr through_hole)")
    lines.extend(
        _fp_rect(
            PointNm(-half_width_nm, -half_depth_nm),
            PointNm(half_width_nm, half_depth_nm),
            "F.Fab",
            100_000,
        )
    )
    lines.extend(
        _fp_rect(
            PointNm(-half_width_nm, -half_depth_nm),
            PointNm(half_width_nm, half_depth_nm),
            "F.SilkS",
            120_000,
        )
    )
    lines.extend(
        _fp_rect(
            PointNm(-half_width_nm - 250_000, -half_depth_nm - 250_000),
            PointNm(half_width_nm + 250_000, half_depth_nm + 250_000),
            "F.CrtYd",
            50_000,
        )
    )
    lines.extend(
        (
            "\t(fp_circle",
            "\t\t(center -8.75 -8.75)",
            "\t\t(end -8.15 -8.75)",
            "\t\t(stroke (width 0.3) (type solid))",
            "\t\t(fill no)",
            '\t\t(layer "F.SilkS")',
            "\t)",
        )
    )
    for terminal in definition.terminals:
        lines.append(
            (
                f"\t(pad {quote_kicad(terminal.number)} thru_hole circle "
                f"(at {_nm_to_mm(terminal.center.x_nm)} {_nm_to_mm(terminal.center.y_nm)}) "
                f"(size {_nm_to_mm(terminal.land_diameter_nm)} "
                f"{_nm_to_mm(terminal.land_diameter_nm)}) "
                f"(drill {_nm_to_mm(terminal.drill_diameter_nm)}) "
                '(layers "*.Cu" "*.Mask"))'
            )
        )
    for hole in definition.mounting_holes:
        diameter = _nm_to_mm(hole.drill_diameter_nm)
        lines.append(
            (
                '\t(pad "" np_thru_hole circle '
                f"(at {_nm_to_mm(hole.center.x_nm)} {_nm_to_mm(hole.center.y_nm)}) "
                f"(size {diameter} {diameter}) (drill {diameter}) "
                '(layers "*.Cu" "*.Mask"))'
            )
        )
    lines.extend((")", ""))
    return "\n".join(lines).encode("utf-8")


def _property_value(symbol: SexpNode, name: str) -> str:
    for node in symbol.find_all("property"):
        children = node.children
        if len(children) >= 3 and children[1].value == name:
            return children[2].value
    raise KiCadGenerationError(f"symbol property {name!r} is missing")


def _point_from_at(node: SexpNode, field_name: str) -> PointNm:
    at = node.find("at")
    if at is None or len(at.children) < 3:
        raise KiCadGenerationError(f"{field_name} has no center")
    return PointNm(
        _atom_to_fixed(at.children[1].value, NM_PER_MM, f"{field_name} x"),
        _atom_to_fixed(at.children[2].value, NM_PER_MM, f"{field_name} y"),
    )


def _read_symbol(symbol_bytes: bytes) -> tuple[str, str, str, str, str, tuple[ObservedPin, ...]]:
    try:
        document = SexpDocument.parse(symbol_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KiCadGenerationError(f"invalid KiCad symbol library: {exc}") from exc
    if document.root.name != "kicad_symbol_lib":
        raise KiCadGenerationError("symbol artifact is not a kicad_symbol_lib")
    symbols = document.root.find_all("symbol")
    if len(symbols) != 1:
        raise KiCadGenerationError("symbol library must contain exactly one top-level symbol")
    symbol = symbols[0]
    if len(symbol.children) < 2:
        raise KiCadGenerationError("symbol has no name")
    pins: list[ObservedPin] = []
    for node in symbol.iter_descendants():
        if node.name != "pin":
            continue
        children = node.children
        if len(children) < 2:
            raise KiCadGenerationError("symbol pin is missing its electrical type")
        number = _child_atom(node, "number", 1, "symbol pin number")
        at = node.find("at")
        if at is None or len(at.children) < 4:
            raise KiCadGenerationError(f"symbol pin {number!r} has no complete position")
        pins.append(
            ObservedPin(
                number=number,
                electrical_type=children[1].value,
                center=_point_from_at(node, f"symbol pin {number!r}"),
                rotation_udeg=_atom_to_fixed(
                    at.children[3].value,
                    1_000_000,
                    f"symbol pin {number!r} rotation",
                ),
            )
        )
    return (
        symbol.children[1].value,
        _property_value(symbol, "Value"),
        _property_value(symbol, "Manufacturer"),
        _property_value(symbol, "Manufacturer Part Number"),
        _property_value(symbol, "Footprint"),
        tuple(pins),
    )


def _read_pad(node: SexpNode, index: int) -> ObservedPad:
    children = node.children
    if len(children) < 4:
        raise KiCadGenerationError(f"footprint pad {index} has an incomplete header")
    number = children[1].value
    size = node.find("size")
    if size is None or len(size.children) < 3:
        raise KiCadGenerationError(f"footprint pad {number!r} has no size")
    drill = node.find("drill")
    if drill is None or len(drill.children) < 2:
        raise KiCadGenerationError(f"footprint pad {number!r} has no drill")
    return ObservedPad(
        number=number,
        pad_type=children[2].value,
        shape=children[3].value,
        center=_point_from_at(node, f"footprint pad {number!r}"),
        size_x_nm=_atom_to_fixed(
            size.children[1].value,
            NM_PER_MM,
            f"footprint pad {number!r} width",
        ),
        size_y_nm=_atom_to_fixed(
            size.children[2].value,
            NM_PER_MM,
            f"footprint pad {number!r} height",
        ),
        drill_diameter_nm=_atom_to_fixed(
            drill.children[1].value,
            NM_PER_MM,
            f"footprint pad {number!r} drill",
        ),
    )


def _read_footprint(
    footprint_bytes: bytes,
) -> tuple[str, tuple[ObservedPad, ...], tuple[ObservedPad, ...], None]:
    try:
        document = SexpDocument.parse(footprint_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KiCadGenerationError(f"invalid KiCad footprint: {exc}") from exc
    root = document.root
    if root.name != "footprint" or len(root.children) < 2:
        raise KiCadGenerationError("footprint artifact is not a named footprint")
    pads = tuple(_read_pad(node, index) for index, node in enumerate(root.find_all("pad")))
    plated = tuple(pad for pad in pads if pad.pad_type == "thru_hole")
    holes = tuple(pad for pad in pads if pad.pad_type == "np_thru_hole")
    unknown = tuple(pad for pad in pads if pad.pad_type not in {"thru_hole", "np_thru_hole"})
    if unknown:
        raise KiCadGenerationError("footprint contains pads outside the PTH/NPTH definition")
    if any(node.name == "model" for node in root.iter_descendants()):
        raise KiCadGenerationError("footprint unexpectedly contains a 3D model")
    return root.children[1].value, plated, holes, None


def readback_kicad_component(
    symbol_bytes: bytes,
    footprint_bytes: bytes,
) -> KiCadComponentReadback:
    """Parse generated bytes through Stockroom's repository S-expression layer."""

    (
        symbol_name,
        symbol_value,
        manufacturer,
        mpn,
        footprint_reference,
        pins,
    ) = _read_symbol(symbol_bytes)
    footprint_name, plated_pads, mounting_holes, model_path = _read_footprint(footprint_bytes)
    return KiCadComponentReadback(
        symbol_name=symbol_name,
        symbol_value=symbol_value,
        manufacturer=manufacturer,
        mpn=mpn,
        footprint_reference=footprint_reference,
        footprint_name=footprint_name,
        pins=pins,
        plated_pads=plated_pads,
        mounting_holes=mounting_holes,
        model_path=model_path,
    )


def verify_kicad_readback(
    definition: ComponentDefinition,
    readback: KiCadComponentReadback,
) -> None:
    """Fail closed unless identity, terminals, land pattern, holes, and model agree."""

    identity = definition.identity
    observed_identity = (
        readback.manufacturer,
        readback.mpn,
        readback.symbol_name,
        readback.symbol_value,
        readback.footprint_reference,
        readback.footprint_name,
    )
    expected_identity = (
        identity.manufacturer,
        identity.mpn,
        identity.symbol_name,
        identity.mpn,
        f"Stockroom:{identity.footprint_name}",
        identity.footprint_name,
    )
    if observed_identity != expected_identity:
        raise KiCadGenerationError(f"KiCad exact identity readback differs: {observed_identity!r}")

    expected_pins = tuple(
        ObservedPin(
            number=terminal.number,
            electrical_type=terminal.electrical_type,
            center=_symbol_pin_geometry(terminal)[0],
            rotation_udeg=_symbol_pin_geometry(terminal)[1],
        )
        for terminal in definition.terminals
    )
    if readback.pins != expected_pins:
        raise KiCadGenerationError("KiCad symbol pin numbers, types, or centers differ")

    expected_pads = tuple(
        ObservedPad(
            number=terminal.number,
            pad_type="thru_hole",
            shape="circle",
            center=terminal.center,
            size_x_nm=terminal.land_diameter_nm,
            size_y_nm=terminal.land_diameter_nm,
            drill_diameter_nm=terminal.drill_diameter_nm,
        )
        for terminal in definition.terminals
    )
    if readback.plated_pads != expected_pads:
        raise KiCadGenerationError(
            "KiCad PTH pad numbers, centers, land sizes, or drill sizes differ"
        )

    expected_holes = tuple(
        ObservedPad(
            number="",
            pad_type="np_thru_hole",
            shape="circle",
            center=hole.center,
            size_x_nm=hole.drill_diameter_nm,
            size_y_nm=hole.drill_diameter_nm,
            drill_diameter_nm=hole.drill_diameter_nm,
        )
        for hole in definition.mounting_holes
    )
    if readback.mounting_holes != expected_holes:
        raise KiCadGenerationError("KiCad NPTH positions or drill sizes differ")
    if definition.model is not None or readback.model_path is not None:
        raise KiCadGenerationError("unqualified component must not project a 3D model")
    if definition.production_ready or not definition.blockers:
        raise KiCadGenerationError("unqualified component lost its production blockers")


def generate_kicad_component(
    definition: ComponentDefinition,
) -> GeneratedKiCadComponent:
    """Render stable library bytes, parse them back, and return only verified output."""

    symbol = KiCadArtifact(
        file_name=f"{definition.identity.symbol_name}.kicad_sym",
        content=_render_symbol(definition),
    )
    footprint = KiCadArtifact(
        file_name=f"{definition.identity.footprint_name}.kicad_mod",
        content=_render_footprint(definition),
    )
    readback = readback_kicad_component(symbol.content, footprint.content)
    verify_kicad_readback(definition, readback)
    return GeneratedKiCadComponent(
        definition_digest=definition.canonical_digest(),
        symbol=symbol,
        footprint=footprint,
        readback=readback,
        blockers=definition.blockers,
    )
