"""Native Altium IPC-2581 export for the shared interactive board scene."""

from __future__ import annotations

import hashlib
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
from stockroom.model.project import ProjectRecord
from stockroom.projects.board_scene import parse_ipc2581_board_scene

_SCHEMA_VERSION = 1


def _digest(value: object) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _source_snapshot(project: ProjectRecord) -> dict:
    rows = []
    root = Path(project.root)
    for relative in project.board_paths:
        path = root / relative
        if path.is_file():
            rows.append(
                {
                    "path": Path(relative).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return {"files": rows, "digest": _digest(rows)}


def _template_for(driver: AltiumDriver | Any) -> Path | None:
    x2 = getattr(driver, "x2", None)
    if x2 is None:
        return None
    candidate = (
        Path("C:/Users/Public/Documents/Altium")
        / Path(x2).parent.name
        / "OutputJobs"
        / "Fabrication.OutJob"
    )
    return candidate if candidate.is_file() else None


def _disable_outputs(text: str) -> str:
    text = re.sub(
        r"(?m)^OutputEnabled\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )
    return re.sub(
        r"(?m)^OutputEnabled\d+_OutputMedium\d+=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=0",
        text,
    )


def _configure_ipc2581_outjob(
    source: Path,
    target: Path,
    *,
    board_name: str,
    output_dir: Path,
) -> str:
    raw = source.read_bytes()
    text = raw.decode("latin-1").replace("\r\n", "\n")
    output_match = re.search(r"(?m)^OutputType(\d+)=IPC2581$", text)
    medium_match = re.search(r"(?m)^OutputMedium(\d+)=Fabrication$", text)
    if output_match is None or medium_match is None:
        raise ValueError("installed Fabrication.OutJob has no IPC-2581 folder mapping")
    output_index = output_match.group(1)
    medium_index = medium_match.group(1)
    text = _disable_outputs(text)
    text = _set_line(text, "TargetOutputMedium", "Fabrication")
    text = _set_line(text, f"OutputEnabled{output_index}", "1")
    text = _set_line(
        text,
        f"OutputEnabled{output_index}_OutputMedium{medium_index}",
        "1",
    )
    text = _set_line(text, f"OutputDocumentPath{output_index}", board_name)
    text = _set_line(text, f"OutputFilePath{medium_index}", str(output_dir))
    text = _set_line(text, f"ReleaseManaged{medium_index}", "0")
    text = _set_line(text, f"OutputBasePath{medium_index}", str(output_dir))
    text = _set_line(text, f"RelativeOutputPath{medium_index}", str(output_dir))
    text = _set_line(text, f"OpenOutputs{medium_index}", "0")
    text = _set_line(text, f"AddToProject{medium_index}", "0")
    text = _set_line(text, f"TimestampFolder{medium_index}", "0")
    text = _set_line(text, f"UseOutputName{medium_index}", "0")
    text = _set_line(text, f"OpenIPCOutput{medium_index}", "0")
    target.write_text(text, encoding="latin-1", newline="\r\n")
    return hashlib.sha256(raw).hexdigest()


def _render_script(
    *,
    descriptor: Path,
    jobs: list[tuple[str, Path, Path, Path]],
    marker: Path,
) -> str:
    steps = []
    output_comments = []
    for relative, board, outjob, output_dir in jobs:
        output_comments.append(f"{{OUTPUT|{output_dir}}}")
        steps.append(
            f"""
        PcbDoc := Client.OpenDocument('PCB', '{_pascal(board)}');
        If PcbDoc = Nil Then
            Lines.Add('BOARD|{_pascal(relative)}|blocked|PCB document did not open')
        Else
        Begin
            Client.ShowDocument(PcbDoc);
            OutJob := Client.OpenDocument('OUTPUTJOB', '{_pascal(outjob)}');
            If OutJob = Nil Then
                Lines.Add('BOARD|{_pascal(relative)}|blocked|IPC-2581 OutJob did not open')
            Else
            Begin
                Client.ShowDocument(OutJob);
                ResetParameters;
                AddStringParameter('ObjectKind', 'OutputBatch');
                AddStringParameter('DisableDialog', 'True');
                AddStringParameter('OutputMedium', 'Fabrication');
                AddStringParameter('Action', 'Run');
                RunProcess('WorkspaceManager:GenerateReport');
                ResetParameters;
                Lines.Add('BOARD|{_pascal(relative)}|completed|native IPC-2581 generation returned');
                Client.CloseDocument(OutJob);
            End;
            Client.CloseDocument(PcbDoc);
        End;
"""
        )
    return f"""{{ GENERATED by stockroom.altium.project_scene. }}
{chr(10).join(output_comments)}
Procedure ExportStockroomBoardScenes;
Var
    WS      : IWorkspace;
    Prj     : IProject;
    PcbDoc  : IServerDocument;
    OutJob  : IServerDocument;
    Lines   : TStringList;
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
            Lines.Add('STATUS|blocked|workspace unavailable')
        Else
        Begin
            Prj := WS.DM_FocusedProject;
            If Prj = Nil Then
                Lines.Add('STATUS|blocked|project did not become focused')
            Else
            Begin
                Prj.DM_Compile;
{''.join(steps)}
                Lines.Add('STATUS|completed|native board scenes returned');
            End;
        End;
        Lines.SaveToFile('{_pascal(marker)}');
    Except
        Lines.Add('STATUS|blocked|Altium board scene script exception');
        Lines.SaveToFile('{_pascal(marker)}');
    End;
    Lines.Free;
    ResetParameters;
    AddStringParameter('ObjectKind', 'All');
    RunProcess('WorkspaceManager:CloseObject');
    ResetParameters;
    RunProcess('DXP:Exit');
End;
"""


def _marker_status(text: str) -> tuple[str, str]:
    status = "blocked"
    detail = "native board scene marker was incomplete"
    board_failed = ""
    for raw in text.splitlines():
        fields = raw.strip().split("|")
        if fields[0] == "STATUS" and len(fields) >= 3:
            status, detail = fields[1], fields[2]
        elif fields[0] == "BOARD" and len(fields) >= 4 and fields[2] != "completed":
            board_failed = fields[3]
    if board_failed:
        return "blocked", board_failed
    return ("ready" if status == "completed" else "blocked"), detail


def export_altium_board_scenes(
    project: ProjectRecord,
    driver: AltiumDriver | Any | None = None,
    *,
    template: Path | None = None,
    timeout: int = 300,
) -> dict:
    """Export every registered board through Altium's native IPC-2581 OutJob."""

    native = driver or AltiumDriver()
    before = _source_snapshot(project)
    x2 = getattr(native, "x2", None)
    version = Path(x2).parent.name if x2 is not None else ""
    runtime = {"name": "Altium Designer", "version": version}
    blocked = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": "blocked",
        "runtime": runtime,
        "scenes": {},
    }
    if not native.installed:
        result = {
            **blocked,
            "source": {**before, "preserved": True},
            "detail": "Altium Designer is not installed on this reviewer machine.",
        }
        result["digest"] = _digest(result)
        return result
    outjob_template = template or _template_for(native)
    if outjob_template is None or not outjob_template.is_file():
        result = {
            **blocked,
            "source": {**before, "preserved": True},
            "detail": "The installed Altium Fabrication.OutJob template was not found.",
        }
        result["digest"] = _digest(result)
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="stockroom-altium-scene-") as raw:
            temp_root = Path(raw)
            run_root = temp_root / "project"
            shutil.copytree(
                Path(project.root),
                run_root,
                ignore=shutil.ignore_patterns(".git", "Project Outputs for *"),
            )
            jobs: list[tuple[str, Path, Path, Path]] = []
            template_hash = ""
            for index, relative in enumerate(project.board_paths, 1):
                board = run_root / relative
                if not board.is_file():
                    raise FileNotFoundError(f"registered PCB is missing: {relative}")
                output_dir = temp_root / "output" / str(index)
                output_dir.mkdir(parents=True)
                outjob = run_root / f"Stockroom Board Scene {index}.OutJob"
                template_hash = _configure_ipc2581_outjob(
                    outjob_template,
                    outjob,
                    board_name=board.name,
                    output_dir=output_dir,
                )
                jobs.append((relative, board, outjob, output_dir))
            descriptor = _execution_descriptor(
                project,
                run_root,
                [outjob for _relative, _board, outjob, _output in jobs],
            )
            marker = temp_root / "Stockroom Board Scenes.txt"
            script = temp_root / "StockroomBoardScenes.pas"
            script_project = temp_root / "StockroomBoardScenes.PrjScr"
            script.write_text(
                _render_script(descriptor=descriptor, jobs=jobs, marker=marker),
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
                proc=f"{script.name}>ExportStockroomBoardScenes",
                marker=marker,
                timeout=timeout,
            )
            if not outcome.ok:
                raise RuntimeError(outcome.detail)
            status, detail = _marker_status(outcome.marker_text)
            if status != "ready":
                raise RuntimeError(detail)
            scenes = {}
            for relative, _board, _outjob, output_dir in jobs:
                generated = sorted(
                    [*output_dir.rglob("*.cvg"), *output_dir.rglob("*.xml")]
                )
                if len(generated) != 1:
                    raise ValueError(
                        f"Altium produced {len(generated)} IPC-2581 files for "
                        f"{relative}; expected exactly one"
                    )
                scenes[relative] = parse_ipc2581_board_scene(
                    generated[0],
                    board=relative,
                )
    except Exception as exc:
        after = _source_snapshot(project)
        result = {
            **blocked,
            "source": {**before, "preserved": before == after},
            "detail": str(exc),
        }
        result["digest"] = _digest(result)
        return result

    after = _source_snapshot(project)
    preserved = before == after
    status = "ready" if preserved else "blocked"
    result = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": status,
        "runtime": runtime,
        "template_sha256": template_hash,
        "scenes": scenes if preserved else {},
        "source": {**before, "preserved": preserved},
        "detail": (
            "Native interactive PCB scenes are ready."
            if preserved
            else "Registered PCB source changed during native scene export."
        ),
    }
    result["digest"] = _digest(result)
    return result
