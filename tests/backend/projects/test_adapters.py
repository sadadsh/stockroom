"""The same project-selection/document contract for KiCad and Altium."""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.model.project import ProjectRecord
from stockroom.projects.adapters import detect_project, get_adapter
from stockroom.projects.adapters.altium import AltiumProjectAdapter
from stockroom.projects.adapters.kicad import KiCadProjectAdapter
from stockroom.projects.project_visuals import ProjectVisualBundle


def _project(root: Path, tool: str) -> ProjectRecord:
    description = detect_project(root, requested=tool)
    return ProjectRecord(
        id=description.name.lower(),
        name=description.name,
        root=root.as_posix(),
        pro_path=description.descriptor,
        board_paths=list(description.boards),
        sheet_paths=list(description.schematics),
        eda=tool,
    )


def _write_kicad(root: Path) -> None:
    (root / "Amp.kicad_pro").write_text("{}", encoding="utf-8")
    (root / "Amp.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    (root / "Amp.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")


def _write_altium(root: Path) -> None:
    (root / "Amp.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Sheets\\Power.SchDoc\n"
        "[Document2]\nDocumentPath=Amp.PcbDoc\n",
        encoding="utf-8",
    )
    sheets = root / "Sheets"
    sheets.mkdir()
    (sheets / "Power.SchDoc").write_bytes(b"binary")
    (root / "Amp.PcbDoc").write_bytes(b"binary")


@pytest.mark.parametrize(
    ("tool", "writer", "descriptor", "schematic", "board"),
    [
        ("kicad", _write_kicad, "Amp.kicad_pro", "Amp.kicad_sch", "Amp.kicad_pcb"),
        ("altium", _write_altium, "Amp.PrjPcb", "Sheets/Power.SchDoc", "Amp.PcbDoc"),
    ],
)
def test_adapters_share_selection_and_document_contract(
    tmp_path, tool, writer, descriptor, schematic, board
):
    root = tmp_path / tool
    root.mkdir()
    writer(root)

    description = detect_project(root)
    assert description.adapter_key == tool
    assert description.descriptor == descriptor
    assert description.schematics == (schematic,)
    assert description.boards == (board,)

    documents = get_adapter(tool).documents(_project(root, tool))
    assert [(document.kind, document.path) for document in documents] == [
        ("project", descriptor),
        ("schematic", schematic),
        ("pcb", board),
    ]
    assert all(document.exists and document.lock_required for document in documents)


def test_mixed_tool_directory_requires_an_explicit_selection(tmp_path):
    _write_kicad(tmp_path)
    _write_altium(tmp_path)
    with pytest.raises(ValueError, match="both KiCad and Altium"):
        detect_project(tmp_path)
    assert detect_project(tmp_path, requested="kicad").adapter_key == "kicad"
    assert detect_project(tmp_path, requested="altium").adapter_key == "altium"


def test_multiple_descriptors_of_one_tool_are_not_silently_guessed(tmp_path):
    _write_kicad(tmp_path)
    (tmp_path / "Other.kicad_pro").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple"):
        detect_project(tmp_path)


def test_kicad_adapter_normalizes_native_erc_and_drc(monkeypatch, tmp_path):
    class Cli:
        available = True
        binary = "kicad-cli"

        @staticmethod
        def version():
            return "10.0.4"

    monkeypatch.setattr(
        "stockroom.projects.adapters.kicad.project_checks",
        lambda *_args, **_kwargs: {
            "erc": {
                "ok": True,
                "sheet": "Amp.kicad_sch",
                "summary": {"errors": 0, "warnings": 1},
                "findings": [{"severity": "warning", "rule": "pin", "message": "open"}],
            },
            "drc": [
                {
                    "ok": True,
                    "board": "Amp.kicad_pcb",
                    "summary": {"errors": 0, "warnings": 0},
                    "findings": [],
                }
            ],
        },
    )
    project = ProjectRecord(
        id="amp",
        name="Amp",
        root=tmp_path.as_posix(),
        pro_path="Amp.kicad_pro",
        sheet_paths=["Amp.kicad_sch"],
        board_paths=["Amp.kicad_pcb"],
        eda="kicad",
    )

    result = KiCadProjectAdapter(Cli()).validate(project)

    assert result["status"] == "passed"
    assert result["runtime"]["version"] == "10.0.4"
    assert result["summary"] == {"checked": 2, "errors": 0, "warnings": 1}
    assert [check["kind"] for check in result["checks"]] == ["schematic", "pcb"]


def test_kicad_adapter_never_calls_an_unavailable_runtime(tmp_path):
    class Cli:
        available = False
        binary = None

    project = ProjectRecord(
        id="amp",
        name="Amp",
        root=tmp_path.as_posix(),
        pro_path="Amp.kicad_pro",
        eda="kicad",
    )

    result = KiCadProjectAdapter(Cli()).validate(project)

    assert result["status"] == "blocked"
    assert result["summary"]["checked"] == 0
    assert "not installed" in result["detail"]


def test_altium_artwork_and_geometry_share_one_native_scene_run(monkeypatch, tmp_path):
    board = tmp_path / "Amp.PcbDoc"
    board.write_bytes(b"native")
    project = ProjectRecord(
        id="amp",
        name="Amp",
        root=tmp_path.as_posix(),
        pro_path="Amp.PrjPcb",
        board_paths=["Amp.PcbDoc"],
        eda="altium",
    )
    calls = []
    scene = {
        "components": [
            {
                "reference": "R1",
                "x_mm": 10.0,
                "y_mm": 20.0,
                "rotation_deg": 90.0,
                "side": "top",
                "package": "R_0402",
            }
        ]
    }

    def render(_project, _driver):
        calls.append(_project.id)
        return ProjectVisualBundle(
            {
                "status": "ready",
                "runtime": {"name": "Altium Designer", "version": "AD26"},
                "documents": [
                    {
                        "kind": "pcb",
                        "path": "Amp.PcbDoc",
                        "status": "ready",
                        "scene": scene,
                        "artifacts": [],
                    }
                ],
            },
            {},
        )

    monkeypatch.setattr(
        "stockroom.projects.adapters.altium.render_altium_project",
        render,
    )
    adapter = AltiumProjectAdapter(driver=object())

    adapter.render(project)
    geometry = adapter.board_geometry(project)

    assert calls == ["amp"]
    assert geometry["status"] == "ready"
    assert geometry["placements"][0] == {
        "reference": "R1",
        "board": "Amp.PcbDoc",
        "x_mm": 10.0,
        "y_mm": 20.0,
        "rotation_deg": 90.0,
        "side": "top",
        "footprint": "R_0402",
    }


def test_altium_render_cache_never_crosses_project_roots(monkeypatch, tmp_path):
    calls = []

    def render(project, _driver):
        calls.append(project.id)
        return ProjectVisualBundle(
            {
                "status": "blocked",
                "runtime": {"name": "Altium Designer", "version": "AD26"},
                "documents": [],
                "detail": project.id,
            },
            {},
        )

    monkeypatch.setattr(
        "stockroom.projects.adapters.altium.render_altium_project",
        render,
    )
    adapter = AltiumProjectAdapter(driver=object())
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = ProjectRecord(id="first", name="First", root=first_root.as_posix(), eda="altium")
    second = ProjectRecord(
        id="second",
        name="Second",
        root=second_root.as_posix(),
        eda="altium",
    )

    assert adapter.render(first).evidence["detail"] == "first"
    assert adapter.render(second).evidence["detail"] == "second"
    assert calls == ["first", "second"]
