"""Fail-closed native readback for one browser-delivered dual-EDA component.

This module does not infer correctness from file names.  It reads the selected
KiCad symbol and footprint, the native Altium component and footprint streams,
and the STEP geometry.  A result is valid only when identity, terminal mapping,
pad multiplicity, and rotation/translation/reflection-invariant pad geometry
all agree.

The Altium binary readers intentionally recognize only the record layouts that
Stockroom can prove.  An unfamiliar vendor/version is rejected for review
rather than accepted from a partial parse.
"""

from __future__ import annotations

import hashlib
import math
import struct
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import olefile

from stockroom.altium.extract import extract_intlib
from stockroom.altium.native_authoring import read_embedded_model_payloads
from stockroom.altium.oleread import pick_entry, read_footprint_names, read_symbol_names
from stockroom.kicad.footprint import Footprint, Pad
from stockroom.kicad.model_convert import model_to_glb
from stockroom.planning import ExactPartIdentity
from stockroom.sexp.document import SexpDocument, SexpNode

_ALTIUM_PAD_TRAILER = b"\x01\x00\x00\x00\x00\x05\x00\x00\x00\x04|&|0"
_ALTIUM_COORDINATE_TO_MM = 2.54e-6
_GEOMETRY_ABSOLUTE_TOLERANCE_MM = 0.05
_GEOMETRY_RELATIVE_TOLERANCE = 0.01

_MANUFACTURER_FIELDS = (
    "manufacturer",
    "manufacturer name",
    "mf",
)
_MPN_FIELDS = (
    "manufacturer part number",
    "manufacturer part number 1",
    "part number",
    "partnumber",
    "mpn",
    "mp",
)


class CrossEdaVerificationError(ValueError):
    """The artifacts cannot prove one coherent dual-EDA component."""


@dataclass(frozen=True, slots=True)
class _Pin:
    number: str
    name: str


@dataclass(frozen=True, slots=True)
class _PadGeometry:
    number: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class _SymbolReadback:
    entry: str
    manufacturer: str
    mpn: str
    pins: tuple[_Pin, ...]


@dataclass(frozen=True, slots=True)
class _FootprintReadback:
    entry: str
    pads: tuple[_PadGeometry, ...]
    model_path: str | None = None


def _mpn_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _manufacturer_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _pin_name_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _is_no_connect_name(value: str) -> bool:
    key = "".join(character for character in _pin_name_key(value) if character.isalnum())
    return key in {"nc", "noconnect", "donotconnect", "dnc"}


def _field(properties: dict[str, str], aliases: tuple[str, ...]) -> str:
    normalized = {
        unicodedata.normalize("NFKC", key).strip().casefold(): value.strip()
        for key, value in properties.items()
        if value.strip()
    }
    found = {normalized[alias] for alias in aliases if alias in normalized}
    if not found:
        return ""
    if len({_mpn_key(value) for value in found}) != 1:
        raise CrossEdaVerificationError(
            f"conflicting identity fields are present: {sorted(found)!r}"
        )
    return sorted(found, key=lambda value: (_mpn_key(value), value))[0]


def _verify_identity(
    observed: _SymbolReadback,
    expected: ExactPartIdentity,
    tool: str,
    attested: ExactPartIdentity | None = None,
) -> tuple[str, ...]:
    missing: list[str] = []
    if observed.manufacturer and _manufacturer_key(
        observed.manufacturer
    ) != _manufacturer_key(expected.authoritative_manufacturer_key):
        raise CrossEdaVerificationError(
            f"{tool} symbol manufacturer {observed.manufacturer!r} does not equal "
            f"{expected.authoritative_manufacturer_key!r}"
        )
    if observed.mpn and _mpn_key(observed.mpn) != _mpn_key(expected.mpn_canonical):
        raise CrossEdaVerificationError(
            f"{tool} symbol MPN {observed.mpn!r} does not equal {expected.mpn_canonical!r}"
        )
    if not observed.manufacturer:
        missing.append("manufacturer")
    if not observed.mpn:
        missing.append("mpn")
    if not missing:
        return ()
    if attested is None:
        raise CrossEdaVerificationError(
            f"{tool} symbol does not carry both manufacturer and MPN identity"
        )
    if _manufacturer_key(attested.authoritative_manufacturer_key) != _manufacturer_key(
        expected.authoritative_manufacturer_key
    ) or _mpn_key(attested.mpn_canonical) != _mpn_key(expected.mpn_canonical):
        raise CrossEdaVerificationError(
            f"{tool} symbol's missing identity is not covered by an exact provider attestation"
        )
    return tuple(missing)


def _unique_pins(pins: list[_Pin], tool: str) -> tuple[_Pin, ...]:
    by_number: dict[str, str] = {}
    for pin in pins:
        if not pin.number.strip():
            raise CrossEdaVerificationError(f"{tool} symbol has an unnumbered pin")
        prior = by_number.setdefault(pin.number, pin.name)
        if prior != pin.name:
            raise CrossEdaVerificationError(
                f"{tool} pin {pin.number!r} has conflicting names {prior!r} and {pin.name!r}"
            )
    if not by_number:
        raise CrossEdaVerificationError(f"{tool} symbol has no readable pins")
    return tuple(_Pin(number, name) for number, name in sorted(by_number.items()))


def _node_field(node: SexpNode, name: str) -> str:
    child = node.find(name)
    if child is None or len(child.children) < 2:
        return ""
    return child.children[1].value


def read_kicad_symbol(path: Path, preferred_entry: str) -> _SymbolReadback:
    """Read one unambiguous KiCad symbol and its physical pin definitions."""

    document = SexpDocument.load(path)
    if document.root.name != "kicad_symbol_lib":
        raise CrossEdaVerificationError(f"{path.name} is not a KiCad symbol library")
    entries = [node for node in document.root.find_all("symbol") if len(node.children) >= 2]
    entry_name = pick_entry(
        [node.children[1].value for node in entries],
        "KiCad symbol",
        preferred_entry,
    )
    selected = next(node for node in entries if node.children[1].value == entry_name)
    properties: dict[str, str] = {}
    for prop in selected.find_all("property"):
        if len(prop.children) >= 3:
            properties[prop.children[1].value] = prop.children[2].value
    pins: list[_Pin] = []
    for node in selected.iter_descendants():
        if node.name != "pin":
            continue
        pins.append(_Pin(_node_field(node, "number"), _node_field(node, "name")))
    return _SymbolReadback(
        entry=entry_name,
        manufacturer=_field(properties, _MANUFACTURER_FIELDS),
        mpn=_field(properties, _MPN_FIELDS)
        or (entry_name if _mpn_key(entry_name) == _mpn_key(preferred_entry) else ""),
        pins=_unique_pins(pins, "KiCad"),
    )


def read_kicad_footprint(path: Path, step_model: Path) -> _FootprintReadback:
    footprint = Footprint.load(path)
    pads = tuple(
        _PadGeometry(
            number=pad.number,
            x_mm=pad.at[0],
            y_mm=pad.at[1],
            width_mm=pad.size[0],
            height_mm=pad.size[1],
        )
        for pad in footprint.pads
    )
    _validate_pads(pads, "KiCad")
    model_path = footprint.model_path
    if model_path and Path(model_path).name.casefold() != step_model.name.casefold():
        raise CrossEdaVerificationError(
            f"KiCad footprint links {Path(model_path).name!r}, not {step_model.name!r}"
        )
    return _FootprintReadback(entry=footprint.name, pads=pads, model_path=model_path)


def _pipe_record(payload: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    utf8: set[str] = set()
    for item in payload.rstrip(b"\x00").split(b"|"):
        if not item or b"=" not in item:
            continue
        raw_key, raw_value = item.split(b"=", 1)
        key = raw_key.decode("latin-1").strip().upper()
        if key.startswith("%UTF8%"):
            key = key.removeprefix("%UTF8%")
            fields[key] = raw_value.decode("utf-8", errors="strict")
            utf8.add(key)
        elif key not in utf8:
            fields[key] = raw_value.decode("latin-1")
    return fields


def _pascal_string(payload: bytes, offset: int, label: str) -> tuple[str, int]:
    if offset >= len(payload):
        raise CrossEdaVerificationError(f"Altium {label} is truncated")
    length = payload[offset]
    end = offset + 1 + length
    if not length or end > len(payload):
        raise CrossEdaVerificationError(f"Altium {label} length is invalid")
    raw = payload[offset + 1 : end]
    if any(byte < 0x20 for byte in raw):
        raise CrossEdaVerificationError(f"Altium {label} contains control bytes")
    return raw.decode("latin-1"), end


def _read_altium_symbol_stream(raw: bytes, entry: str) -> _SymbolReadback:
    records: list[dict[str, str]] = []
    pins: list[_Pin] = []
    offset = 0
    while offset + 4 <= len(raw):
        word = struct.unpack_from("<I", raw, offset)[0]
        length = word & 0x00FFFFFF
        record_type = word >> 24
        offset += 4
        if not length or offset + length > len(raw):
            raise CrossEdaVerificationError("Altium SchLib component stream is truncated")
        payload = raw[offset : offset + length]
        offset += length
        if record_type == 0:
            records.append(_pipe_record(payload))
        elif record_type == 1:
            if len(payload) < 28:
                raise CrossEdaVerificationError("Altium binary pin record is truncated")
            name, cursor = _pascal_string(payload, 26, "pin name")
            number, _cursor = _pascal_string(payload, cursor, "pin number")
            pins.append(_Pin(number=number, name=name))
        else:
            raise CrossEdaVerificationError(
                f"Altium SchLib record type {record_type} is not supported"
            )
    if offset != len(raw) or not records:
        raise CrossEdaVerificationError("Altium SchLib component stream has trailing bytes")
    component = records[0]
    if component.get("RECORD") != "1":
        raise CrossEdaVerificationError("Altium SchLib has no component header")
    library_reference = component.get("LIBREFERENCE", "")
    if library_reference != entry:
        raise CrossEdaVerificationError(
            f"Altium component stream is {library_reference!r}, not {entry!r}"
        )
    try:
        declared_count = int(component.get("ALLPINCOUNT", ""))
    except ValueError as exc:
        raise CrossEdaVerificationError("Altium SchLib has no valid pin count") from exc
    observed_pins = _unique_pins(pins, "Altium")
    if declared_count != len(observed_pins):
        raise CrossEdaVerificationError(
            f"Altium SchLib declares {declared_count} pins but exposes "
            f"{len(observed_pins)} unique numbered pins"
        )
    properties = {
        record.get("NAME", ""): record.get("TEXT", "")
        for record in records
        if record.get("RECORD") == "41" and record.get("NAME")
    }
    return _SymbolReadback(
        entry=entry,
        manufacturer=_field(properties, _MANUFACTURER_FIELDS),
        mpn=_field(properties, _MPN_FIELDS) or (entry if _mpn_key(entry) else ""),
        pins=observed_pins,
    )


def read_altium_symbol(path: Path, preferred_entry: str) -> _SymbolReadback:
    entry = pick_entry(read_symbol_names(path), "Altium symbol", preferred_entry)
    with olefile.OleFileIO(str(path)) as container:
        stream = [entry, "Data"]
        if not container.exists(stream):
            raise CrossEdaVerificationError(
                f"Altium SchLib entry {entry!r} has no component Data stream"
            )
        return _read_altium_symbol_stream(container.openstream(stream).read(), entry)


def _read_altium_pad_stream(raw: bytes, entry: str) -> tuple[_PadGeometry, ...]:
    if len(raw) < 5:
        raise CrossEdaVerificationError("Altium PcbLib component stream is truncated")
    name_length = struct.unpack_from("<I", raw, 0)[0]
    if name_length < 2 or 4 + name_length > len(raw):
        raise CrossEdaVerificationError("Altium PcbLib component name is invalid")
    name_payload = raw[4 : 4 + name_length]
    if name_payload[0] != name_length - 1:
        raise CrossEdaVerificationError("Altium PcbLib component name length is invalid")
    observed_name = name_payload[1:].decode("latin-1")
    if observed_name != entry:
        raise CrossEdaVerificationError(
            f"Altium PcbLib component stream is {observed_name!r}, not {entry!r}"
        )

    pads: list[_PadGeometry] = []
    cursor = 4 + name_length
    while cursor < len(raw) - 7:
        if raw[cursor] != 2:
            cursor += 1
            continue
        field_length = struct.unpack_from("<I", raw, cursor + 1)[0]
        if not 2 <= field_length <= 65:
            cursor += 1
            continue
        payload_end = cursor + 5 + field_length
        trailer_end = payload_end + len(_ALTIUM_PAD_TRAILER)
        if trailer_end > len(raw) or raw[payload_end:trailer_end] != _ALTIUM_PAD_TRAILER:
            cursor += 1
            continue
        payload = raw[cursor + 5 : payload_end]
        if payload[0] != field_length - 1:
            cursor += 1
            continue
        number = payload[1:].decode("latin-1")
        geometry = trailer_end
        if geometry + 38 > len(raw) or raw[geometry] != 1:
            raise CrossEdaVerificationError(
                f"Altium pad {number!r} uses an unsupported binary geometry record"
            )
        record_length = struct.unpack_from("<I", raw, geometry + 5)[0]
        if record_length < 38 or geometry + 9 + record_length > len(raw):
            raise CrossEdaVerificationError(f"Altium pad {number!r} geometry record is truncated")
        x, y, width, height = struct.unpack_from("<iiii", raw, geometry + 22)
        pads.append(
            _PadGeometry(
                number=number,
                x_mm=x * _ALTIUM_COORDINATE_TO_MM,
                y_mm=y * _ALTIUM_COORDINATE_TO_MM,
                width_mm=width * _ALTIUM_COORDINATE_TO_MM,
                height_mm=height * _ALTIUM_COORDINATE_TO_MM,
            )
        )
        cursor = geometry + 9 + record_length
    return tuple(pads)


def read_altium_footprint(path: Path, preferred_entry: str) -> _FootprintReadback:
    entry = pick_entry(read_footprint_names(path), "Altium footprint", preferred_entry)
    with olefile.OleFileIO(str(path)) as container:
        stream = [entry, "Data"]
        if not container.exists(stream):
            raise CrossEdaVerificationError(
                f"Altium PcbLib entry {entry!r} has no component Data stream"
            )
        pads = _read_altium_pad_stream(container.openstream(stream).read(), entry)
    _validate_pads(pads, "Altium")
    return _FootprintReadback(entry=entry, pads=pads)


def _validate_pads(pads: tuple[_PadGeometry, ...], tool: str) -> None:
    if not pads:
        raise CrossEdaVerificationError(f"{tool} footprint has no readable pads")
    for pad in pads:
        if not pad.number.strip():
            raise CrossEdaVerificationError(f"{tool} footprint has an unnumbered pad")
        values = (pad.x_mm, pad.y_mm, pad.width_mm, pad.height_mm)
        if not all(math.isfinite(value) for value in values):
            raise CrossEdaVerificationError(f"{tool} footprint pad geometry is not finite")
        if pad.width_mm <= 0 or pad.height_mm <= 0:
            raise CrossEdaVerificationError(
                f"{tool} footprint pad {pad.number!r} has non-positive dimensions"
            )


def _terminal_map(
    kicad: _SymbolReadback,
    altium: _SymbolReadback,
) -> tuple[dict[str, str], set[str], set[str]]:
    """Map represented electrical terminals while retaining explicit NC package pads."""

    kicad_nc = {pin.number for pin in kicad.pins if _is_no_connect_name(pin.name)}
    altium_nc = {pin.number for pin in altium.pins if _is_no_connect_name(pin.name)}
    kicad_by_number = {
        pin.number: pin for pin in kicad.pins if pin.number not in kicad_nc
    }
    altium_by_number = {
        pin.number: pin for pin in altium.pins if pin.number not in altium_nc
    }
    if len(kicad_by_number) != len(altium_by_number):
        raise CrossEdaVerificationError(
            f"KiCad exposes {len(kicad_by_number)} connected pins but Altium exposes "
            f"{len(altium_by_number)}"
        )
    if set(kicad_by_number) == set(altium_by_number):
        return (
            {number: number for number in sorted(kicad_by_number)},
            kicad_nc,
            altium_nc,
        )

    kicad_by_name: dict[str, list[str]] = defaultdict(list)
    altium_by_name: dict[str, list[str]] = defaultdict(list)
    for pin in kicad_by_number.values():
        kicad_by_name[_pin_name_key(pin.name)].append(pin.number)
    for pin in altium_by_number.values():
        altium_by_name[_pin_name_key(pin.name)].append(pin.number)
    if "" in kicad_by_name or "" in altium_by_name or set(kicad_by_name) != set(altium_by_name):
        raise CrossEdaVerificationError(
            "KiCad and Altium pin numbers differ and pin names do not prove a mapping"
        )
    mapping: dict[str, str] = {}
    for name in sorted(kicad_by_name):
        kicad_numbers = kicad_by_name[name]
        altium_numbers = altium_by_name[name]
        if len(kicad_numbers) != 1 or len(altium_numbers) != 1:
            raise CrossEdaVerificationError(
                f"pin name {name!r} is not unique across both EDA symbols"
            )
        mapping[kicad_numbers[0]] = altium_numbers[0]
    return mapping, kicad_nc, altium_nc


def _close(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=_GEOMETRY_RELATIVE_TOLERANCE,
        abs_tol=_GEOMETRY_ABSOLUTE_TOLERANCE_MM,
    )


def _distance_signature(
    pads: tuple[_PadGeometry, ...],
    labels: dict[str, str],
) -> dict[tuple[str, str], list[float]]:
    signature: dict[tuple[str, str], list[float]] = defaultdict(list)
    for index, first in enumerate(pads):
        for second in pads[index + 1 :]:
            first_label = labels[first.number]
            second_label = labels[second.number]
            label = (
                (first_label, second_label)
                if first_label <= second_label
                else (second_label, first_label)
            )
            signature[label].append(math.hypot(first.x_mm - second.x_mm, first.y_mm - second.y_mm))
    return {key: sorted(values) for key, values in signature.items()}


def _size_signature(
    pads: tuple[_PadGeometry, ...],
    labels: dict[str, str],
) -> dict[str, list[tuple[float, float]]]:
    signature: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pad in pads:
        first_size, second_size = sorted((pad.width_mm, pad.height_mm))
        signature[labels[pad.number]].append((first_size, second_size))
    return {key: sorted(values) for key, values in signature.items()}


def _verify_geometry(
    kicad_pads: tuple[_PadGeometry, ...],
    altium_pads: tuple[_PadGeometry, ...],
    terminal_map: dict[str, str],
    *,
    kicad_no_connects: set[str],
    altium_no_connects: set[str],
) -> dict[str, str]:
    kicad_counts = Counter(pad.number for pad in kicad_pads)
    altium_counts = Counter(pad.number for pad in altium_pads)
    physical_map = dict(terminal_map)
    # One symbol may omit package NC pins while both footprints retain their physical pads. The
    # other symbol's explicit NC number plus an equal-number pad on both sides is the only safe
    # additional mapping.
    for number in sorted(kicad_no_connects | altium_no_connects):
        if (
            number in kicad_counts
            and number in altium_counts
            and number not in physical_map
            and number not in physical_map.values()
        ):
            physical_map[number] = number
    # Some native libraries omit package-only pads from both symbols (typically NC terminals)
    # while retaining them in both footprints. Accept only the exact same unused pad numbers on
    # both sides; this proves package equivalence without inventing an electrical terminal.
    unmatched_kicad = set(kicad_counts) - set(physical_map)
    unmatched_altium = set(altium_counts) - set(physical_map.values())
    if unmatched_kicad == unmatched_altium:
        for number in sorted(unmatched_kicad):
            physical_map[number] = number
    if set(kicad_counts) != set(physical_map):
        raise CrossEdaVerificationError(
            "KiCad footprint pad numbers do not equal its symbol pin numbers"
        )
    if set(altium_counts) != set(physical_map.values()):
        raise CrossEdaVerificationError(
            "Altium footprint pad numbers do not equal its symbol pin numbers"
        )
    for kicad_number, altium_number in physical_map.items():
        if kicad_counts[kicad_number] != altium_counts[altium_number]:
            raise CrossEdaVerificationError(
                f"physical pad multiplicity differs for mapped terminals "
                f"{kicad_number!r}/{altium_number!r}"
            )

    canonical = {number: number for number in physical_map}
    altium_canonical = {
        native: canonical_number for canonical_number, native in physical_map.items()
    }
    left_distances = _distance_signature(kicad_pads, canonical)
    right_distances = _distance_signature(altium_pads, altium_canonical)
    if set(left_distances) != set(right_distances):
        raise CrossEdaVerificationError("KiCad and Altium pad topology differs")
    for key in sorted(left_distances):
        left = left_distances[key]
        right = right_distances[key]
        if len(left) != len(right) or any(
            not _close(a, b) for a, b in zip(left, right, strict=True)
        ):
            raise CrossEdaVerificationError(
                f"KiCad and Altium pad spacing differs for terminals {key!r}"
            )

    left_sizes = _size_signature(kicad_pads, canonical)
    right_sizes = _size_signature(altium_pads, altium_canonical)
    if set(left_sizes) != set(right_sizes):
        raise CrossEdaVerificationError("KiCad and Altium pad size topology differs")
    for key in sorted(left_sizes):
        left = left_sizes[key]
        right = right_sizes[key]
        if len(left) != len(right):
            raise CrossEdaVerificationError(
                f"KiCad and Altium pad counts differ for terminal {key!r}"
            )
        for left_size, right_size in zip(left, right, strict=True):
            if not all(_close(a, b) for a, b in zip(left_size, right_size, strict=True)):
                raise CrossEdaVerificationError(
                    f"KiCad and Altium pad dimensions differ for terminal {key!r}"
                )
    return physical_map


def _verify_step(path: Path) -> dict[str, object]:
    if path.suffix.casefold() not in {".step", ".stp"}:
        raise CrossEdaVerificationError("3D model is not a STEP file")
    data = path.read_bytes()
    stripped = data.lstrip()
    if not stripped.startswith(b"ISO-10303-21;") or b"END-ISO-10303-21;" not in stripped[-256:]:
        raise CrossEdaVerificationError("STEP exchange structure is incomplete")
    try:
        glb = model_to_glb(path)
    except Exception as exc:
        raise CrossEdaVerificationError(
            f"STEP model did not produce readable geometry: {exc}"
        ) from exc
    return {
        "geometry_reader": "cascadio",
        "glb_size_bytes": len(glb),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _resolve_altium_sources(
    sources: tuple[Path, ...],
    extraction_root: Path,
) -> tuple[Path, Path]:
    schlibs = [path for path in sources if path.suffix.casefold() == ".schlib"]
    pcblibs = [path for path in sources if path.suffix.casefold() == ".pcblib"]
    intlibs = [path for path in sources if path.suffix.casefold() == ".intlib"]
    if len(schlibs) > 1 or len(pcblibs) > 1 or len(intlibs) > 1:
        raise CrossEdaVerificationError("multiple native Altium libraries are ambiguous")
    if intlibs:
        if schlibs or pcblibs:
            raise CrossEdaVerificationError(
                "mixed loose and integrated Altium libraries are ambiguous"
            )
        try:
            return extract_intlib(intlibs[0], extraction_root)
        except ValueError as exc:
            raise CrossEdaVerificationError(str(exc)) from exc
    if len(schlibs) != 1 or len(pcblibs) != 1:
        raise CrossEdaVerificationError(
            "cross-EDA verification requires exactly one SchLib and one PcbLib"
        )
    return schlibs[0], pcblibs[0]


def verify_kicad_component(
    *,
    identity: ExactPartIdentity,
    kicad_symbol: Path,
    kicad_footprint: Path,
    step_model: Path,
    allowed_unrepresented_pads: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Prove the minimum complete KiCad artifact set through native readback."""

    kicad_symbol = Path(kicad_symbol)
    kicad_footprint = Path(kicad_footprint)
    step_model = Path(step_model)
    for path in (kicad_symbol, kicad_footprint, step_model):
        if not path.is_file() or path.is_symlink():
            raise CrossEdaVerificationError(f"CAD evidence is missing or linked: {path}")
    symbol = read_kicad_symbol(kicad_symbol, identity.mpn_canonical)
    _verify_identity(symbol, identity, "KiCad")
    footprint = read_kicad_footprint(kicad_footprint, step_model)
    pin_numbers = {pin.number for pin in symbol.pins}
    pad_numbers = {pad.number for pad in footprint.pads}
    if pin_numbers & allowed_unrepresented_pads:
        raise CrossEdaVerificationError(
            "KiCad represented pins cannot also be declared unrepresented package pads"
        )
    if pin_numbers | allowed_unrepresented_pads != pad_numbers:
        raise CrossEdaVerificationError(
            "KiCad footprint pad numbers do not equal its symbol pin numbers"
        )
    step = _verify_step(step_model)
    return {
        "footprint_entry": footprint.entry,
        "model_link": "provider-supplied" if footprint.model_path else "installed-during-attach",
        "model_path": footprint.model_path,
        "pad_count": len(footprint.pads),
        "pin_count": len(symbol.pins),
        "schema": "stockroom.kicad-artifact-verification/1",
        "step": step,
        "symbol_entry": symbol.entry,
        "unrepresented_pad_numbers": sorted(allowed_unrepresented_pads),
        "valid": True,
    }


def verify_cross_eda_component(
    *,
    identity: ExactPartIdentity,
    kicad_symbol: Path,
    kicad_footprint: Path,
    step_model: Path,
    altium_sources: tuple[Path, ...],
    altium_identity_attestation: ExactPartIdentity | None = None,
) -> dict[str, object]:
    """Return strict-JSON evidence only after independent native readback agrees."""

    kicad_symbol = Path(kicad_symbol)
    kicad_footprint = Path(kicad_footprint)
    step_model = Path(step_model)
    sources = tuple(Path(path) for path in altium_sources)
    for path in (kicad_symbol, kicad_footprint, step_model, *sources):
        if not path.is_file() or path.is_symlink():
            raise CrossEdaVerificationError(f"CAD evidence is missing or linked: {path}")

    try:
        with tempfile.TemporaryDirectory(prefix="stockroom-cross-eda-") as temporary:
            schlib, pcblib = _resolve_altium_sources(sources, Path(temporary))
            kicad = read_kicad_symbol(kicad_symbol, identity.mpn_canonical)
            altium = read_altium_symbol(schlib, identity.mpn_canonical)
            bound_altium_fields = _verify_identity(
                altium,
                identity,
                "Altium",
                altium_identity_attestation,
            )
            kicad_fp = read_kicad_footprint(kicad_footprint, step_model)
            altium_fp = read_altium_footprint(pcblib, identity.mpn_canonical)
            mapping, kicad_no_connects, altium_no_connects = _terminal_map(kicad, altium)
            physical_mapping = _verify_geometry(
                kicad_fp.pads,
                altium_fp.pads,
                mapping,
                kicad_no_connects=kicad_no_connects,
                altium_no_connects=altium_no_connects,
            )
            represented_kicad = {pin.number for pin in kicad.pins}
            unrepresented_kicad = frozenset(physical_mapping) - represented_kicad
            kicad_report = verify_kicad_component(
                identity=identity,
                kicad_symbol=kicad_symbol,
                kicad_footprint=kicad_footprint,
                step_model=step_model,
                allowed_unrepresented_pads=unrepresented_kicad,
            )

            embedded = read_embedded_model_payloads(pcblib)
            if embedded and step_model.read_bytes() not in embedded:
                raise CrossEdaVerificationError("Altium PcbLib embeds a different STEP payload")
    except CrossEdaVerificationError:
        raise
    except Exception as exc:
        raise CrossEdaVerificationError(f"native CAD readback failed: {exc}") from exc

    return {
        "altium": {
            "embedded_step": bool(embedded),
            "footprint_entry": altium_fp.entry,
            "pad_count": len(altium_fp.pads),
            "pin_count": len(altium.pins),
            "symbol_entry": altium.entry,
        },
        "geometry": {
            "absolute_tolerance_mm": _GEOMETRY_ABSOLUTE_TOLERANCE_MM,
            "method": "mapped-pad-distance-and-size-signatures",
            "relative_tolerance": _GEOMETRY_RELATIVE_TOLERANCE,
        },
        "identity": {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
            **(
                {
                    "altium_binding": {
                        "fields": list(bound_altium_fields),
                        "source": "exact-provider-detail-page",
                    }
                }
                if bound_altium_fields
                else {}
            ),
        },
        "kicad": {
            "footprint_entry": kicad_fp.entry,
            "pad_count": len(kicad_fp.pads),
            "pin_count": len(kicad.pins),
            "symbol_entry": kicad.entry,
            "unrepresented_pad_numbers": sorted(unrepresented_kicad),
        },
        "schema": "stockroom.cross-eda-verification/1",
        "step": kicad_report["step"],
        "terminal_map": [
            {"altium": altium_number, "kicad": kicad_number}
            for kicad_number, altium_number in sorted(mapping.items())
        ],
        "no_connect_pad_map": [
            {"altium": altium_number, "kicad": kicad_number}
            for kicad_number, altium_number in sorted(physical_mapping.items())
            if kicad_number not in mapping
        ],
        "valid": True,
    }


__all__ = [
    "CrossEdaVerificationError",
    "read_altium_footprint",
    "read_altium_symbol",
    "read_kicad_footprint",
    "read_kicad_symbol",
    "verify_cross_eda_component",
    "verify_kicad_component",
]
