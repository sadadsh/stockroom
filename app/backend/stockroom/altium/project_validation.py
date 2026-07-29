"""Native Altium project validation in a disposable execution copy.

The checked Git worktree remains read-only. Altium receives a second temporary
copy because opening a project may create structure files and DRC requires a
temporary OutJob to be part of the project. Success means the native compiler
ran and every registered PCB produced a parseable DRC report.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from stockroom.altium.driver import AltiumDriver
from stockroom.model.project import ProjectRecord

_SCHEMA_VERSION = 1


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _pascal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _template_for(driver: AltiumDriver) -> Path | None:
    if driver.x2 is None:
        return None
    candidate = (
        Path("C:/Users/Public/Documents/Altium")
        / driver.x2.parent.name
        / "OutputJobs"
        / "Fabrication.OutJob"
    )
    return candidate if candidate.is_file() else None


def _set_line(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    if pattern.search(text):
        return pattern.sub(lambda _match: f"{key}={value}", text)
    return text


def _configure_drc_outjob(source: Path, target: Path, board_name: str) -> str:
    """Create one board-specific DRC-only OutJob and return its template hash."""

    raw = source.read_bytes()
    text = raw.decode("latin-1").replace("\r\n", "\n")
    output_match = re.search(r"(?m)^OutputType(\d+)=Design Rules Check$", text)
    medium_match = re.search(r"(?m)^OutputMedium(\d+)=Reports$", text)
    if output_match is None or medium_match is None:
        raise ValueError("installed Fabrication.OutJob has no DRC Reports mapping")
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
    text = _set_line(text, "TargetOutputMedium", "Reports")
    text = _set_line(text, f"OutputEnabled{output_index}", "1")
    text = _set_line(
        text,
        f"OutputEnabled{output_index}_OutputMedium{medium_index}",
        "1",
    )
    text = _set_line(text, f"OutputDocumentPath{output_index}", board_name)
    text = _set_line(text, f"OpenOutputs{medium_index}", "0")
    text = _set_line(text, f"AddToProject{medium_index}", "0")
    target.write_text(text, encoding="latin-1", newline="\r\n")
    return hashlib.sha256(raw).hexdigest()


def _next_document_index(descriptor: str) -> int:
    indexes = [
        int(match.group(1))
        for match in re.finditer(r"(?m)^\[Document(\d+)\]$", descriptor)
    ]
    return max(indexes, default=0) + 1


def _execution_descriptor(project: ProjectRecord, root: Path, outjobs: list[Path]) -> Path:
    descriptor = root / project.pro_path if project.pro_path else root / f"{project.name}.PrjPcb"
    if descriptor.is_file():
        text = descriptor.read_text(encoding="utf-8", errors="replace")
    else:
        text = "[Design]\nVersion=1.0\n"
        for index, relative in enumerate((*project.sheet_paths, *project.board_paths), 1):
            text += f"\n[Document{index}]\nDocumentPath={relative}\n"
    next_index = _next_document_index(text)
    for outjob in outjobs:
        text += f"\n[Document{next_index}]\nDocumentPath={outjob.name}\n"
        next_index += 1
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(text, encoding="utf-8", newline="\r\n")
    return descriptor


def _render_script(
    *,
    descriptor: Path,
    boards: list[tuple[Path, Path]],
    marker: Path,
) -> str:
    board_steps = []
    for board, outjob in boards:
        board_steps.append(
            f"""
        PcbDoc := Client.OpenDocument('PCB', '{_pascal(board)}');
        If PcbDoc = Nil Then
        Begin
            Lines.Add('PCB|{_pascal(board.name)}|blocked|document did not open');
        End
        Else
        Begin
            Client.ShowDocument(PcbDoc);
            OutJob := Client.OpenDocument('OUTPUTJOB', '{_pascal(outjob)}');
            If OutJob = Nil Then
            Begin
                Lines.Add('PCB|{_pascal(board.name)}|blocked|validation OutJob did not open');
            End
            Else
            Begin
                Client.ShowDocument(OutJob);
                ResetParameters;
                AddStringParameter('ObjectKind', 'OutputBatch');
                AddStringParameter('DisableDialog', 'True');
                AddStringParameter('OutputMedium', 'Reports');
                AddStringParameter('Action', 'Run');
                RunProcess('WorkspaceManager:GenerateReport');
                ResetParameters;
                Lines.Add('PCB|{_pascal(board.name)}|completed|DRC process returned');
                Client.CloseDocument(OutJob);
            End;
            Client.CloseDocument(PcbDoc);
        End;
"""
        )
    return f"""{{ GENERATED by stockroom.altium.project_validation. }}
Procedure RunStockroomProjectValidation;
Var
    WS          : IWorkspace;
    Prj         : IProject;
    PcbDoc      : IServerDocument;
    OutJob      : IServerDocument;
    Lines       : TStringList;
    CompileOk   : Boolean;
    I           : Integer;
    V           : IViolation;
    Level       : TErrorLevel;
    Errors      : Integer;
    Warnings    : Integer;
Begin
    Lines := TStringList.Create;
    Errors := 0;
    Warnings := 0;
    Try
        ResetParameters;
        AddStringParameter('ObjectKind', 'Project');
        AddStringParameter('FileName', '{_pascal(descriptor)}');
        RunProcess('WorkspaceManager:OpenObject');
        ResetParameters;
        WS := GetWorkspace;
        If WS = Nil Then
        Begin
            Lines.Add('STATUS|blocked|workspace unavailable');
            Lines.SaveToFile('{_pascal(marker)}');
            Exit;
        End;
        Prj := WS.DM_FocusedProject;
        If Prj = Nil Then
        Begin
            Lines.Add('STATUS|blocked|project did not become focused');
            Lines.SaveToFile('{_pascal(marker)}');
            Exit;
        End;

        Prj.DM_ClearViolations;
        CompileOk := Prj.DM_Compile;
        For I := 0 To Prj.DM_ViolationCount - 1 Do
        Begin
            V := Prj.DM_Violations(I);
            Level := Prj.DM_ErrorLevels(V.DM_ErrorKind);
            If (Level = eErrorLevelError) Or (Level = eErrorLevelFatal) Then
                Errors := Errors + 1
            Else If Level = eErrorLevelWarning Then
                Warnings := Warnings + 1;
        End;
        If CompileOk Then
            Lines.Add('SCHEMATIC|completed|1|' + IntToStr(Errors) + '|' +
                      IntToStr(Warnings) + '|' + IntToStr(Prj.DM_ViolationCount))
        Else
            Lines.Add('SCHEMATIC|completed|0|' + IntToStr(Errors) + '|' +
                      IntToStr(Warnings) + '|' + IntToStr(Prj.DM_ViolationCount));
        Lines.Add('DOCUMENTS|' + IntToStr(Prj.DM_LogicalDocumentCount) + '|' +
                  IntToStr(Prj.DM_PhysicalDocumentCount));
{''.join(board_steps)}
        Lines.Add('STATUS|completed|native checks returned');
        Lines.SaveToFile('{_pascal(marker)}');
    Except
        Lines.Add('STATUS|blocked|Altium script exception');
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


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.values.append(value)


def _number_after(values: list[str], label: str) -> int | None:
    try:
        index = values.index(label)
    except ValueError:
        return None
    for value in values[index + 1 : index + 5]:
        if value.isdigit():
            return int(value)
    return None


def parse_drc_report(path: Path) -> dict:
    body = path.read_bytes()
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    warnings = _number_after(parser.values, "Warnings:")
    violations = _number_after(parser.values, "Rule Violations:")
    if warnings is None or violations is None:
        return {
            "ok": False,
            "warnings": 0,
            "errors": 0,
            "detail": "Altium DRC report did not expose summary counts",
            "artifact": {
                "name": path.name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
        }
    return {
        "ok": True,
        "warnings": warnings,
        "errors": violations,
        "detail": (
            "No rule violations"
            if violations == 0
            else f"{violations} rule violation{'s' if violations != 1 else ''}"
        ),
        "artifact": {
            "name": path.name,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    }


def _parse_marker(text: str) -> dict:
    result: dict = {"status": "blocked", "detail": "native marker was incomplete", "pcbs": {}}
    invalid_detail = ""
    for raw in text.splitlines():
        fields = raw.strip().split("|")
        if not fields:
            continue
        try:
            if fields[0] == "STATUS" and len(fields) >= 3:
                result["status"] = fields[1]
                result["detail"] = fields[2]
            elif fields[0] == "SCHEMATIC" and len(fields) == 6:
                result["schematic"] = {
                    "completed": fields[1] == "completed",
                    "compile_ok": fields[2] == "1",
                    "errors": int(fields[3]),
                    "warnings": int(fields[4]),
                    "total": int(fields[5]),
                }
            elif fields[0] == "DOCUMENTS" and len(fields) == 3:
                result["documents"] = {
                    "logical": int(fields[1]),
                    "physical": int(fields[2]),
                }
            elif fields[0] == "PCB" and len(fields) >= 4:
                result["pcbs"][fields[1]] = {
                    "completed": fields[2] == "completed",
                    "detail": fields[3],
                }
        except ValueError:
            # The marker is tool output, not trusted program state.  A malformed count must fail
            # closed as an incomplete observation rather than crash the validation request.
            invalid_detail = f"native marker contained invalid numeric data: {raw.strip()}"
    if invalid_detail:
        result["status"] = "blocked"
        result["detail"] = invalid_detail
    return result


def _copy_project(source: Path, target: Path) -> None:
    def ignore(_root: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name == ".git" or name.lower().startswith("project outputs for ")
        }

    shutil.copytree(source, target, ignore=ignore)


def validate_altium_project(
    project: ProjectRecord,
    driver: AltiumDriver | None = None,
    *,
    timeout: int = 300,
) -> dict:
    drv = driver or AltiumDriver()
    blocked = {
        "schema_version": _SCHEMA_VERSION,
        "adapter": "altium",
        "status": "blocked",
        "runtime": {"name": "Altium Designer", "version": ""},
        "checks": [],
        "summary": {"checked": 0, "errors": 0, "warnings": 0},
    }
    if not drv.installed:
        result = {
            **blocked,
            "detail": "Altium Designer is not installed on this reviewer machine.",
        }
        result["digest"] = _digest(result)
        return result
    version = drv.x2.parent.name if drv.x2 else ""
    template = _template_for(drv)
    if project.board_paths and template is None:
        result = {
            **blocked,
            "runtime": {"name": "Altium Designer", "version": version},
            "detail": "The installed Altium Fabrication.OutJob template was not found.",
        }
        result["digest"] = _digest(result)
        return result

    source = Path(project.root).resolve()
    with tempfile.TemporaryDirectory(prefix="stockroom-altium-validation-") as raw:
        run_root = Path(raw) / "project"
        _copy_project(source, run_root)
        board_jobs: list[tuple[Path, Path]] = []
        template_hash = ""
        for index, relative in enumerate(project.board_paths, 1):
            if template is None:
                raise AssertionError("board validation template disappeared")
            board = run_root / relative
            outjob = run_root / f"Stockroom Validation {index}.OutJob"
            try:
                template_hash = _configure_drc_outjob(template, outjob, board.name)
            except (OSError, ValueError) as exc:
                result = {
                    **blocked,
                    "runtime": {"name": "Altium Designer", "version": version},
                    "detail": str(exc),
                }
                result["digest"] = _digest(result)
                return result
            board_jobs.append((board, outjob))

        descriptor = _execution_descriptor(
            project,
            run_root,
            [outjob for _board, outjob in board_jobs],
        )
        marker = Path(raw) / "Stockroom Project Validation.txt"
        script = Path(raw) / "StockroomProjectValidation.pas"
        script_project = Path(raw) / "StockroomProjectValidation.PrjScr"
        script.write_text(
            _render_script(descriptor=descriptor, boards=board_jobs, marker=marker),
            encoding="utf-8",
            newline="\r\n",
        )
        script_project.write_text(
            "[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n[Document1]\r\n"
            f"DocumentPath={script.name}\r\n",
            encoding="utf-8",
        )
        outcome = drv.run_script(
            project=script_project,
            proc=f"{script.name}>RunStockroomProjectValidation",
            marker=marker,
            timeout=timeout,
        )
        if not outcome.ok:
            result = {
                **blocked,
                "runtime": {"name": "Altium Designer", "version": version},
                "detail": outcome.detail,
            }
            result["digest"] = _digest(result)
            return result

        marker_result = _parse_marker(outcome.marker_text)
        checks: list[dict] = []
        schematic = marker_result.get("schematic")
        if project.sheet_paths:
            if schematic is None:
                checks.append(
                    {
                        "kind": "schematic",
                        "path": project.pro_path or project.name,
                        "status": "blocked",
                        "errors": 0,
                        "warnings": 0,
                        "detail": "Altium did not report schematic validation completion.",
                    }
                )
            else:
                errors = schematic["errors"]
                compile_ok = schematic["compile_ok"]
                completed = schematic["completed"]
                checks.append(
                    {
                        "kind": "schematic",
                        "path": project.pro_path or project.name,
                        "status": (
                            "passed"
                            if completed and compile_ok and errors == 0
                            else "failed" if completed else "blocked"
                        ),
                        "errors": errors,
                        "warnings": schematic["warnings"],
                        "detail": (
                            "Project validation passed"
                            if completed and compile_ok and errors == 0
                            else (
                                "Project validation reported errors"
                                if completed
                                else "Project validation did not report observable completion"
                            )
                        ),
                    }
                )

        reports = sorted(run_root.rglob("*.html"))
        unused = list(reports)
        for relative in project.board_paths:
            board_name = Path(relative).name
            report = next(
                (
                    candidate
                    for candidate in unused
                    if candidate.stem.casefold() == Path(board_name).stem.casefold()
                ),
                None,
            )
            if report is None:
                checks.append(
                    {
                        "kind": "pcb",
                        "path": relative,
                        "status": "blocked",
                        "errors": 0,
                        "warnings": 0,
                        "detail": "Altium returned without producing a DRC report.",
                    }
                )
                continue
            unused.remove(report)
            parsed = parse_drc_report(report)
            checks.append(
                {
                    "kind": "pcb",
                    "path": relative,
                    "status": (
                        "passed"
                        if parsed["ok"] and parsed["errors"] == 0
                        else "failed" if parsed["ok"] else "blocked"
                    ),
                    "errors": parsed["errors"],
                    "warnings": parsed["warnings"],
                    "detail": parsed["detail"],
                    "artifact": parsed["artifact"],
                }
            )

        errors = sum(check["errors"] for check in checks)
        warnings = sum(check["warnings"] for check in checks)
        marker_completed = marker_result.get("status") == "completed"
        all_passed = (
            marker_completed
            and bool(checks)
            and all(check["status"] == "passed" for check in checks)
        )
        any_failed = any(check["status"] == "failed" for check in checks)
        status = "passed" if all_passed else "failed" if any_failed else "blocked"
        result = {
            "schema_version": _SCHEMA_VERSION,
            "adapter": "altium",
            "status": status,
            "runtime": {"name": "Altium Designer", "version": version},
            "template_sha256": template_hash,
            "checks": checks,
            "summary": {
                "checked": len(checks),
                "errors": errors,
                "warnings": warnings,
            },
            "detail": (
                "All native checks passed"
                if status == "passed"
                else "Native checks found blockers"
            ),
        }
        result["digest"] = _digest(result)
        return result
