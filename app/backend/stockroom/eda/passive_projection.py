"""Isolated dual-EDA projection for the qualified ON Semiconductor S1M slice.

The canonical schema remains owned by :mod:`stockroom.domain`.  This module is
only a native projection/readback boundary.  It publishes four content-addressed
artifacts beneath a caller-owned empty staging directory and never writes to an
active EDA library.

KiCad artifacts are generated from installed KiCad 10 stock libraries and
opened by ``kicad-cli``.  Altium support is deliberately fixture-only: native
libraries are extracted from a checked-in ``.IntLib`` and their OLE streams are
read directly, but no claim is made about live Altium generation or placement.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

import olefile

from stockroom.altium.extract import normalize_altium_source
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.domain import CanonicalPassiveBundle, ToolTemplateBinding
from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.stock import (
    find_kicad_share_dir,
    stock_footprint_file,
    stock_symbol_lib_file,
)
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.mutation.placement import place_footprint
from stockroom.sexp.document import SexpDocument

ArtifactKind = Literal["symbol", "footprint"]
ToolKey = Literal["kicad", "altium"]

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SUPPORTED_IDENTITY = ("ON Semiconductor", "S1M")
_SUPPORTED_PACKAGE = "SMA (DO-214AC)"
_SUPPORTED_SHARED_TEMPLATES = (
    "shared.passive.diode.two_pin.v1",
    "shared.passive.diode.sma_do_214ac.v1",
)
_KICAD_SOURCE_TEMPLATES = ("Device:D", "Diode_SMD:D_SMA")
_ALTIUM_FIXTURE_REFS = ("S1M", "DIOM5227X270N")
_ALTIUM_PAD_TRAILER = b"\x01\x00\x00\x00\x00\x05\x00\x00\x00\x04|&|0"
_ROLE_PIN_NAME = {"cathode": "K", "anode": "A"}
_LIMITATIONS = (
    "Altium artifacts were acquired from a checked-in fixture, not generated.",
    "Altium semantics were read from OLE fixture streams, not the live official adapter.",
    "Database-library browse, placement, and compilation were not exercised.",
)


class ProjectionError(RuntimeError):
    """Base error for the isolated projection."""


class UnsupportedProjection(ProjectionError):
    """The requested identity, template, tool version, or mode is unsupported."""


class ProjectionMismatch(ProjectionError):
    """Native readback does not equal the canonical terminal mapping."""


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-blank trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactDigest:
    """A directly mappable, immutable native artifact."""

    tool: ToolKey
    kind: ArtifactKind
    template_id: str
    reference: str
    relative_path: str
    digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != self.relative_path
        ):
            raise ValueError("artifact path must be a normalized relative POSIX path")
        for value, name in (
            (self.template_id, "artifact template id"),
            (self.reference, "artifact reference"),
        ):
            _required_text(value, name)
        if _SHA256.fullmatch(self.digest) is None:
            raise ValueError("artifact digest must be a lowercase sha256 digest")
        digest_segment = self.digest.removeprefix("sha256:")
        if digest_segment not in path.parts:
            raise ValueError("artifact path must contain its full content digest")
        if self.size_bytes <= 0:
            raise ValueError("artifact size must be positive")

    @property
    def sha256(self) -> str:
        """Compatibility alias for callers that label the digest by algorithm."""

        return self.digest


@dataclass(frozen=True, slots=True)
class EvidenceDigest:
    locator: str
    digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        _required_text(self.locator, "evidence locator")
        if _SHA256.fullmatch(self.digest) is None:
            raise ValueError("evidence digest must be a lowercase sha256 digest")
        if self.size_bytes <= 0:
            raise ValueError("evidence size must be positive")

    @property
    def sha256(self) -> str:
        return self.digest


@dataclass(frozen=True, slots=True)
class ObservedPin:
    """A native pin plus its normalized tool-template terminal."""

    native_number: str
    name: str
    tool_terminal: str

    def __post_init__(self) -> None:
        _required_text(self.native_number, "observed native pin number")
        _required_text(self.name, "observed pin name")
        _required_text(self.tool_terminal, "observed tool terminal")


@dataclass(frozen=True, slots=True)
class ObservedPad:
    """A native pad plus its normalized tool-template terminal."""

    native_number: str
    tool_terminal: str

    def __post_init__(self) -> None:
        _required_text(self.native_number, "observed native pad number")
        _required_text(self.tool_terminal, "observed tool terminal")


@dataclass(frozen=True, slots=True)
class ToolBinding:
    symbol_template_id: str
    footprint_template_id: str
    source_symbol_reference: str
    source_footprint_reference: str
    symbol_library: str
    symbol_library_nickname: str | None
    symbol_ref: str
    footprint_library: str
    footprint_library_nickname: str | None
    footprint_ref: str

    def __post_init__(self) -> None:
        for attribute in (
            "symbol_template_id",
            "footprint_template_id",
            "source_symbol_reference",
            "source_footprint_reference",
            "symbol_library",
            "symbol_ref",
            "footprint_library",
            "footprint_ref",
        ):
            _required_text(getattr(self, attribute), attribute.replace("_", " "))
        for attribute in ("symbol_library", "footprint_library"):
            path = PurePosixPath(getattr(self, attribute))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"{attribute} must be a relative portable path")
        nicknames = (
            self.symbol_library_nickname,
            self.footprint_library_nickname,
        )
        if any(nickname is not None for nickname in nicknames):
            if any(nickname is None for nickname in nicknames):
                raise ValueError("library nicknames must be supplied as a pair")
            for nickname in nicknames:
                assert nickname is not None
                _required_text(nickname, "library nickname")
                if ":" in nickname:
                    raise ValueError("library nickname must not contain ':'")
            if self.symbol_ref != f"{self.symbol_library_nickname}:S1M":
                raise ValueError("KiCad symbol_ref must be a full library ID")
            if self.footprint_ref != f"{self.footprint_library_nickname}:S1M":
                raise ValueError("KiCad footprint_ref must be a full library ID")


@dataclass(frozen=True, slots=True)
class ToolProjection:
    tool: ToolKey
    tool_version: str
    fixture_mode: bool
    binding: ToolBinding
    artifacts: tuple[ArtifactDigest, ArtifactDigest]
    pins: tuple[ObservedPin, ObservedPin]
    pads: tuple[ObservedPad, ObservedPad]
    evidence: tuple[EvidenceDigest, ...] = ()

    def __post_init__(self) -> None:
        if tuple(artifact.tool for artifact in self.artifacts) != (
            self.tool,
            self.tool,
        ):
            raise ValueError("tool projection artifacts must belong to that tool")
        if tuple(artifact.kind for artifact in self.artifacts) != (
            "symbol",
            "footprint",
        ):
            raise ValueError("tool projection requires symbol then footprint artifacts")
        if self.tool == "kicad" and (self.fixture_mode or not self.tool_version):
            raise ValueError("KiCad projection must carry a real tool version")
        if self.tool == "altium" and not self.fixture_mode:
            raise ValueError("this slice supports only fixture-mode Altium projection")


@dataclass(frozen=True, slots=True)
class DualEdaProjectionResult:
    canonical_bundle_digest: str
    canonical_terminal_numbers: tuple[str, str]
    kicad: ToolProjection
    altium: ToolProjection
    limitations: tuple[str, ...] = _LIMITATIONS
    semantic_cross_check_passed: bool = field(default=True, init=False)
    production_ready: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.canonical_bundle_digest) is None:
            raise ValueError("canonical bundle digest must be a lowercase sha256 digest")
        if self.canonical_terminal_numbers != ("1", "2"):
            raise ValueError("this projection requires canonical terminals 1 and 2")
        if self.kicad.tool != "kicad" or self.altium.tool != "altium":
            raise ValueError("dual-EDA result must contain KiCad and Altium projections")
        if not self.altium.fixture_mode:
            raise ValueError("fixture limitation must remain explicit")
        if self.limitations != _LIMITATIONS:
            raise ValueError("fixture limitations cannot be weakened")

    @property
    def artifacts(
        self,
    ) -> tuple[ArtifactDigest, ArtifactDigest, ArtifactDigest, ArtifactDigest]:
        return (*self.kicad.artifacts, *self.altium.artifacts)


@dataclass(frozen=True, slots=True)
class _RawPin:
    number: str
    name: str


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _evidence(locator: str, data: bytes) -> EvidenceDigest:
    return EvidenceDigest(
        locator=locator,
        digest=_sha256_bytes(data),
        size_bytes=len(data),
    )


def _validated_bundle(bundle: CanonicalPassiveBundle) -> CanonicalPassiveBundle:
    if not isinstance(bundle, CanonicalPassiveBundle):
        raise TypeError("bundle must be stockroom.domain.CanonicalPassiveBundle")
    # model_copy(update=...) bypasses Pydantic validation.  Revalidate the complete
    # graph so a caller cannot project broken digest links through this boundary.
    return CanonicalPassiveBundle.model_validate(bundle.model_dump(mode="python"))


def _tool_binding(
    bundle: CanonicalPassiveBundle,
    tool: ToolKey,
) -> ToolTemplateBinding:
    return next(binding for binding in bundle.artifacts.tool_bindings if binding.tool == tool)


def _supported_bundle(bundle: CanonicalPassiveBundle) -> None:
    package = next(claim.value for claim in bundle.claims if claim.key == "package")
    identity = (
        bundle.manufacturer.authoritative_key,
        bundle.identity.mpn_canonical,
    )
    templates = tuple(template.template_id for template in bundle.artifacts.shared_templates)
    roles = tuple((terminal.number, terminal.role) for terminal in bundle.definition.terminals)
    if identity != _SUPPORTED_IDENTITY:
        raise UnsupportedProjection("this slice supports only exact ON Semiconductor/S1M")
    if (
        bundle.definition.functional_kind != "diode"
        or package != _SUPPORTED_PACKAGE
        or roles != (("1", "cathode"), ("2", "anode"))
        or templates != _SUPPORTED_SHARED_TEMPLATES
    ):
        raise UnsupportedProjection(
            "this slice supports only the qualified S1M diode/SMA canonical profile"
        )
    for tool in ("kicad", "altium"):
        binding = _tool_binding(bundle, tool)
        if (
            binding.symbol_template_id,
            binding.footprint_template_id,
        ) != _SUPPORTED_SHARED_TEMPLATES:
            raise UnsupportedProjection(f"{tool} does not bind the qualified shared S1M templates")
        expected_tool_terminals = ("1", "2") if tool == "kicad" else ("C", "A")
        actual_tool_terminals = tuple(
            terminal.tool_terminal for terminal in binding.terminal_bindings
        )
        if actual_tool_terminals != expected_tool_terminals:
            raise UnsupportedProjection(
                f"{tool} does not use the qualified S1M native terminal bindings"
            )


def _empty_staging_root(staging_directory: Path) -> Path:
    root = Path(staging_directory)
    if not root.is_dir():
        raise ValueError("staging_directory must be an existing empty directory")
    if any(root.iterdir()):
        raise ValueError("staging_directory must be empty")
    return root


def _publish_file(
    *,
    source: Path,
    root: Path,
    tool: ToolKey,
    kind: ArtifactKind,
    template_id: str,
    reference: str,
    relative_parent: PurePosixPath,
    relative_tail: PurePosixPath,
) -> tuple[Path, ArtifactDigest]:
    """Copy exact staged bytes to a content-addressed immutable path."""

    data = source.read_bytes()
    digest = _sha256_bytes(data)
    revision = digest.removeprefix("sha256:")
    relative_path = relative_parent / revision / relative_tail
    destination = root.joinpath(*relative_path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    if destination.read_bytes() != data:
        raise ProjectionMismatch("published artifact bytes differ from staged bytes")
    return (
        destination,
        ArtifactDigest(
            tool=tool,
            kind=kind,
            template_id=template_id,
            reference=reference,
            relative_path=relative_path.as_posix(),
            digest=digest,
            size_bytes=len(data),
        ),
    )


def _symbol_node_text(source: Path, symbol_name: str) -> str:
    document = SexpDocument.load(source)
    for node in document.root.find_all("symbol"):
        if len(node.children) >= 2 and node.children[1].value == symbol_name:
            start, end = node.span
            return document.text[start:end]
    raise ProjectionMismatch(f"KiCad stock symbol {symbol_name!r} was not found in {source.name}")


def _insert_renamed_symbol(
    library_path: Path,
    source_path: Path,
    source_name: str,
    output_name: str,
    footprint_ref: str,
) -> None:
    fragment = SexpDocument.parse(_symbol_node_text(source_path, source_name))
    symbol_nodes = [fragment.root]
    symbol_nodes.extend(node for node in fragment.root.iter_descendants() if node.name == "symbol")
    for node in symbol_nodes:
        if len(node.children) < 2:
            raise ProjectionMismatch("KiCad symbol node has no name")
        old_name = node.children[1].value
        if old_name == source_name:
            new_name = output_name
        elif old_name.startswith(f"{source_name}_"):
            new_name = f"{output_name}{old_name[len(source_name) :]}"
        else:
            raise ProjectionMismatch(
                f"KiCad nested symbol {old_name!r} does not belong to {source_name!r}"
            )
        node.children[1].set_value(new_name, quote=True)

    library = SymbolLib.load(library_path)
    library.insert_symbol(fragment.serialize())
    library.save(library_path)

    reloaded = SymbolLib.load(library_path)
    symbol = reloaded.get_symbol(output_name)
    symbol.set_property("Value", output_name)
    symbol.set_property("Footprint", footprint_ref, hide=True)
    symbol.set_property("Manufacturer", _SUPPORTED_IDENTITY[0], hide=True)
    symbol.set_property("MPN", _SUPPORTED_IDENTITY[1], hide=True)
    reloaded.save(library_path)


def _read_kicad_pins(symbol_path: Path, symbol_name: str) -> tuple[_RawPin, ...]:
    document = SexpDocument.load(symbol_path)
    outer = next(
        (
            node
            for node in document.root.find_all("symbol")
            if len(node.children) >= 2 and node.children[1].value == symbol_name
        ),
        None,
    )
    if outer is None:
        raise ProjectionMismatch(f"generated KiCad symbol {symbol_name!r} is absent")
    observed: list[_RawPin] = []
    for node in outer.iter_descendants():
        if node.name != "pin":
            continue
        name_node = node.find("name")
        number_node = node.find("number")
        if (
            name_node is None
            or number_node is None
            or len(name_node.children) < 2
            or len(number_node.children) < 2
        ):
            raise ProjectionMismatch("generated KiCad symbol contains an incomplete pin")
        observed.append(
            _RawPin(
                number=number_node.children[1].value,
                name=name_node.children[1].value,
            )
        )
    return tuple(sorted(observed, key=lambda pin: pin.number))


def _normalize_kicad(
    bundle: CanonicalPassiveBundle,
    binding: ToolTemplateBinding,
    raw_pins: tuple[_RawPin, ...],
    raw_pads: tuple[str, ...],
) -> tuple[tuple[ObservedPin, ObservedPin], tuple[ObservedPad, ObservedPad]]:
    canonical_by_tool = {
        item.tool_terminal: item.canonical_terminal for item in binding.terminal_bindings
    }
    role_by_canonical = {terminal.number: terminal.role for terminal in bundle.definition.terminals}
    pins: list[ObservedPin] = []
    for pin in raw_pins:
        canonical_number = canonical_by_tool.get(pin.number)
        if canonical_number is None:
            raise ProjectionMismatch(f"KiCad pin {pin.number!r} has no template binding")
        expected_name = _ROLE_PIN_NAME.get(role_by_canonical[canonical_number])
        if pin.name != expected_name:
            raise ProjectionMismatch(
                f"KiCad pin {pin.number!r} is {pin.name!r}, expected {expected_name!r}"
            )
        pins.append(
            ObservedPin(
                native_number=pin.number,
                name=pin.name,
                tool_terminal=pin.number,
            )
        )
    pads = [ObservedPad(native_number=number, tool_terminal=number) for number in raw_pads]
    if len(pins) != 2 or len(pads) != 2:
        raise ProjectionMismatch("KiCad S1M must expose exactly two pins and two pads")
    return (pins[0], pins[1]), (pads[0], pads[1])


def _project_kicad(bundle: CanonicalPassiveBundle, root: Path) -> ToolProjection:
    binding = _tool_binding(bundle, "kicad")
    library_nickname = f"Stockroom_{bundle.identity.component_id}"
    symbol_ref = f"{library_nickname}:S1M"
    footprint_ref = f"{library_nickname}:S1M"
    cli = KiCadCli()
    if not cli.available:
        raise UnsupportedProjection("installed KiCad 10 CLI is required")
    version = cli.version()
    if not version.startswith("10."):
        raise UnsupportedProjection(
            f"KiCad {version or 'unknown'} is not qualified; installed KiCad 10 is required"
        )
    share = find_kicad_share_dir()
    if share is None:
        raise UnsupportedProjection("installed KiCad 10 stock libraries are required")
    symbol_source = stock_symbol_lib_file("Device", share=share)
    footprint_source = stock_footprint_file("Diode_SMD", "D_SMA", share=share)
    if symbol_source is None or footprint_source is None:
        raise UnsupportedProjection("installed KiCad 10 is missing Device:D or Diode_SMD:D_SMA")

    build_root = root / ".build" / "KiCad"
    staged_symbol = build_root / "S1M.kicad_sym"
    staged_pretty = build_root / "S1M.pretty"
    staged_footprint = staged_pretty / "S1M.kicad_mod"
    create_empty_symbol_lib(cli, staged_symbol)
    _insert_renamed_symbol(
        staged_symbol,
        symbol_source,
        "D",
        "S1M",
        footprint_ref,
    )
    ensure_footprint_lib(staged_pretty)
    placed = place_footprint(staged_pretty, footprint_source, "S1M")
    if placed != staged_footprint:
        raise ProjectionMismatch("KiCad footprint landed at an unexpected path")

    symbol_path, symbol_artifact = _publish_file(
        source=staged_symbol,
        root=root,
        tool="kicad",
        kind="symbol",
        template_id=binding.symbol_template_id,
        reference=symbol_ref,
        relative_parent=PurePosixPath("EDA/KiCad/Symbols"),
        relative_tail=PurePosixPath("S1M.kicad_sym"),
    )
    footprint_path, footprint_artifact = _publish_file(
        source=staged_footprint,
        root=root,
        tool="kicad",
        kind="footprint",
        template_id=binding.footprint_template_id,
        reference=footprint_ref,
        relative_parent=PurePosixPath("EDA/KiCad/Footprints"),
        relative_tail=PurePosixPath("S1M.pretty/S1M.kicad_mod"),
    )
    pretty_path = footprint_path.parent

    symbol_library = SymbolLib.load(symbol_path)
    if symbol_library.symbol_names != ["S1M"]:
        raise ProjectionMismatch(
            f"generated KiCad symbol entries are {symbol_library.symbol_names!r}"
        )
    if symbol_library.get_symbol("S1M").get_property("Footprint") != footprint_ref:
        raise ProjectionMismatch(
            "generated KiCad symbol does not bind the projected footprint library ID"
        )
    footprint = Footprint.load(footprint_path)
    if footprint.name != "S1M":
        raise ProjectionMismatch(
            f"generated KiCad footprint is named {footprint.name!r}, not 'S1M'"
        )
    raw_pins = _read_kicad_pins(symbol_path, "S1M")
    raw_pads = tuple(sorted(pad.number for pad in footprint.pads))
    pins, pads = _normalize_kicad(bundle, binding, raw_pins, raw_pads)

    with tempfile.TemporaryDirectory(prefix=".kicad-readback-", dir=root) as readback:
        readback_root = Path(readback)
        symbol_svgs = cli.sym_export_svg(
            symbol_path,
            "S1M",
            readback_root / "symbol",
        )
        footprint_svg = cli.fp_export_svg(
            pretty_path,
            "S1M",
            readback_root / "footprint",
        )
        if not symbol_svgs or any(path.stat().st_size <= 0 for path in symbol_svgs):
            raise ProjectionMismatch("KiCad CLI did not export the generated S1M symbol")
        if footprint_svg.stat().st_size <= 0:
            raise ProjectionMismatch("KiCad CLI did not export the generated S1M footprint")

    return ToolProjection(
        tool="kicad",
        tool_version=version,
        fixture_mode=False,
        binding=ToolBinding(
            symbol_template_id=binding.symbol_template_id,
            footprint_template_id=binding.footprint_template_id,
            source_symbol_reference=_KICAD_SOURCE_TEMPLATES[0],
            source_footprint_reference=_KICAD_SOURCE_TEMPLATES[1],
            symbol_library=symbol_artifact.relative_path,
            symbol_library_nickname=library_nickname,
            symbol_ref=symbol_ref,
            footprint_library=pretty_path.relative_to(root).as_posix(),
            footprint_library_nickname=library_nickname,
            footprint_ref=footprint_ref,
        ),
        artifacts=(symbol_artifact, footprint_artifact),
        pins=pins,
        pads=pads,
    )


def _pipe_record(payload: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    utf8: set[str] = set()
    for part in payload.rstrip(b"\x00").split(b"|"):
        if not part or b"=" not in part:
            continue
        raw_key, raw_value = part.split(b"=", 1)
        key = raw_key.decode("latin-1").upper()
        if key.startswith("%UTF8%"):
            canonical = key[len("%UTF8%") :]
            fields[canonical] = raw_value.decode("utf-8", errors="strict")
            utf8.add(canonical)
        elif key not in utf8:
            fields[key] = raw_value.decode("latin-1")
    return fields


def _pascal_string(payload: bytes, offset: int, label: str) -> tuple[str, int]:
    if offset >= len(payload):
        raise ProjectionMismatch(f"Altium {label} is truncated")
    length = payload[offset]
    end = offset + 1 + length
    if length == 0 or end > len(payload):
        raise ProjectionMismatch(f"Altium {label} has an invalid length")
    raw = payload[offset + 1 : end]
    if any(byte < 0x20 or byte >= 0x7F for byte in raw):
        raise ProjectionMismatch(f"Altium {label} is not printable ASCII")
    return raw.decode("ascii"), end


def _read_altium_symbol_data(
    raw: bytes,
) -> tuple[str, str, tuple[_RawPin, ...]]:
    records: list[dict[str, str]] = []
    pins: list[_RawPin] = []
    offset = 0
    while offset + 4 <= len(raw):
        word = struct.unpack_from("<I", raw, offset)[0]
        length = word & 0x00FFFFFF
        record_type = word >> 24
        offset += 4
        if length == 0 or offset + length > len(raw):
            raise ProjectionMismatch("Altium SchLib component stream is truncated")
        payload = raw[offset : offset + length]
        offset += length
        if record_type == 0:
            records.append(_pipe_record(payload))
        elif record_type == 1:
            if len(payload) < 32:
                raise ProjectionMismatch("Altium binary pin record is truncated")
            name, cursor = _pascal_string(payload, 26, "pin name")
            number, cursor = _pascal_string(payload, cursor, "pin number")
            if payload[cursor:] != b"\x00\x03|&|\x00":
                raise ProjectionMismatch("Altium binary pin record has an unknown layout")
            pins.append(_RawPin(number=number, name=name))
        else:
            raise ProjectionMismatch(
                f"Altium SchLib contains unsupported record type {record_type}"
            )
    if offset != len(raw) or not records:
        raise ProjectionMismatch("Altium SchLib component stream has trailing bytes")
    component = records[0]
    if component.get("RECORD") != "1" or component.get("LIBREFERENCE") != "S1M":
        raise ProjectionMismatch("Altium SchLib component identity is not S1M")
    try:
        expected_pin_count = int(component.get("ALLPINCOUNT", ""))
    except ValueError as exc:
        raise ProjectionMismatch("Altium SchLib has no valid pin count") from exc
    if expected_pin_count != len(pins):
        raise ProjectionMismatch(
            f"Altium SchLib declares {expected_pin_count} pins but exposes {len(pins)}"
        )
    parameters = {
        record.get("NAME", ""): record.get("TEXT", "")
        for record in records
        if record.get("RECORD") == "41" and record.get("NAME")
    }
    return (
        parameters.get("MF", ""),
        parameters.get("MP", ""),
        tuple(sorted(pins, key=lambda pin: pin.number)),
    )


def _read_altium_pad_numbers(raw: bytes, footprint_name: str) -> tuple[str, ...]:
    if len(raw) < 5:
        raise ProjectionMismatch("Altium PcbLib component stream is truncated")
    name_length = struct.unpack_from("<I", raw, 0)[0]
    if name_length < 2 or 4 + name_length > len(raw):
        raise ProjectionMismatch("Altium PcbLib component name record is invalid")
    encoded_name = raw[4 : 4 + name_length]
    if encoded_name[0] != name_length - 1:
        raise ProjectionMismatch("Altium PcbLib component name length is invalid")
    observed_name = encoded_name[1:].decode("ascii", errors="strict")
    if observed_name != footprint_name:
        raise ProjectionMismatch(
            f"Altium PcbLib component is {observed_name!r}, not {footprint_name!r}"
        )

    numbers: list[str] = []
    for offset in range(4 + name_length, len(raw) - 6):
        if raw[offset] != 2:
            continue
        field_length = struct.unpack_from("<I", raw, offset + 1)[0]
        if not 2 <= field_length <= 65:
            continue
        payload_end = offset + 5 + field_length
        trailer_end = payload_end + len(_ALTIUM_PAD_TRAILER)
        if trailer_end > len(raw):
            continue
        payload = raw[offset + 5 : payload_end]
        if payload[0] != field_length - 1:
            continue
        if raw[payload_end:trailer_end] != _ALTIUM_PAD_TRAILER:
            continue
        number = payload[1:].decode("ascii", errors="strict")
        if not number or any(ord(char) < 0x20 or ord(char) >= 0x7F for char in number):
            raise ProjectionMismatch("Altium PcbLib pad number is not printable ASCII")
        numbers.append(number)
    unique = tuple(sorted(set(numbers)))
    if len(unique) != len(numbers) or not unique:
        raise ProjectionMismatch("Altium PcbLib pad designators are absent or duplicated")
    return unique


def _ole_stream(path: Path, stream: tuple[str, ...]) -> bytes:
    with olefile.OleFileIO(str(path)) as container:
        location = list(stream)
        if not container.exists(location):
            raise ProjectionMismatch(f"{path.name} is missing OLE stream {'/'.join(stream)}")
        return container.openstream(location).read()


def _normalize_altium(
    bundle: CanonicalPassiveBundle,
    binding: ToolTemplateBinding,
    raw_pins: tuple[_RawPin, ...],
    raw_pads: tuple[str, ...],
) -> tuple[tuple[ObservedPin, ObservedPin], tuple[ObservedPad, ObservedPad]]:
    canonical_by_tool = {
        item.tool_terminal: item.canonical_terminal for item in binding.terminal_bindings
    }
    role_by_canonical = {terminal.number: terminal.role for terminal in bundle.definition.terminals}
    pins: list[ObservedPin] = []
    for pin in raw_pins:
        canonical_terminal = canonical_by_tool.get(pin.number)
        if canonical_terminal is None:
            raise ProjectionMismatch(f"Altium pin {pin.number!r} has no canonical tool binding")
        expected_name = _ROLE_PIN_NAME.get(role_by_canonical[canonical_terminal])
        if pin.name != expected_name:
            raise ProjectionMismatch(
                f"Altium pin {pin.number!r} is {pin.name!r}, expected {expected_name!r}"
            )
        pins.append(
            ObservedPin(
                native_number=pin.number,
                name=pin.name,
                tool_terminal=pin.number,
            )
        )
    pads: list[ObservedPad] = []
    for native_number in raw_pads:
        if native_number not in canonical_by_tool:
            raise ProjectionMismatch(f"Altium pad {native_number!r} has no canonical tool binding")
        pads.append(
            ObservedPad(
                native_number=native_number,
                tool_terminal=native_number,
            )
        )
    canonical_order = {
        item.tool_terminal: item.canonical_terminal for item in binding.terminal_bindings
    }
    pins.sort(key=lambda pin: canonical_order[pin.tool_terminal])
    pads.sort(key=lambda pad: canonical_order[pad.tool_terminal])
    if len(pins) != 2 or len(pads) != 2:
        raise ProjectionMismatch("Altium S1M must expose exactly two pins and two pads")
    return (pins[0], pins[1]), (pads[0], pads[1])


def _project_altium(
    bundle: CanonicalPassiveBundle,
    root: Path,
    intlib: Path,
) -> ToolProjection:
    binding = _tool_binding(bundle, "altium")
    build_root = root / ".build" / "Altium"
    build_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".extract-", dir=build_root) as extracted:
        source_symbol, source_footprint = normalize_altium_source(
            intlib,
            out_dir=Path(extracted),
        )
        if source_symbol is None or source_footprint is None:
            raise ProjectionMismatch("Altium fixture does not contain both native libraries")
        symbol_names = read_symbol_names(source_symbol)
        footprint_names = read_footprint_names(source_footprint)
        if symbol_names != [_ALTIUM_FIXTURE_REFS[0]]:
            raise ProjectionMismatch(
                f"Altium symbol entries are {symbol_names!r}, expected ['S1M']"
            )
        if footprint_names != [_ALTIUM_FIXTURE_REFS[1]]:
            raise ProjectionMismatch(
                f"Altium footprint entries are {footprint_names!r}, expected ['DIOM5227X270N']"
            )
        symbol_path, symbol_artifact = _publish_file(
            source=source_symbol,
            root=root,
            tool="altium",
            kind="symbol",
            template_id=binding.symbol_template_id,
            reference=_ALTIUM_FIXTURE_REFS[0],
            relative_parent=PurePosixPath("EDA/Altium/Symbols"),
            relative_tail=PurePosixPath("S1M.SchLib"),
        )
        footprint_path, footprint_artifact = _publish_file(
            source=source_footprint,
            root=root,
            tool="altium",
            kind="footprint",
            template_id=binding.footprint_template_id,
            reference=_ALTIUM_FIXTURE_REFS[1],
            relative_parent=PurePosixPath("EDA/Altium/Footprints"),
            relative_tail=PurePosixPath("S1M.PcbLib"),
        )

    if read_symbol_names(symbol_path) != [_ALTIUM_FIXTURE_REFS[0]]:
        raise ProjectionMismatch("published Altium SchLib did not read back S1M")
    if read_footprint_names(footprint_path) != [_ALTIUM_FIXTURE_REFS[1]]:
        raise ProjectionMismatch("published Altium PcbLib did not read back DIOM5227X270N")

    header = _ole_stream(symbol_path, ("FileHeader",))
    symbol_data = _ole_stream(symbol_path, ("S1M", "Data"))
    footprint_data = _ole_stream(
        footprint_path,
        ("DIOM5227X270N", "Data"),
    )
    manufacturer, mpn, raw_pins = _read_altium_symbol_data(symbol_data)
    if (manufacturer, mpn) != _SUPPORTED_IDENTITY:
        raise ProjectionMismatch(
            f"Altium fixture identity is {manufacturer}/{mpn}, not ON Semiconductor/S1M"
        )
    raw_pads = _read_altium_pad_numbers(
        footprint_data,
        _ALTIUM_FIXTURE_REFS[1],
    )
    pins, pads = _normalize_altium(
        bundle,
        binding,
        raw_pins,
        raw_pads,
    )

    return ToolProjection(
        tool="altium",
        tool_version="",
        fixture_mode=True,
        binding=ToolBinding(
            symbol_template_id=binding.symbol_template_id,
            footprint_template_id=binding.footprint_template_id,
            source_symbol_reference=_ALTIUM_FIXTURE_REFS[0],
            source_footprint_reference=_ALTIUM_FIXTURE_REFS[1],
            symbol_library=symbol_artifact.relative_path,
            symbol_library_nickname=None,
            symbol_ref=_ALTIUM_FIXTURE_REFS[0],
            footprint_library=footprint_artifact.relative_path,
            footprint_library_nickname=None,
            footprint_ref=_ALTIUM_FIXTURE_REFS[1],
        ),
        artifacts=(symbol_artifact, footprint_artifact),
        pins=pins,
        pads=pads,
        evidence=(
            _evidence(f"{symbol_artifact.relative_path}:FileHeader", header),
            _evidence(f"{symbol_artifact.relative_path}:S1M/Data", symbol_data),
            _evidence(
                f"{footprint_artifact.relative_path}:DIOM5227X270N/Data",
                footprint_data,
            ),
        ),
    )


def _cross_check_tool(
    bundle: CanonicalPassiveBundle,
    projected: ToolProjection,
) -> None:
    canonical_binding = _tool_binding(bundle, projected.tool)
    if (
        projected.binding.symbol_template_id,
        projected.binding.footprint_template_id,
    ) != (
        canonical_binding.symbol_template_id,
        canonical_binding.footprint_template_id,
    ):
        raise ProjectionMismatch(
            f"{projected.tool} result does not retain canonical template bindings"
        )
    expected_tool_by_canonical = {
        item.canonical_terminal: item.tool_terminal for item in canonical_binding.terminal_bindings
    }
    expected_pins = {
        (
            expected_tool_by_canonical[terminal.number],
            _ROLE_PIN_NAME.get(terminal.role),
        )
        for terminal in bundle.definition.terminals
    }
    observed_pins = {(pin.tool_terminal, pin.name) for pin in projected.pins}
    if observed_pins != expected_pins:
        raise ProjectionMismatch(
            f"{projected.tool} pin semantics differ from canonical terminals: "
            f"observed={sorted(observed_pins)!r}, expected={sorted(expected_pins)!r}"
        )
    expected_terminals = set(expected_tool_by_canonical.values())
    observed_pad_terminals = {pad.tool_terminal for pad in projected.pads}
    if observed_pad_terminals != expected_terminals:
        raise ProjectionMismatch(
            f"{projected.tool} pad semantics differ from canonical terminals: "
            f"observed={sorted(observed_pad_terminals)!r}, "
            f"expected={sorted(expected_terminals)!r}"
        )
    if {pin.native_number for pin in projected.pins} != {
        pad.native_number for pad in projected.pads
    }:
        raise ProjectionMismatch(f"{projected.tool} native pin-to-pad IDs do not match")
    if {pin.tool_terminal for pin in projected.pins} != observed_pad_terminals:
        raise ProjectionMismatch(f"{projected.tool} normalized pin-to-pad bindings do not match")
    artifact_bindings = {
        artifact.kind: (artifact.template_id, artifact.reference)
        for artifact in projected.artifacts
    }
    expected_artifacts = {
        "symbol": (
            canonical_binding.symbol_template_id,
            projected.binding.symbol_ref,
        ),
        "footprint": (
            canonical_binding.footprint_template_id,
            projected.binding.footprint_ref,
        ),
    }
    if artifact_bindings != expected_artifacts:
        raise ProjectionMismatch(
            f"{projected.tool} artifact metadata differs from its result binding"
        )


def _cross_check(
    bundle: CanonicalPassiveBundle,
    kicad: ToolProjection,
    altium: ToolProjection,
) -> None:
    _cross_check_tool(bundle, kicad)
    _cross_check_tool(bundle, altium)
    kicad_canonical_by_tool = {
        item.tool_terminal: item.canonical_terminal
        for item in _tool_binding(bundle, "kicad").terminal_bindings
    }
    altium_canonical_by_tool = {
        item.tool_terminal: item.canonical_terminal
        for item in _tool_binding(bundle, "altium").terminal_bindings
    }
    kicad_semantics = {(kicad_canonical_by_tool[pin.tool_terminal], pin.name) for pin in kicad.pins}
    altium_semantics = {
        (altium_canonical_by_tool[pin.tool_terminal], pin.name) for pin in altium.pins
    }
    if kicad_semantics != altium_semantics:
        raise ProjectionMismatch("KiCad and Altium normalized pin semantics do not agree")


def project_passive_bundle(
    bundle: CanonicalPassiveBundle,
    staging_directory: Path,
    *,
    fixture_mode: bool,
    altium_intlib: Path,
) -> DualEdaProjectionResult:
    """Project exact S1M into an isolated empty staging root.

    ``fixture_mode=False`` is rejected until the official native Altium adapter
    exists.  On any failure the caller's staging directory remains empty.
    """

    canonical = _validated_bundle(bundle)
    _supported_bundle(canonical)
    if fixture_mode is not True:
        raise UnsupportedProjection(
            "fixture_mode=False requires a real native Altium adapter, which is not implemented"
        )
    root = _empty_staging_root(staging_directory)
    intlib = Path(altium_intlib)
    if not intlib.is_file() or intlib.suffix.lower() != ".intlib":
        raise ValueError("altium_intlib must be an existing .IntLib fixture")

    with tempfile.TemporaryDirectory(prefix=".passive-projection-", dir=root) as temporary:
        work = Path(temporary)
        kicad = _project_kicad(canonical, work)
        altium = _project_altium(canonical, work, intlib)
        _cross_check(canonical, kicad, altium)
        result = DualEdaProjectionResult(
            canonical_bundle_digest=canonical.canonical_digest(),
            canonical_terminal_numbers=(
                canonical.definition.terminals[0].number,
                canonical.definition.terminals[1].number,
            ),
            kicad=kicad,
            altium=altium,
        )
        payload = work / "EDA"
        if not payload.is_dir():
            raise ProjectionMismatch("projection produced no EDA staging tree")
        payload.replace(root / "EDA")
        return result
