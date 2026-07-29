"""Independent review evidence generated from one exact Git commit.

The reviewer, not the author, builds this snapshot inside ReviewManager's detached
disposable worktree. KiCad and Altium terminate at the existing native readers;
the evidence contract above them is deliberately identical.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from stockroom.model.project import ProjectRecord
from stockroom.projects.adapters import get_adapter
from stockroom.projects.bom import project_bom
from stockroom.projects.collaboration import ReviewCandidate, ReviewManager
from stockroom.projects.health import audit_altium_project, audit_project

_SCHEMA_VERSION = 1


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _project_in_worktree(project: ProjectRecord, worktree: Path) -> ProjectRecord:
    if not project.git_root:
        raise ValueError("review evidence requires a linked Git repository")
    project_root = Path(project.root).resolve()
    git_root = Path(project.git_root).resolve()
    try:
        relative_root = project_root.relative_to(git_root)
    except ValueError as exc:
        raise ValueError("the linked project root is outside its Git repository") from exc
    snapshot_root = (Path(worktree) / relative_root).resolve()
    return replace(
        project,
        root=snapshot_root.as_posix(),
        git_root=Path(worktree).resolve().as_posix(),
        audit_digest=None,
        # Machine-local fallback bindings cannot prove what the exact commit contains.
        bindings={},
    )


def _document_kind(project: ProjectRecord, path: str) -> str:
    if path == project.pro_path:
        return "project"
    if path in project.board_paths:
        return "pcb"
    return "schematic"


def _document_evidence(project: ProjectRecord) -> tuple[list[dict], list[dict]]:
    root = Path(project.root).resolve()
    registered = [
        path
        for path in (
            project.pro_path,
            *project.board_paths,
            *project.sheet_paths,
        )
        if path
    ]
    documents: list[dict] = []
    blockers: list[dict] = []
    for relative in dict.fromkeys(registered):
        absolute = (root / relative).resolve()
        try:
            absolute.relative_to(root)
        except ValueError:
            blockers.append(
                {
                    "kind": "document_outside_project",
                    "path": relative,
                    "detail": f"{relative} resolves outside the linked project",
                }
            )
            continue
        if not absolute.is_file():
            blockers.append(
                {
                    "kind": "missing_document",
                    "path": relative,
                    "detail": f"{relative} is absent from the reviewed commit",
                }
            )
            continue
        content = absolute.read_bytes()
        documents.append(
            {
                "path": Path(relative).as_posix(),
                "kind": _document_kind(project, relative),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return documents, blockers


def _normalized_bom(project: ProjectRecord) -> dict:
    result = project_bom(
        project.root,
        project.pro_path,
        project.sheet_paths,
        name=project.name,
        boards=1,
        library_parts=[],
        price_lookup=None,
        bindings={},
        tool=project.eda or "kicad",
    )
    lines = [
        {
            "refs": list(line["refs"]),
            "qty": line["qty"],
            "value": line["value"],
            "mpn": line["mpn"],
            "manufacturer": line["manufacturer"],
            "footprint": line["footprint"],
            "package": line["package"],
            "description": line["description"],
            "datasheet": line["datasheet"],
            "basic": line["basic"],
            "identity_ready": bool(line["mpn"] or line["basic"]),
        }
        for line in result["lines"]
    ]
    return {
        "variant": "Default",
        "line_count": result["line_count"],
        "component_count": result["component_count"],
        "lines": lines,
        "digest": _digest(lines),
    }


def _semantic_audit(project: ProjectRecord) -> dict:
    root = Path(project.root)
    if project.eda == "altium":
        audit = audit_altium_project(root, project.pro_path, project.sheet_paths)
    else:
        audit = audit_project([root / path for path in project.sheet_paths])
    return {
        "components": audit["components"],
        "sheets": audit["sheets"],
        "counts": audit["counts"],
        "findings": audit["findings"],
        "digest": _digest(
            {
                "components": audit["components"],
                "sheets": audit["sheets"],
                "counts": audit["counts"],
                "findings": audit["findings"],
            }
        ),
    }


def _bom_findings(bom: dict) -> tuple[list[dict], list[dict]]:
    blockers: list[dict] = []
    warnings: list[dict] = []
    for line in bom["lines"]:
        refs = ", ".join(line["refs"])
        if not line["identity_ready"]:
            blockers.append(
                {
                    "kind": "missing_identity",
                    "path": refs,
                    "detail": f"{refs} has no exact MPN and is not a value-qualified basic part",
                }
            )
        if not line["footprint"]:
            blockers.append(
                {
                    "kind": "missing_footprint",
                    "path": refs,
                    "detail": f"{refs} has no assembly footprint",
                }
            )
        if line["mpn"] and not line["manufacturer"]:
            warnings.append(
                {
                    "kind": "missing_manufacturer",
                    "path": refs,
                    "detail": f"{refs} has an MPN but no manufacturer",
                }
            )
    return blockers, warnings


def build_review_evidence(
    manager: ReviewManager,
    project: ProjectRecord,
    candidate: ReviewCandidate,
) -> dict:
    """Build deterministic evidence from the displayed commit without checkout mutation."""

    captured: dict = {}

    def inspect(worktree: Path) -> None:
        snapshot = _project_in_worktree(project, worktree)
        documents, document_blockers = _document_evidence(snapshot)
        bom = _normalized_bom(snapshot)
        audit = _semantic_audit(snapshot)
        bom_blockers, warnings = _bom_findings(bom)
        audit_blockers = [
            {
                "kind": finding["kind"],
                "path": finding["ref"],
                "detail": finding["detail"],
            }
            for finding in audit["findings"]
            if finding["severity"] == "error"
        ]
        blockers = document_blockers + bom_blockers + audit_blockers
        body = {
            "schema_version": _SCHEMA_VERSION,
            "project_id": project.id,
            "project_name": project.name,
            "eda": project.eda,
            "branch": candidate.branch,
            "commit": candidate.commit,
            "base_branch": candidate.base_branch,
            "base_commit": candidate.base_commit,
            "documents": documents,
            "source_digest": _digest(documents),
            "bom": bom,
            "semantic_audit": audit,
            "blockers": blockers,
            "warnings": warnings,
            "reviewable": not blockers,
            "native_validation": {
                "status": "pending",
                "detail": "Native ERC/DRC or compile evidence is not attached yet.",
            },
            "visual_diff": {
                "status": "pending",
                "detail": "Native schematic and PCB render comparison is not attached yet.",
            },
        }
        captured.update(body)
        captured["digest"] = _digest(body)

    manager.inspect(candidate, inspect)
    if not captured:
        raise RuntimeError("review evidence inspection produced no result")
    return captured


def review_validation_key(project: ProjectRecord, candidate: ReviewCandidate) -> str:
    return ":".join(
        (
            project.id,
            candidate.branch,
            candidate.commit,
            candidate.base_branch,
            candidate.base_commit,
        )
    )


def run_review_native_validation(
    manager: ReviewManager,
    project: ProjectRecord,
    candidate: ReviewCandidate,
) -> dict:
    """Run the selected adapter's native checks against the exact commit."""

    captured: dict = {}

    def inspect(worktree: Path) -> None:
        snapshot = _project_in_worktree(project, worktree)
        before, blockers = _document_evidence(snapshot)
        if blockers:
            result = {
                "schema_version": 1,
                "adapter": snapshot.eda,
                "status": "blocked",
                "runtime": {"name": snapshot.eda, "version": ""},
                "checks": [],
                "summary": {"checked": 0, "errors": 0, "warnings": 0},
                "detail": "Registered source documents are missing from the reviewed commit.",
            }
        else:
            result = get_adapter(snapshot.eda).validate(snapshot)
        after, after_blockers = _document_evidence(snapshot)
        if before != after or after_blockers:
            result = {
                "schema_version": 1,
                "adapter": snapshot.eda,
                "status": "blocked",
                "runtime": result.get("runtime", {"name": snapshot.eda, "version": ""}),
                "checks": result.get("checks", []),
                "summary": result.get(
                    "summary",
                    {"checked": 0, "errors": 0, "warnings": 0},
                ),
                "detail": "Native validation changed a registered source document.",
            }
        result = {
            **result,
            "project_id": project.id,
            "branch": candidate.branch,
            "commit": candidate.commit,
            "base_branch": candidate.base_branch,
            "base_commit": candidate.base_commit,
            "source_digest": _digest(before),
        }
        result.pop("digest", None)
        result["digest"] = _digest(result)
        captured.update(result)

    manager.inspect(candidate, inspect)
    if not captured:
        raise RuntimeError("native review validation produced no result")
    return captured


def attach_native_validation(evidence: dict, validation: dict | None) -> dict:
    """Bind a cached native run to matching source evidence, or keep review blocked."""

    body = {key: value for key, value in evidence.items() if key != "digest"}
    blockers = list(body["blockers"])
    matching = (
        validation is not None
        and validation.get("project_id") == body["project_id"]
        and validation.get("branch") == body["branch"]
        and validation.get("commit") == body["commit"]
        and validation.get("base_branch") == body["base_branch"]
        and validation.get("base_commit") == body["base_commit"]
        and validation.get("source_digest") == body["source_digest"]
    )
    if not matching:
        body["native_validation"] = {
            "status": "pending",
            "detail": "Run native checks for this exact commit before approval.",
        }
        blockers.append(
            {
                "kind": "native_validation_pending",
                "path": body["commit"],
                "detail": "Native checks have not passed for this exact commit.",
            }
        )
    else:
        body["native_validation"] = validation
        if validation["status"] != "passed":
            blockers.append(
                {
                    "kind": f"native_validation_{validation['status']}",
                    "path": body["commit"],
                    "detail": validation["detail"],
                }
            )
    body["blockers"] = blockers
    body["reviewable"] = not blockers
    body["digest"] = _digest(body)
    return body
