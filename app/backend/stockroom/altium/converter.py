"""Run Stockroom's deterministic P-CAD-to-native-Altium sidecar.

The converter process is deliberately separate from the Python host.  Packaged builds
inject its exact attested path; development callers may pass that path explicitly.  The
boundary is request/result JSON, never console text, and every native artifact is read
back through Stockroom before it can be handed to ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stockroom.altium.native_authoring import read_embedded_model_payloads
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.capture.cross_eda import read_altium_footprint, read_altium_symbol
from stockroom.pcad import normalize, parse_file
from stockroom.pcad.altium_request import build_altium_writer_request

_RESULT_SCHEMA = "stockroom.cad-converter/result/1"
_CONVERTER_ENV = "STOCKROOM_CAD_CONVERTER"


def _installed_converter() -> Path | None:
    """Return the machine-local converter provisioned by the Windows package.

    The continuously updated Python host is a child of the stable launcher, not the immutable
    release worker. It therefore cannot rely on a temporary PyInstaller extraction path surviving
    forever. A package provisions the complete sidecar under LocalAppData and source updates keep
    using that stable, user-scoped location.
    """

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = (
        Path(local_app_data)
        / "Stockroom"
        / "Tools"
        / "CadConverter"
        / "Stockroom.CadConverter.exe"
    )
    return candidate if candidate.is_file() else None


def _development_converter() -> Path | None:
    """Return the converter built beside an editable source checkout, when present."""

    if bool(getattr(sys, "frozen", False)):
        return None
    repository_root = Path(__file__).resolve().parents[4]
    candidate = (
        repository_root
        / "app"
        / "desktop"
        / "Stockroom.CadConverter"
        / "bin"
        / "Release"
        / "net10.0"
        / "Stockroom.CadConverter.exe"
    )
    return candidate if candidate.is_file() else None


class CadConversionError(RuntimeError):
    """The sidecar could not produce strictly verified native Altium libraries."""


@dataclass(frozen=True, slots=True)
class NativeAltiumConversion:
    symbol_library: Path
    footprint_library: Path
    symbol_entries: tuple[str, ...]
    footprint_entries: tuple[str, ...]
    source_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(
    value: object,
    *,
    suffix: str,
    output_directory: Path,
) -> Path:
    if not isinstance(value, dict):
        raise CadConversionError(f"converter result is missing its {suffix} artifact")
    path_value = value.get("path")
    size = value.get("sizeBytes")
    digest = value.get("sha256")
    if not isinstance(path_value, str) or not isinstance(size, int) or not isinstance(digest, str):
        raise CadConversionError(f"converter returned an invalid {suffix} artifact record")
    path = Path(path_value).resolve(strict=True)
    if path.suffix.casefold() != suffix.casefold():
        raise CadConversionError(f"converter returned the wrong artifact type for {suffix}")
    try:
        path.relative_to(output_directory)
    except ValueError as exc:
        raise CadConversionError("converter artifact escaped its requested output directory") from exc
    if path.stat().st_size != size or _sha256(path) != digest:
        raise CadConversionError(f"converter {suffix} artifact does not match its evidence")
    return path


def _invoke(
    executable: Path,
    request_path: Path,
    result_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    executable = executable.resolve(strict=True)
    if executable.suffix.casefold() != ".exe":
        raise CadConversionError("native CAD converter must be an exact .exe path")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                str(executable),
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise CadConversionError("native CAD conversion timed out") from exc
    if not result_path.is_file():
        raise CadConversionError(
            f"native CAD converter exited {completed.returncode} without a result document"
        )
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CadConversionError("native CAD converter returned unreadable result JSON") from exc
    if not isinstance(result, dict) or result.get("schema") != _RESULT_SCHEMA:
        raise CadConversionError("native CAD converter returned an unsupported result schema")
    if completed.returncode != 0 or result.get("status") != "ok":
        detail = result.get("detail")
        raise CadConversionError(
            detail if isinstance(detail, str) and detail else "native CAD conversion failed"
        )
    return result


def _resolve_converter_executable(value: Path | str | None) -> Path:
    if value is not None:
        return Path(value)
    configured = os.environ.get(_CONVERTER_ENV)
    if configured:
        return Path(configured)
    # An editable checkout must run the converter built from that same checkout. Falling through
    # to the machine-installed package first made source runs silently execute an older validator,
    # so a fix could pass its own build/tests and still fail in the real app. A continuously updated
    # packaged checkout has no committed bin/ output and naturally falls through to the installed
    # converter below.
    development = _development_converter()
    if development is not None:
        return development
    installed = _installed_converter()
    if installed is not None:
        return installed
    raise CadConversionError(
        f"native CAD converter is unavailable; packaged runtime must set {_CONVERTER_ENV}"
    )


def convert_pcad_ascii(
    lia_path: Path,
    output_directory: Path,
    *,
    step_model: Path | None = None,
    converter_executable: Path | None = None,
    timeout_seconds: float = 60,
) -> NativeAltiumConversion:
    """Convert and strictly read back one P-CAD ASCII library without Altium."""
    lia_path = Path(lia_path).resolve(strict=True)
    step_model = None if step_model is None else Path(step_model).resolve(strict=True)
    output_directory = Path(output_directory).resolve()
    executable = _resolve_converter_executable(converter_executable)
    library = normalize(parse_file(lia_path))
    request = build_altium_writer_request(
        library,
        output_directory=output_directory,
        step_model=step_model,
    )

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="Stockroom Cad Converter ", dir=output_directory.parent
    ) as temporary:
        boundary = Path(temporary)
        request_path = boundary / "Request.json"
        result_path = boundary / "Result.json"
        request_path.write_text(
            json.dumps(request, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result = _invoke(executable, request_path, result_path, timeout_seconds)

    symbol_library = _artifact(
        result.get("schlib"), suffix=".SchLib", output_directory=output_directory
    )
    footprint_library = _artifact(
        result.get("pcblib"), suffix=".PcbLib", output_directory=output_directory
    )
    symbol_entries = tuple(read_symbol_names(symbol_library))
    footprint_entries = tuple(read_footprint_names(footprint_library))
    expected_footprints = tuple(item.name for item in library.footprints)
    if symbol_entries != (library.mpn,):
        raise CadConversionError(
            f"native symbol readback returned {symbol_entries!r}, expected {(library.mpn,)!r}"
        )
    if footprint_entries != expected_footprints:
        raise CadConversionError(
            f"native footprint readback returned {footprint_entries!r}, "
            f"expected {expected_footprints!r}"
        )

    symbol = read_altium_symbol(symbol_library, library.mpn)
    if symbol.manufacturer != library.manufacturer or symbol.mpn != library.mpn:
        raise CadConversionError("native symbol identity did not survive readback")
    expected_pins = {(item.number, item.name) for item in library.symbol.pins}
    if {(item.number, item.name) for item in symbol.pins} != expected_pins:
        raise CadConversionError("native symbol pin map did not survive readback")

    for footprint in library.footprints:
        observed = read_altium_footprint(footprint_library, footprint.name)
        observed_pads = {
            item.number: (item.x_mm, item.y_mm, item.width_mm, item.height_mm)
            for item in observed.pads
        }
        expected_pads = {
            item.number: (
                item.position.x_nm / 1_000_000,
                item.position.y_nm / 1_000_000,
                item.width_nm / 1_000_000,
                item.height_nm / 1_000_000,
            )
            for item in footprint.pads
        }
        if observed_pads.keys() != expected_pads.keys() or any(
            any(abs(left - right) > 0.00002 for left, right in zip(observed_pads[number], values))
            for number, values in expected_pads.items()
        ):
            raise CadConversionError(
                f"native footprint pad geometry did not survive readback for {footprint.name}"
            )

    if step_model is not None:
        payloads = read_embedded_model_payloads(footprint_library)
        if payloads != (step_model.read_bytes(),):
            raise CadConversionError("native footprint library did not preserve the exact STEP payload")

    return NativeAltiumConversion(
        symbol_library=symbol_library,
        footprint_library=footprint_library,
        symbol_entries=symbol_entries,
        footprint_entries=footprint_entries,
        source_sha256=library.source_sha256,
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lia", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--step", type=Path)
    parser.add_argument("--converter", type=Path)
    arguments = parser.parse_args()
    converted = convert_pcad_ascii(
        arguments.lia,
        arguments.output,
        step_model=arguments.step,
        converter_executable=arguments.converter,
    )
    print(
        json.dumps(
            {
                "symbol_library": str(converted.symbol_library),
                "footprint_library": str(converted.footprint_library),
                "symbol_entries": converted.symbol_entries,
                "footprint_entries": converted.footprint_entries,
                "source_sha256": converted.source_sha256,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["CadConversionError", "NativeAltiumConversion", "convert_pcad_ascii"]
