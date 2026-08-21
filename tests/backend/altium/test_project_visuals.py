from pathlib import Path

import pytest

import stockroom.altium.project_visuals as project_visuals
from stockroom.altium.converter import (
    CadConversionError,
    NativeProjectRender,
    NativeProjectRenderArtifact,
)
from stockroom.altium.project_visuals import render_altium_project
from stockroom.model.project import ProjectRecord


def _artifact(source: str, kind: str, view: str) -> NativeProjectRenderArtifact:
    return NativeProjectRenderArtifact(
        source_path=source,
        kind=kind,
        view=view,
        content=f'<svg data-source="{source}" data-view="{view}"/>'.encode(),
        media_type="image/svg+xml",
        width=1600,
        height=1000,
        source_sha256="a" * 64,
    )


def test_altium_visuals_use_converter_svg_without_altium_automation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = ProjectRecord(
        id="demo",
        name="Demo",
        root=tmp_path.as_posix(),
        eda="altium",
        sheet_paths=["Main.SchDoc"],
        board_paths=["Main.PcbDoc"],
    )
    (tmp_path / "Main.SchDoc").write_bytes(b"schematic")
    (tmp_path / "Main.PcbDoc").write_bytes(b"board")
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def render(root: Path, documents: tuple[str, ...], **_kwargs) -> NativeProjectRender:
        calls.append((root, documents))
        return NativeProjectRender(
            detail="Rendered 2 Altium project document(s).",
            artifacts=(
                _artifact("Main.SchDoc", "schematic", "sheet"),
                _artifact("Main.PcbDoc", "pcb", "top"),
                _artifact("Main.PcbDoc", "pcb", "bottom"),
            ),
        )

    monkeypatch.setattr(project_visuals, "render_altium_project_documents", render)

    bundle = render_altium_project(project)

    assert calls == [(tmp_path, ("Main.SchDoc", "Main.PcbDoc"))]
    assert bundle.evidence["status"] == "ready"
    assert bundle.evidence["runtime"] == {
        "name": "Stockroom CAD Converter",
        "version": "AltiumSharp",
    }
    assert [document["path"] for document in bundle.evidence["documents"]] == [
        "Main.SchDoc",
        "Main.PcbDoc",
    ]
    assert [item["view"] for item in bundle.evidence["documents"][1]["artifacts"]] == [
        "top",
        "bottom",
    ]
    assert len(bundle.artifacts) == 3
    assert all(item.media_type == "image/svg+xml" for item in bundle.artifacts.values())


def test_altium_visual_failure_is_a_normal_blocked_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project = ProjectRecord(
        id="demo",
        name="Demo",
        root=tmp_path.as_posix(),
        eda="altium",
        board_paths=["Main.PcbDoc"],
    )
    (tmp_path / "Main.PcbDoc").write_bytes(b"board")
    monkeypatch.setattr(
        project_visuals,
        "render_altium_project_documents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(CadConversionError("bad board")),
    )

    bundle = render_altium_project(project)

    assert bundle.evidence["status"] == "blocked"
    assert bundle.evidence["documents"] == []
    assert bundle.evidence["detail"] == "bad board"
    assert bundle.artifacts == {}


def test_ordinary_visual_module_has_no_altium_process_or_outjob_contract():
    source = Path(project_visuals.__file__).read_text(encoding="utf-8")

    assert "AltiumDriver" not in source
    assert "run_script" not in source
    assert "OutJob" not in source
    assert "pypdfium2" not in source
