"""Native project renders normalized into one KiCad/Altium review contract."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError
from stockroom.model.project import ProjectRecord
from stockroom.projects.board_scene import parse_ipc2581_board_scene

_SCHEMA_VERSION = 1
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")


@dataclass(frozen=True)
class VisualArtifact:
    """One immutable render payload kept outside the JSON evidence body."""

    media_type: str
    content: bytes


@dataclass(frozen=True)
class ProjectVisualBundle:
    """Serializable render evidence plus its separately served binary payloads."""

    evidence: dict
    artifacts: dict[str, VisualArtifact]


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _artifact_id(
    *,
    adapter: str,
    kind: str,
    path: str,
    view: str,
    page: int,
    content: bytes,
) -> str:
    identity = "\0".join((adapter, kind, path, view, str(page))).encode("utf-8")
    return hashlib.sha256(identity + b"\0" + content).hexdigest()


def _svg_dimensions(content: bytes) -> tuple[int, int]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return 0, 0
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        return 0, 0
    view_box = root.attrib.get("viewBox", "").split()
    if len(view_box) == 4:
        try:
            width = float(view_box[2])
            height = float(view_box[3])
            if (
                not math.isfinite(width)
                or not math.isfinite(height)
                or width <= 0
                or height <= 0
            ):
                return 0, 0
            return max(1, round(width)), max(1, round(height))
        except ValueError:
            pass

    def number(name: str) -> int:
        match = _NUMBER.match(root.attrib.get(name, ""))
        return max(0, round(float(match.group(0)))) if match else 0

    return number("width"), number("height")


def artifact_metadata(
    *,
    artifacts: dict[str, VisualArtifact],
    adapter: str,
    kind: str,
    path: str,
    view: str,
    label: str,
    page: int,
    content: bytes,
    media_type: str,
    width: int,
    height: int,
) -> dict:
    """Register one payload and return its deterministic public metadata."""

    artifact_id = _artifact_id(
        adapter=adapter,
        kind=kind,
        path=path,
        view=view,
        page=page,
        content=content,
    )
    artifacts[artifact_id] = VisualArtifact(media_type=media_type, content=content)
    return {
        "id": artifact_id,
        "kind": kind,
        "path": Path(path).as_posix(),
        "view": view,
        "label": label,
        "page": page,
        "media_type": media_type,
        "width": width,
        "height": height,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _blocked(adapter: str, runtime: dict, detail: str) -> ProjectVisualBundle:
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": adapter,
        "status": "blocked",
        "runtime": runtime,
        "documents": [],
        "summary": {"documents": 0, "artifacts": 0, "blocked": 1},
        "detail": detail,
    }
    body["digest"] = _digest(body)
    return ProjectVisualBundle(body, {})


def _render_kicad_schematic(
    cli: KiCadCli,
    project: ProjectRecord,
    relative: str,
    output: Path,
    artifacts: dict[str, VisualArtifact],
) -> dict:
    source = Path(project.root) / relative
    target = output / "schematic"
    target.mkdir(parents=True, exist_ok=True)
    before = set(target.glob("*.svg"))
    cli._run(
        "sch",
        "export",
        "svg",
        "--output",
        str(target),
        "--exclude-drawing-sheet",
        "--no-background-color",
        str(source),
    )
    rendered = sorted(set(target.glob("*.svg")) - before)
    if not rendered:
        return {
            "kind": "schematic",
            "path": relative,
            "status": "blocked",
            "detail": "KiCad returned without producing schematic SVG pages.",
            "artifacts": [],
        }
    pages: list[tuple[int, bytes, int, int]] = []
    for page, path in enumerate(rendered, 1):
        content = path.read_bytes()
        width, height = _svg_dimensions(content)
        if width <= 0 or height <= 0:
            return {
                "kind": "schematic",
                "path": relative,
                "status": "blocked",
                "detail": (
                    f"KiCad produced an invalid or dimensionless schematic SVG page {page}."
                ),
                "artifacts": [],
            }
        pages.append((page, content, width, height))

    # Register only after every page has been observed as a valid SVG.  A bad later page must not
    # leave a partial artifact set beside a blocked document.
    rows = []
    for page, content, width, height in pages:
        rows.append(
            artifact_metadata(
                artifacts=artifacts,
                adapter="kicad",
                kind="schematic",
                path=relative,
                view=f"page-{page}",
                label=f"Schematic page {page}",
                page=page,
                content=content,
                media_type="image/svg+xml",
                width=width,
                height=height,
            )
        )
    return {
        "kind": "schematic",
        "path": relative,
        "status": "ready",
        "detail": f"{len(rows)} native schematic page{'s' if len(rows) != 1 else ''}",
        "artifacts": rows,
    }


def _render_kicad_board_view(
    cli: KiCadCli,
    *,
    project: ProjectRecord,
    relative: str,
    output: Path,
    side: str,
    artifacts: dict[str, VisualArtifact],
) -> dict:
    source = Path(project.root) / relative
    target = output / f"{Path(relative).stem}-{side}.svg"
    layers = (
        "F.Cu,F.Mask,F.SilkS,Edge.Cuts"
        if side == "top"
        else "B.Cu,B.Mask,B.SilkS,Edge.Cuts"
    )
    args = [
        "pcb",
        "export",
        "svg",
        "--output",
        str(target),
        "--layers",
        layers,
        "--mode-single",
        "--page-size-mode",
        "2",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
    ]
    if side == "bottom":
        args.append("--mirror")
    args.append(str(source))
    cli._run(*args)
    if not target.is_file():
        raise KiCadCliError(f"KiCad returned without producing the {side} board SVG")
    content = target.read_bytes()
    width, height = _svg_dimensions(content)
    if width <= 0 or height <= 0:
        raise KiCadCliError(
            f"KiCad produced an invalid or dimensionless {side} board SVG"
        )
    return artifact_metadata(
        artifacts=artifacts,
        adapter="kicad",
        kind="pcb",
        path=relative,
        view=side,
        label=f"{side.title()} copper + mask + silkscreen",
        page=1 if side == "top" else 2,
        content=content,
        media_type="image/svg+xml",
        width=width,
        height=height,
    )


def _render_kicad_board(
    cli: KiCadCli,
    project: ProjectRecord,
    relative: str,
    output: Path,
    artifacts: dict[str, VisualArtifact],
) -> dict:
    pending: dict[str, VisualArtifact] = {}
    try:
        ipc2581 = output / f"{Path(relative).stem}-scene.xml"
        cli._run(
            "pcb",
            "export",
            "ipc2581",
            "--output",
            str(ipc2581),
            "--version",
            "C",
            "--units",
            "mm",
            str(Path(project.root) / relative),
        )
        if not ipc2581.is_file():
            raise KiCadCliError("KiCad returned without producing the interactive PCB scene")
        scene = parse_ipc2581_board_scene(ipc2581, board=relative)
        rows = [
            _render_kicad_board_view(
                cli,
                project=project,
                relative=relative,
                output=output,
                side=side,
                artifacts=pending,
            )
            for side in ("top", "bottom")
        ]
    except (KiCadCliError, OSError) as exc:
        return {
            "kind": "pcb",
            "path": relative,
            "status": "blocked",
            "detail": str(exc),
            "artifacts": [],
        }
    # A top/bottom pair is one observable board result. Do not publish the first view if the
    # second one failed validation: callers must never see a partial artifact set beside a
    # blocked board.
    artifacts.update(pending)
    return {
        "kind": "pcb",
        "path": relative,
        "status": "ready",
        "detail": "Native top and bottom board views with exact component geometry",
        "artifacts": rows,
        "scene": scene,
    }


def render_kicad_project(
    project: ProjectRecord,
    cli: KiCadCli | None = None,
) -> ProjectVisualBundle:
    """Render every registered KiCad schematic and PCB without opening the GUI."""

    native = cli or KiCadCli()
    if not native.available:
        return _blocked(
            "kicad",
            {"name": "KiCad CLI", "version": ""},
            "KiCad CLI is not installed on this reviewer machine.",
        )
    try:
        version = native.version()
    except KiCadCliError as exc:
        return _blocked("kicad", {"name": "KiCad CLI", "version": ""}, str(exc))

    artifacts: dict[str, VisualArtifact] = {}
    documents: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="stockroom-kicad-visual-") as raw:
        output = Path(raw)
        for relative in project.sheet_paths:
            try:
                documents.append(
                    _render_kicad_schematic(native, project, relative, output, artifacts)
                )
            except (KiCadCliError, OSError) as exc:
                documents.append(
                    {
                        "kind": "schematic",
                        "path": relative,
                        "status": "blocked",
                        "detail": str(exc),
                        "artifacts": [],
                    }
                )
        documents.extend(
            _render_kicad_board(native, project, relative, output, artifacts)
            for relative in project.board_paths
        )

    blocked = sum(row["status"] == "blocked" for row in documents)
    status = "ready" if documents and not blocked and artifacts else "blocked"
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "kicad",
        "status": status,
        "runtime": {"name": "KiCad CLI", "version": version},
        "documents": documents,
        "summary": {
            "documents": len(documents),
            "artifacts": len(artifacts),
            "blocked": blocked,
        },
        "detail": (
            "Native schematic and PCB views are ready"
            if status == "ready"
            else "One or more native views could not be rendered"
        ),
    }
    body["digest"] = _digest(body)
    return ProjectVisualBundle(body, artifacts)
