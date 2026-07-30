from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.projects.adapters import ProjectDocument
from stockroom.projects.native_open import open_project_document


def _document(path: str = "board.kicad_pcb") -> ProjectDocument:
    return ProjectDocument(
        document_id=f"pcb:{path}",
        path=path,
        label=Path(path).name,
        kind="pcb",
        exists=True,
    )


def test_open_project_document_launches_the_exact_adapter_reported_file(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    calls = []

    opened = open_project_document(
        tmp_path,
        "pcb:board.kicad_pcb",
        [_document()],
        opener=lambda path, action: calls.append((path, action)),
    )

    assert opened.path == "board.kicad_pcb"
    assert calls == [(str(board.resolve()), "open")]


def test_open_project_document_rejects_ids_the_adapter_did_not_report(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no such linked project document"):
        open_project_document(
            tmp_path,
            "pcb:other.kicad_pcb",
            [_document()],
            opener=lambda _path, _action: None,
        )


def test_open_project_document_rejects_an_adapter_path_outside_the_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.PcbDoc"
    outside.write_bytes(b"outside")
    escaped = _document("../outside.PcbDoc")

    with pytest.raises(ValueError, match="inside the project"):
        open_project_document(
            project,
            escaped.document_id,
            [escaped],
            opener=lambda _path, _action: None,
        )
