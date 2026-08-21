"""Altium implementation of the shared Projects adapter contract."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from stockroom.altium.driver import AltiumDriver
from stockroom.altium.project_validation import validate_altium_project
from stockroom.altium.project_visuals import render_altium_project
from stockroom.altium.schdoc import read_schdoc_components
from stockroom.model.project import ProjectRecord
from stockroom.projects.matching import AltiumProjectMatchStrategy
from stockroom.projects.project_visuals import ProjectVisualBundle

from .models import (
    DetectedProject,
    ProjectDescription,
    ProjectDocument,
    RuntimeReport,
)

_DOCUMENT_PATH = re.compile(r"^DocumentPath=(.+)$", re.MULTILINE)


def _listed_documents(descriptor: Path) -> list[str]:
    try:
        text = descriptor.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    documents: list[str] = []
    for match in _DOCUMENT_PATH.finditer(text):
        path = match.group(1).strip().replace("\\", "/")
        if path and path not in documents:
            documents.append(path)
    return documents


class AltiumProjectAdapter:
    key = "altium"
    label = "Altium Designer"
    matching = AltiumProjectMatchStrategy()

    def __init__(self, driver: AltiumDriver | None = None) -> None:
        self.driver = driver or AltiumDriver()
        self._render_lock = threading.Lock()
        self._render_cache: dict[str, tuple[tuple, ProjectVisualBundle]] = {}

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
            if candidate.is_file() and candidate.suffix.lower() == ".prjpcb"
            else sorted(root.glob("*.PrjPcb"))
        )
        if descriptors:
            return [
                DetectedProject(self.key, descriptor, root, descriptor.stem)
                for descriptor in descriptors
            ]
        boards = sorted(root.glob("*.PcbDoc"))
        schematics = sorted(root.glob("*.SchDoc"))
        if not (boards or schematics):
            return []
        first = boards[0] if boards else schematics[0]
        return [DetectedProject(self.key, root, root, first.stem)]

    def describe(self, detected: DetectedProject) -> ProjectDescription:
        root = detected.root
        descriptor = (
            detected.descriptor.name
            if detected.descriptor.is_file() and detected.descriptor.suffix.lower() == ".prjpcb"
            else ""
        )
        listed = _listed_documents(detected.descriptor) if descriptor else []
        schematics = [path for path in listed if path.lower().endswith(".schdoc")]
        boards = [path for path in listed if path.lower().endswith(".pcbdoc")]
        for path in sorted(root.glob("*.SchDoc")):
            if path.name not in schematics:
                schematics.append(path.name)
        for path in sorted(root.glob("*.PcbDoc")):
            if path.name not in boards:
                boards.append(path.name)
        name = Path(descriptor).stem if descriptor else detected.name
        return ProjectDescription(
            adapter_key=self.key,
            root=root,
            descriptor=descriptor,
            name=name,
            boards=tuple(boards),
            schematics=tuple(schematics),
        )

    def runtime(self, project: ProjectRecord) -> RuntimeReport:
        """Report passive install readiness without probing running processes."""

        del project
        if not self.driver.installed:
            return RuntimeReport(
                self.key,
                False,
                "unavailable",
                detail=(
                    "Install Altium Designer to validate, edit, and release this project."
                ),
            )
        version = self.driver.x2.parent.name if self.driver.x2 else ""
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
        seen: set[tuple[str, str]] = set()
        for rel in project.sheet_paths:
            path = root / rel
            if not path.exists():
                continue
            try:
                components = read_schdoc_components(path)
            except Exception:
                continue
            for component in components:
                ref = component["designator"]
                key = (ref, component["lib_ref"])
                if ref and key in seen:
                    continue
                seen.add(key)
                props = dict(component["params"])
                props["Reference"] = ref
                if not (props.get("Footprint") or "").strip():
                    props["Footprint"] = component["footprint"]
                if not (props.get("MPN") or "").strip() and component["design_item_id"].strip():
                    props["MPN"] = component["design_item_id"]
                out.append(
                    {
                        "ref": ref,
                        "uuid": component["unique_id"],
                        "lib_id": (
                            f"altium:{component['lib_ref']}" if component["lib_ref"] else ""
                        ),
                        "value": props.get("Value", ""),
                        "footprint": props.get("Footprint", ""),
                        "props": props,
                        "_sheet": rel,
                    }
                )
        return out

    def board_geometry(self, project: ProjectRecord) -> dict:
        bundle = self._render_shared(project)
        documents = [
            document
            for document in bundle.evidence.get("documents", [])
            if document.get("kind") == "pcb" and document.get("scene")
        ]
        if not documents:
            return _blocked_geometry(project, bundle.evidence)
        placements = []
        for document in documents:
            placements.extend(
                {
                    "reference": component["reference"],
                    "board": document["path"],
                    "x_mm": component["x_mm"],
                    "y_mm": component["y_mm"],
                    "rotation_deg": component["rotation_deg"],
                    "side": component["side"],
                    "footprint": component["package"],
                }
                for component in document["scene"]["components"]
            )
        placements.sort(key=lambda row: (row["board"].casefold(), row["reference"]))
        source_files = []
        for relative in project.board_paths:
            path = Path(project.root) / relative
            if path.is_file():
                source_files.append(
                    {
                        "path": relative,
                        "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        result = {
            "schema_version": 1,
            "adapter": self.key,
            "status": "ready",
            "runtime": bundle.evidence["runtime"],
            "boards": [document["path"] for document in documents],
            "placements": placements,
            "summary": {
                "boards": len(documents),
                "placements": len(placements),
                "top": sum(row["side"] == "top" for row in placements),
                "bottom": sum(row["side"] == "bottom" for row in placements),
            },
            "source": {
                "digest": _digest(source_files),
                "files": source_files,
                "preserved": True,
            },
            "detail": "Native PCB placement geometry is ready.",
        }
        result["digest"] = _digest(result)
        return result

    def validate(self, project: ProjectRecord) -> dict:
        return validate_altium_project(project, self.driver)

    def render(self, project: ProjectRecord) -> ProjectVisualBundle:
        return self._render_shared(project)

    def _render_shared(self, project: ProjectRecord) -> ProjectVisualBundle:
        """Coalesce concurrent geometry and artwork requests into one Altium run."""

        key = (
            Path(project.root).resolve().as_posix(),
            project.pro_path,
            tuple(
                (
                    relative,
                    (Path(project.root) / relative).stat().st_size,
                    (Path(project.root) / relative).stat().st_mtime_ns,
                )
                for relative in (*project.sheet_paths, *project.board_paths)
                if (Path(project.root) / relative).is_file()
            ),
        )
        cache_id = Path(project.root).resolve().as_posix().casefold()
        with self._render_lock:
            cached = self._render_cache.get(cache_id)
            if cached is not None and cached[0] == key:
                return cached[1]
            bundle = render_altium_project(project)
            if bundle.evidence.get("status") == "ready":
                self._render_cache[cache_id] = (key, bundle)
                return bundle
            if cached is None or cached[1].evidence.get("status") != "ready":
                return bundle
            evidence = dict(cached[1].evidence)
            evidence.pop("digest", None)
            evidence["stale"] = True
            evidence["detail"] = (
                f"{bundle.evidence.get('detail') or 'Fresh render failed'} "
                "Showing the last valid render."
            )
            evidence["digest"] = _digest(evidence)
            return ProjectVisualBundle(evidence, cached[1].artifacts)


def _digest(value: object) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _blocked_geometry(project: ProjectRecord, evidence: dict) -> dict:
    result = {
        "schema_version": 1,
        "adapter": "altium",
        "status": "blocked",
        "runtime": evidence.get("runtime", {}),
        "boards": [],
        "placements": [],
        "summary": {"boards": 0, "placements": 0, "top": 0, "bottom": 0},
        "source": {"digest": "", "files": [], "preserved": True},
        "detail": evidence.get("detail") or (
            f"Native placement geometry is not available for {project.name}."
        ),
    }
    result["digest"] = _digest(result)
    return result
