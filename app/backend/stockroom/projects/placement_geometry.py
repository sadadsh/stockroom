"""Native, format-neutral PCB placement geometry for Projects.

Both adapters return the same coordinate contract. KiCad exports its native
position CSV through ``kicad-cli``. Altium generates its native Pick and Place
CSV through an installed Assembly OutJob. Neither path parses or mutates the
registered board file directly.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from stockroom.altium.driver import AltiumDriver
from stockroom.altium.project_validation import (
    _execution_descriptor,
    _pascal,
    _set_line,
)
from stockroom.kicad.cli import KiCadCli
from stockroom.model.project import ProjectRecord

_SCHEMA_VERSION = 1
_PLACEMENT_KEYS = (
    "reference",
    "board",
    "x_mm",
    "y_mm",
    "rotation_deg",
    "side",
    "footprint",
)


def _json_digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _source_snapshot(project: ProjectRecord) -> dict:
    root = Path(project.root)
    files = []
    for relative in project.board_paths:
        path = root / relative
        if not path.is_file():
            continue
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {"files": files, "digest": _json_digest(files)}


def _number(value: object) -> float:
    text = str(value or "").strip().lower()
    multiplier = 1.0
    if text.endswith("mm"):
        text = text[:-2].strip()
    elif text.endswith("mil"):
        text = text[:-3].strip()
        multiplier = 0.0254
    elif text.endswith("in"):
        text = text[:-2].strip()
        multiplier = 25.4
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return round(float(text) * multiplier, 6)


def _side(value: object) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "")
    if normalized in {"bottom", "back", "bottomlayer", "b.cu"}:
        return "bottom"
    if normalized in {"top", "front", "toplayer", "f.cu"}:
        return "top"
    raise ValueError(f"unknown placement side: {value}")


def _placement(
    *,
    reference: object,
    board: str,
    x: object,
    y: object,
    rotation: object,
    side: object,
    footprint: object,
) -> dict:
    ref = str(reference or "").strip()
    if not ref:
        raise ValueError("placement has no reference")
    row = {
        "reference": ref,
        "board": board,
        "x_mm": _number(x),
        "y_mm": _number(y),
        "rotation_deg": _number(rotation) % 360,
        "side": _side(side),
        "footprint": str(footprint or "").strip(),
    }
    if tuple(row) != _PLACEMENT_KEYS:
        raise AssertionError("normalized placement shape drifted")
    return row


def parse_kicad_position_csv(text: str, board: str) -> list[dict]:
    """Parse KiCad's native metric position CSV into the shared placement shape."""

    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        rows.append(
            _placement(
                reference=raw.get("Ref") or raw.get("Reference"),
                board=board,
                x=raw.get("PosX") or raw.get("Center-X"),
                y=raw.get("PosY") or raw.get("Center-Y"),
                rotation=raw.get("Rot") or raw.get("Rotation"),
                side=raw.get("Side") or raw.get("Layer"),
                footprint=raw.get("Package") or raw.get("Footprint"),
            )
        )
    return rows


def parse_altium_position_csv(text: str, board: str) -> list[dict]:
    """Parse Altium's native metric Pick and Place CSV into the shared shape."""

    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        rows.append(
            _placement(
                reference=raw.get("Designator") or raw.get("RefDes"),
                board=board,
                x=raw.get("Center-X") or raw.get("Center X"),
                y=raw.get("Center-Y") or raw.get("Center Y"),
                rotation=raw.get("Rotation"),
                side=raw.get("Layer"),
                footprint=raw.get("Footprint"),
            )
        )
    return rows


def _result(
    *,
    project: ProjectRecord,
    adapter: str,
    runtime: dict,
    status: str,
    placements: list[dict],
    boards: list[str],
    source_before: dict,
    source_after: dict,
    detail: str,
) -> dict:
    preserved = source_before == source_after
    if not preserved:
        status = "blocked"
        detail = "Registered PCB source changed during native placement readback."
    ordered = sorted(placements, key=lambda row: (row["board"].casefold(), row["reference"]))
    body = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": adapter,
        "status": status,
        "runtime": runtime,
        "boards": boards,
        "placements": ordered,
        "summary": {
            "boards": len(boards),
            "placements": len(ordered),
            "top": sum(row["side"] == "top" for row in ordered),
            "bottom": sum(row["side"] == "bottom" for row in ordered),
        },
        "source": {
            "digest": source_before["digest"],
            "files": source_before["files"],
            "preserved": preserved,
        },
        "detail": detail,
    }
    body["digest"] = _json_digest(body)
    return body


def board_geometry_from_visual_evidence(
    project: ProjectRecord,
    *,
    adapter: str,
    evidence: dict | None,
) -> dict:
    """Build the shared placement DTO from an already-rendered native scene.

    This is deliberately cache-only. Project selection and window-focus reads call this seam,
    so they must never launch KiCad, Altium, or a command window. The explicit Render PCB action
    owns native execution and stores the visual bundle that supplies these scenes.
    """

    source = _source_snapshot(project)
    runtime = (evidence or {}).get("runtime", {})
    documents = [
        document
        for document in (evidence or {}).get("documents", [])
        if document.get("kind") == "pcb" and document.get("scene")
    ]
    if not documents:
        return _result(
            project=project,
            adapter=adapter,
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source,
            source_after=_source_snapshot(project),
            detail=(evidence or {}).get("detail")
            or "Native PCB data is paused. Choose Render PCB to run the selected EDA tool.",
        )

    placements: list[dict] = []
    boards: list[str] = []
    for document in documents:
        board = str(document["path"])
        boards.append(board)
        placements.extend(
            _placement(
                reference=component.get("reference"),
                board=board,
                x=component.get("x_mm"),
                y=component.get("y_mm"),
                rotation=component.get("rotation_deg"),
                side=component.get("side"),
                footprint=component.get("package"),
            )
            for component in document["scene"].get("components", [])
        )
    return _result(
        project=project,
        adapter=adapter,
        runtime=runtime,
        status="ready",
        placements=placements,
        boards=boards,
        source_before=source,
        source_after=_source_snapshot(project),
        detail="Native PCB placement geometry is ready.",
    )


def kicad_board_geometry(
    project: ProjectRecord,
    cli: KiCadCli | None = None,
) -> dict:
    """Export all registered KiCad boards through the native position exporter."""

    native = cli or KiCadCli()
    source_before = _source_snapshot(project)
    runtime = {"name": "KiCad", "version": ""}
    if not native.available:
        return _result(
            project=project,
            adapter="kicad",
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source_before,
            source_after=_source_snapshot(project),
            detail="KiCad is not installed on this machine.",
        )
    try:
        runtime["version"] = native.version()
        placements: list[dict] = []
        boards: list[str] = []
        with tempfile.TemporaryDirectory(prefix="stockroom-kicad-placement-") as raw:
            run_root = Path(raw)
            for index, relative in enumerate(project.board_paths, 1):
                source = Path(project.root) / relative
                if not source.is_file():
                    raise FileNotFoundError(f"registered PCB is missing: {relative}")
                board = run_root / Path(relative).name
                shutil.copy2(source, board)
                output = run_root / f"positions-{index}.csv"
                native._run(
                    "pcb",
                    "export",
                    "pos",
                    "--format",
                    "csv",
                    "--units",
                    "mm",
                    "--side",
                    "both",
                    "--output",
                    str(output),
                    str(board),
                )
                if not output.is_file():
                    raise ValueError(f"KiCad did not produce placement CSV for {relative}")
                placements.extend(
                    parse_kicad_position_csv(
                        output.read_text(encoding="utf-8-sig"),
                        relative,
                    )
                )
                boards.append(relative)
    except Exception as exc:
        return _result(
            project=project,
            adapter="kicad",
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source_before,
            source_after=_source_snapshot(project),
            detail=str(exc),
        )
    return _result(
        project=project,
        adapter="kicad",
        runtime=runtime,
        status="ready",
        placements=placements,
        boards=boards,
        source_before=source_before,
        source_after=_source_snapshot(project),
        detail="Native PCB placement geometry is ready.",
    )


def _altium_template(driver: AltiumDriver | Any) -> Path | None:
    x2 = getattr(driver, "x2", None)
    if x2 is None:
        return None
    candidate = (
        Path("C:/Users/Public/Documents/Altium")
        / Path(x2).parent.name
        / "OutputJobs"
        / "Assembly.OutJob"
    )
    return candidate if candidate.is_file() else None


def _configure_altium_placement_outjob(
    source: Path,
    target: Path,
    *,
    board_name: str,
    output_dir: Path,
) -> str:
    raw = source.read_bytes()
    text = raw.decode("latin-1").replace("\r\n", "\n")
    output_match = re.search(r"(?m)^OutputType(\d+)=Pick Place$", text)
    medium_match = re.search(r"(?m)^OutputMedium(\d+)=AssemblyData$", text)
    if output_match is None or medium_match is None:
        raise ValueError("installed Assembly.OutJob has no Pick and Place output")
    output_index = output_match.group(1)
    medium_index = medium_match.group(1)
    text = re.sub(
        r"(?m)^OutputEnabled\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )
    text = re.sub(
        r"(?m)^OutputEnabled\d+_OutputMedium\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )
    text = _set_line(text, "TargetOutputMedium", "AssemblyData")
    text = _set_line(text, f"OutputEnabled{output_index}", "1")
    text = _set_line(
        text,
        f"OutputEnabled{output_index}_OutputMedium{medium_index}",
        "1",
    )
    text = _set_line(text, f"OutputDocumentPath{output_index}", board_name)
    text = _set_line(text, f"RelativeOutputPath{medium_index}", str(output_dir))
    text = _set_line(text, f"OpenOutputs{medium_index}", "0")
    text = _set_line(text, f"AddToProject{medium_index}", "0")
    text = _set_line(text, f"TimestampFolder{medium_index}", "0")
    text = _set_line(text, f"UseOutputName{medium_index}", "0")
    configuration = re.compile(
        rf"(?m)^(Configuration{re.escape(output_index)}_Item1=.*)$"
    )
    match = configuration.search(text)
    if match is None:
        raise ValueError("installed Assembly.OutJob has no Pick and Place configuration")
    configured = match.group(1)
    configured = re.sub(r"\|Units=[^|]*", "|Units=Metric", configured)
    configured = re.sub(
        r"\|GenerateCSVFormat=[^|]*",
        "|GenerateCSVFormat=True",
        configured,
    )
    configured = re.sub(
        r"\|GenerateTextFormat=[^|]*",
        "|GenerateTextFormat=False",
        configured,
    )
    text = text[: match.start()] + configured + text[match.end() :]
    target.write_text(text, encoding="latin-1", newline="\r\n")
    return hashlib.sha256(raw).hexdigest()


def _altium_export_script(
    *,
    descriptor: Path,
    jobs: list[tuple[str, Path, Path]],
    marker: Path,
) -> str:
    steps = []
    for relative, board, outjob in jobs:
        steps.append(
            f"""
        BoardDoc := Client.OpenDocument('PCB', '{_pascal(board)}');
        If BoardDoc = Nil Then
            Lines.Add('ERROR|{_pascal(relative)}|PCB document did not open')
        Else
        Begin
            Client.ShowDocument(BoardDoc);
            OutJob := Client.OpenDocument('OUTPUTJOB', '{_pascal(outjob)}');
            If OutJob = Nil Then
                Lines.Add('ERROR|{_pascal(relative)}|placement OutJob did not open')
            Else
            Begin
                Client.ShowDocument(OutJob);
                ResetParameters;
                AddStringParameter('ObjectKind', 'OutputBatch');
                AddStringParameter('DisableDialog', 'True');
                AddStringParameter('OutputMedium', 'AssemblyData');
                AddStringParameter('Action', 'Run');
                RunProcess('WorkspaceManager:GenerateFiles');
                ResetParameters;
                Lines.Add('BOARD|{_pascal(relative)}');
                Client.CloseDocument(OutJob);
            End;
            Client.CloseDocument(BoardDoc);
        End;
"""
        )
    return f"""{{ GENERATED by stockroom.projects.placement_geometry. }}
Procedure ExportStockroomBoardGeometry;
Var
    WS       : IWorkspace;
    Prj      : IProject;
    BoardDoc : IServerDocument;
    OutJob   : IServerDocument;
    Lines    : TStringList;
Begin
    Lines := TStringList.Create;
    Try
        ResetParameters;
        AddStringParameter('ObjectKind', 'Project');
        AddStringParameter('FileName', '{_pascal(descriptor)}');
        RunProcess('WorkspaceManager:OpenObject');
        ResetParameters;
        WS := GetWorkspace;
        If WS = Nil Then
            Lines.Add('ERROR|project|workspace unavailable')
        Else
        Begin
            Prj := WS.DM_FocusedProject;
            If Prj = Nil Then
                Lines.Add('ERROR|project|project did not become focused')
            Else
            Begin
                Prj.DM_Compile;
{''.join(steps)}
            End;
        End;
        Lines.Add('STATUS|completed|native placement export returned');
    Except
        Lines.Add('STATUS|blocked|Altium placement export exception');
    End;
    Lines.SaveToFile('{_pascal(marker)}');
    Lines.Free;
    ResetParameters;
    AddStringParameter('ObjectKind', 'All');
    RunProcess('WorkspaceManager:CloseObject');
    ResetParameters;
    RunProcess('DXP:Exit');
End;
"""


def _altium_marker(text: str) -> tuple[str, str, list[str]]:
    status = "blocked"
    detail = "native placement marker was incomplete"
    boards = []
    errors = []
    for raw in text.splitlines():
        fields = raw.strip().split("|")
        if fields[0] == "STATUS" and len(fields) >= 3:
            status, detail = fields[1], fields[2]
        elif fields[0] == "BOARD" and len(fields) == 2:
            boards.append(fields[1])
        elif fields[0] == "ERROR" and len(fields) >= 3:
            errors.append(fields[2])
    if errors:
        return "blocked", errors[0], boards
    return ("ready" if status == "completed" else "blocked"), detail, boards


def altium_board_geometry(
    project: ProjectRecord,
    driver: AltiumDriver | Any | None = None,
    *,
    timeout: int = 300,
    template: Path | None = None,
) -> dict:
    """Export all registered Altium boards through native Pick and Place jobs."""

    native = driver or AltiumDriver()
    source_before = _source_snapshot(project)
    x2 = getattr(native, "x2", None)
    version = Path(x2).parent.name if x2 is not None else ""
    runtime = {"name": "Altium Designer", "version": version}
    if not native.installed:
        return _result(
            project=project,
            adapter="altium",
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source_before,
            source_after=_source_snapshot(project),
            detail="Altium Designer is not installed on this machine.",
        )
    assembly_template = template or _altium_template(native)
    if assembly_template is None or not assembly_template.is_file():
        return _result(
            project=project,
            adapter="altium",
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source_before,
            source_after=_source_snapshot(project),
            detail="The installed Altium Assembly.OutJob template was not found.",
        )
    try:
        with tempfile.TemporaryDirectory(prefix="stockroom-altium-placement-") as raw:
            temp_root = Path(raw)
            run_root = temp_root / "project"
            shutil.copytree(
                Path(project.root),
                run_root,
                ignore=shutil.ignore_patterns(".git", "Project Outputs for *"),
            )
            boards = [(relative, run_root / relative) for relative in project.board_paths]
            missing = [relative for relative, path in boards if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"registered PCB is missing: {missing[0]}")
            output_root = run_root / "Stockroom Placement Output"
            output_root.mkdir()
            jobs = []
            outputs: list[tuple[str, Path]] = []
            outjobs = []
            for index, (relative, board) in enumerate(boards, 1):
                output_dir = output_root / str(index)
                output_dir.mkdir()
                outjob = run_root / f"Stockroom Placement {index}.OutJob"
                _configure_altium_placement_outjob(
                    assembly_template,
                    outjob,
                    board_name=Path(relative).name,
                    output_dir=output_dir,
                )
                jobs.append((relative, board, outjob))
                outputs.append((relative, output_dir))
                outjobs.append(outjob)
            descriptor = _execution_descriptor(project, run_root, outjobs)
            marker = temp_root / "Stockroom Board Geometry.txt"
            script = temp_root / "StockroomBoardGeometry.pas"
            script_project = temp_root / "StockroomBoardGeometry.PrjScr"
            script.write_text(
                _altium_export_script(
                    descriptor=descriptor,
                    jobs=jobs,
                    marker=marker,
                ),
                encoding="utf-8",
                newline="\r\n",
            )
            script_project.write_text(
                "[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n"
                f"[Document1]\r\nDocumentPath={script.name}\r\n",
                encoding="utf-8",
            )
            outcome = native.run_script(
                project=script_project,
                proc=f"{script.name}>ReadStockroomBoardGeometry",
                marker=marker,
                timeout=timeout,
            )
            if not outcome.ok:
                raise RuntimeError(outcome.detail)
            status, detail, completed_boards = _altium_marker(
                marker.read_text(encoding="utf-8", errors="replace")
            )
            placements = []
            if status == "ready":
                for relative, output_dir in outputs:
                    generated = sorted(output_dir.rglob("*.csv"))
                    if len(generated) != 1:
                        raise ValueError(
                            f"Altium produced {len(generated)} placement CSV files "
                            f"for {relative}; expected exactly one"
                        )
                    placements.extend(
                        parse_altium_position_csv(
                            generated[0].read_text(encoding="utf-8-sig"),
                            relative,
                        )
                    )
    except Exception as exc:
        return _result(
            project=project,
            adapter="altium",
            runtime=runtime,
            status="blocked",
            placements=[],
            boards=[],
            source_before=source_before,
            source_after=_source_snapshot(project),
            detail=str(exc),
        )
    return _result(
        project=project,
        adapter="altium",
        runtime=runtime,
        status=status,
        placements=placements,
        boards=completed_boards,
        source_before=source_before,
        source_after=_source_snapshot(project),
        detail=detail,
    )
