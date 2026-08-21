"""Normalize headless AltiumSharp SVG renders into Stockroom's visual contract."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from stockroom.altium.converter import (
    CadConversionError,
    render_altium_project_documents,
)
from stockroom.model.project import ProjectRecord
from stockroom.projects.project_visuals import (
    ProjectVisualBundle,
    VisualArtifact,
    artifact_metadata,
)

_SCHEMA_VERSION = 1
_RUNTIME = {"name": "Stockroom CAD Converter", "version": "AltiumSharp"}


def _digest(value: object) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _blocked(detail: str) -> ProjectVisualBundle:
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": "blocked",
        "runtime": _RUNTIME,
        "documents": [],
        "summary": {"documents": 0, "artifacts": 0, "blocked": 1},
        "detail": detail,
    }
    body["digest"] = _digest(body)
    return ProjectVisualBundle(body, {})


def render_altium_project(
    project: ProjectRecord,
    *,
    converter_executable: Path | None = None,
    timeout: int = 60,
) -> ProjectVisualBundle:
    """Render all registered Altium documents without starting Altium Designer."""

    documents = tuple((*project.sheet_paths, *project.board_paths))
    if not documents:
        return _blocked("This project has no Altium schematic or PCB documents.")
    try:
        with tempfile.TemporaryDirectory(prefix="stockroom-altium-svg-") as raw:
            rendered = render_altium_project_documents(
                Path(project.root),
                documents,
                output_directory=Path(raw) / "Output",
                converter_executable=converter_executable,
                timeout_seconds=timeout,
            )
    except (CadConversionError, OSError) as exc:
        return _blocked(str(exc))

    artifacts: dict[str, VisualArtifact] = {}
    grouped: dict[tuple[str, str], dict] = {}
    for native in rendered.artifacts:
        key = (native.kind, native.source_path)
        document = grouped.setdefault(
            key,
            {
                "kind": native.kind,
                "path": native.source_path,
                "status": "ready",
                "detail": "Headless Altium SVG is ready.",
                "artifacts": [],
            },
        )
        label = (
            "Schematic sheet"
            if native.kind == "schematic"
            else f"{native.view.title()} PCB"
        )
        document["artifacts"].append(
            artifact_metadata(
                artifacts=artifacts,
                adapter="altium",
                kind=native.kind,
                path=native.source_path,
                view=native.view,
                label=label,
                page=1,
                content=native.content,
                media_type=native.media_type,
                width=native.width,
                height=native.height,
            )
        )

    rows = list(grouped.values())
    status = "ready" if rows and artifacts else "blocked"
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": status,
        "runtime": _RUNTIME,
        "documents": rows,
        "summary": {
            "documents": len(rows),
            "artifacts": len(artifacts),
            "blocked": 0 if status == "ready" else 1,
        },
        "detail": rendered.detail,
    }
    body["digest"] = _digest(body)
    return ProjectVisualBundle(body, artifacts)
