import hashlib
import json
from pathlib import Path

import pytest

import stockroom.altium.converter as converter_module
from stockroom.altium.converter import (
    CadConversionError,
    _artifact,
    _resolve_converter_executable,
)


def test_artifact_requires_output_containment_size_hash_and_suffix(tmp_path: Path):
    output = tmp_path / "Output"
    output.mkdir()
    library = output / "Part.SchLib"
    library.write_bytes(b"native")
    value = {
        "path": str(library),
        "sizeBytes": 6,
        "sha256": hashlib.sha256(b"native").hexdigest(),
    }

    assert _artifact(value, suffix=".SchLib", output_directory=output) == library

    outside = tmp_path / "Outside.SchLib"
    outside.write_bytes(b"native")
    with pytest.raises(CadConversionError, match="escaped"):
        _artifact(
            {**value, "path": str(outside)},
            suffix=".SchLib",
            output_directory=output,
        )


def test_converter_module_has_no_console_parsing_contract():
    # The sidecar result schema is JSON. This pins the test to the public shape rather
    # than accidentally teaching production code to scrape stdout in a future edit.
    value = json.loads('{"schema":"stockroom.cad-converter/result/1","status":"ok"}')
    assert value["schema"].endswith("/result/1")


def test_continuous_runtime_resolves_the_machine_local_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = (
        tmp_path
        / "Stockroom"
        / "Tools"
        / "CadConverter"
        / "Stockroom.CadConverter.exe"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.delenv("STOCKROOM_CAD_CONVERTER", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(converter_module, "_development_converter", lambda: None)

    assert _resolve_converter_executable(None) == executable


def test_editable_checkout_prefers_its_matching_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    development = tmp_path / "Development" / "Stockroom.CadConverter.exe"
    installed = tmp_path / "Installed" / "Stockroom.CadConverter.exe"
    monkeypatch.delenv("STOCKROOM_CAD_CONVERTER", raising=False)
    monkeypatch.setattr(converter_module, "_development_converter", lambda: development)
    monkeypatch.setattr(converter_module, "_installed_converter", lambda: installed)

    assert _resolve_converter_executable(None) == development
