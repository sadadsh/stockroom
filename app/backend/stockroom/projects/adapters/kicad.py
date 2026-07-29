"""KiCad implementation of the shared Projects adapter contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from stockroom.kicad.cli import KiCadCli
from stockroom.model.project import ProjectRecord
from stockroom.projects.checks import project_checks
from stockroom.projects.fill import read_components
from stockroom.projects.placement_geometry import kicad_board_geometry
from stockroom.projects.project_visuals import ProjectVisualBundle, render_kicad_project
from stockroom.sexp.document import SexpDocument

from .models import (
    DetectedProject,
    ProjectDescription,
    ProjectDocument,
    RuntimeReport,
)


class KiCadProjectAdapter:
    key = "kicad"
    label = "KiCad"

    def __init__(self, cli: KiCadCli | None = None) -> None:
        self.cli = cli or KiCadCli()

    @staticmethod
    def _root(candidate: Path) -> Path:
        return candidate.parent if candidate.is_file() else candidate

    def detect(self, candidate: Path) -> list[DetectedProject]:
        candidate = Path(candidate)
        root = self._root(candidate)
        if not root.is_dir():
            return []
        descriptors = (
            [candidate]
            if candidate.is_file() and candidate.suffix.lower() == ".kicad_pro"
            else sorted(root.glob("*.kicad_pro"))
        )
        if descriptors:
            return [
                DetectedProject(self.key, descriptor, root, descriptor.stem)
                for descriptor in descriptors
            ]
        boards = sorted(root.glob("*.kicad_pcb"))
        schematics = sorted(root.glob("*.kicad_sch"))
        if not (boards or schematics):
            return []
        first = boards[0] if boards else schematics[0]
        return [DetectedProject(self.key, root, root, first.stem)]

    def describe(self, detected: DetectedProject) -> ProjectDescription:
        root = detected.root
        descriptor = (
            detected.descriptor.name
            if detected.descriptor.is_file() and detected.descriptor.suffix.lower() == ".kicad_pro"
            else ""
        )
        boards = tuple(path.name for path in sorted(root.glob("*.kicad_pcb")))
        schematics = tuple(path.name for path in sorted(root.glob("*.kicad_sch")))
        return ProjectDescription(
            adapter_key=self.key,
            root=root,
            descriptor=descriptor,
            name=Path(descriptor).stem if descriptor else detected.name,
            boards=boards,
            schematics=schematics,
        )

    def runtime(self, project: ProjectRecord) -> RuntimeReport:
        del project
        if not self.cli.available:
            return RuntimeReport(
                self.key,
                False,
                "unavailable",
                detail="Install KiCad to render, validate, edit, and release this project.",
            )
        try:
            version = self.cli.version()
        except Exception as exc:
            return RuntimeReport(self.key, False, "error", detail=str(exc))
        return RuntimeReport(self.key, True, "ready", version=version)

    def documents(self, project: ProjectRecord) -> list[ProjectDocument]:
        root = Path(project.root)
        rows: list[ProjectDocument] = []
        if project.pro_path:
            rows.append(
                ProjectDocument(
                    f"project:{project.pro_path}",
                    project.pro_path,
                    Path(project.pro_path).name,
                    "project",
                    (root / project.pro_path).exists(),
                )
            )
        for kind, paths in (
            ("schematic", project.sheet_paths),
            ("pcb", project.board_paths),
        ):
            rows.extend(
                ProjectDocument(
                    f"{kind}:{path}",
                    path,
                    Path(path).name,
                    kind,
                    (root / path).exists(),
                )
                for path in paths
            )
        return rows

    def placements(self, project: ProjectRecord) -> list[dict]:
        root = Path(project.root)
        out: list[dict] = []
        for rel in project.sheet_paths:
            path = root / rel
            if not path.exists():
                continue
            for component in read_components(SexpDocument.load(path)):
                component["_sheet"] = rel
                out.append(component)
        return out

    def board_geometry(self, project: ProjectRecord) -> dict:
        return kicad_board_geometry(project, self.cli)

    def validate(self, project: ProjectRecord) -> dict:
        runtime = {"name": "KiCad", "version": ""}
        if not self.cli.available:
            result = {
                "schema_version": 1,
                "adapter": self.key,
                "status": "blocked",
                "runtime": runtime,
                "checks": [],
                "summary": {"checked": 0, "errors": 0, "warnings": 0},
                "detail": "KiCad is not installed on this reviewer machine.",
            }
            result["digest"] = _digest(result)
            return result
        try:
            runtime["version"] = self.cli.version()
        except Exception as exc:
            result = {
                "schema_version": 1,
                "adapter": self.key,
                "status": "blocked",
                "runtime": runtime,
                "checks": [],
                "summary": {"checked": 0, "errors": 0, "warnings": 0},
                "detail": f"KiCad version check failed: {exc}",
            }
            result["digest"] = _digest(result)
            return result

        native = project_checks(
            project.root,
            project.pro_path,
            project.board_paths,
            project.sheet_paths,
            self.cli.binary,
            name=project.name,
        )
        checks: list[dict] = []
        if native["erc"] is not None:
            checks.append(_kicad_check("schematic", native["erc"]["sheet"], native["erc"]))
        checks.extend(_kicad_check("pcb", check["board"], check) for check in native["drc"])
        errors = sum(check["errors"] for check in checks)
        warnings = sum(check["warnings"] for check in checks)
        all_passed = bool(checks) and all(check["status"] == "passed" for check in checks)
        any_failed = any(check["status"] == "failed" for check in checks)
        status = "passed" if all_passed else "failed" if any_failed else "blocked"
        result = {
            "schema_version": 1,
            "adapter": self.key,
            "status": status,
            "runtime": runtime,
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

    def render(self, project: ProjectRecord) -> ProjectVisualBundle:
        return render_kicad_project(project, self.cli)


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _kicad_check(kind: str, path: str, raw: dict) -> dict:
    summary = raw.get("summary") or {}
    if not raw.get("ok"):
        status = "blocked"
        detail = raw.get("error") or "KiCad did not produce a valid report."
    elif summary.get("errors", 0):
        status = "failed"
        detail = f"{summary['errors']} native error{'s' if summary['errors'] != 1 else ''}"
    else:
        status = "passed"
        detail = "Native check passed"
    return {
        "kind": kind,
        "path": path,
        "status": status,
        "errors": summary.get("errors", 0),
        "warnings": summary.get("warnings", 0),
        "detail": detail,
        "findings": raw.get("findings", []),
    }
