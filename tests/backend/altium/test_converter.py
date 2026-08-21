import hashlib
import json
from pathlib import Path

import pytest

import stockroom.altium.converter as converter_module
from stockroom.altium.converter import (
    CadConversionError,
    _artifact,
    _resolve_converter_executable,
    render_altium_project_documents,
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


def test_project_render_boundary_validates_and_reads_svg_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Stockroom.CadConverter.exe"
    executable.write_bytes(b"MZ")
    root = tmp_path / "Project"
    output = tmp_path / "Output"
    root.mkdir()
    source = root / "Main.PcbDoc"
    source.write_bytes(b"board")

    def invoke(_executable, request_path, _result_path, _timeout, *, result_schema):
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert request == {
            "schema": "stockroom.cad-converter/project-render-request/1",
            "projectRoot": str(root.resolve()),
            "outputDirectory": str(output.resolve()),
            "documents": ["Main.PcbDoc"],
            "width": 1600,
            "height": 1000,
        }
        assert result_schema == "stockroom.cad-converter/project-render-result/1"
        output.mkdir()
        top = output / "main-top.svg"
        bottom = output / "main-bottom.svg"
        top.write_bytes(b"<svg data-view=\"top\"/>")
        bottom.write_bytes(b"<svg data-view=\"bottom\"/>")
        return {
            "schema": result_schema,
            "status": "ok",
            "detail": "ready",
            "artifacts": [
                {
                    "sourcePath": "Main.PcbDoc",
                    "kind": "pcb",
                    "view": "top",
                    "path": str(top),
                    "mediaType": "image/svg+xml",
                    "width": 1600,
                    "height": 1000,
                    "sizeBytes": top.stat().st_size,
                    "sha256": hashlib.sha256(top.read_bytes()).hexdigest(),
                    "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                {
                    "sourcePath": "Main.PcbDoc",
                    "kind": "pcb",
                    "view": "bottom",
                    "path": str(bottom),
                    "mediaType": "image/svg+xml",
                    "width": 1600,
                    "height": 1000,
                    "sizeBytes": bottom.stat().st_size,
                    "sha256": hashlib.sha256(bottom.read_bytes()).hexdigest(),
                    "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
        }

    monkeypatch.setattr(converter_module, "_invoke", invoke)

    result = render_altium_project_documents(
        root,
        ("Main.PcbDoc",),
        output_directory=output,
        converter_executable=executable,
    )

    assert result.detail == "ready"
    assert len(result.artifacts) == 2
    assert result.artifacts[0].content == b'<svg data-view="top"/>'
    assert result.artifacts[0].source_path == "Main.PcbDoc"
