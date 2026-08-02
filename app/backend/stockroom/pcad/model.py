"""Lossless-enough provider CAD model used by the native writer sidecar."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x_nm: int
    y_nm: int


@dataclass(frozen=True, slots=True)
class TextStyle:
    name: str
    font_type: str
    family: str
    face: str
    height_nm: int
    stroke_nm: int


@dataclass(frozen=True, slots=True)
class Graphic:
    kind: str
    layer_number: int | None
    points: tuple[Point, ...] = ()
    width_nm: int = 0
    radius_nm: int = 0
    start_angle_udeg: int = 0
    sweep_angle_udeg: int = 0
    text: str | None = None
    text_style: str | None = None
    justify: str | None = None


@dataclass(frozen=True, slots=True)
class Attribute:
    name: str
    value: str
    layer_number: int | None = None


@dataclass(frozen=True, slots=True)
class Pin:
    number: str
    name: str
    part: int
    electrical_type: str
    position: Point
    length_nm: int
    rotation_udeg: int
    show_name: bool
    show_number: bool


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    pins: tuple[Pin, ...]
    graphics: tuple[Graphic, ...]
    attributes: tuple[Attribute, ...]


@dataclass(frozen=True, slots=True)
class Pad:
    number: str
    style_name: str
    kind: str
    shape: str
    position: Point
    width_nm: int
    height_nm: int
    rotation_udeg: int
    hole_nm: int
    plated: bool


@dataclass(frozen=True, slots=True)
class Footprint:
    name: str
    default: bool
    pads: tuple[Pad, ...]
    graphics: tuple[Graphic, ...]
    attributes: tuple[Attribute, ...]


@dataclass(frozen=True, slots=True)
class Library:
    source_sha256: str
    source_units: str
    name: str
    manufacturer: str
    mpn: str
    reference_prefix: str
    symbol: Symbol
    footprints: tuple[Footprint, ...]
    default_footprint: str
    pad_pin_map: tuple[tuple[str, str], ...]
    text_styles: tuple[TextStyle, ...]
