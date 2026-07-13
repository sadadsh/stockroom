"""The Stockroom project record: one JSON file per registered KiCad project.

A KiCad PCB project is a separate thing that *consumes* the library (M7). Stockroom
does not own the project files; it registers them by path. The ProjectRecord is a
registration plus an audit cache stored in the library repo at
``libraries/<profile>/projects/<id>.json`` while the actual ``.kicad_pro`` /
``.kicad_pcb`` / ``.kicad_sch`` stay at their external ``root`` location; project-file
writes route through a Transaction bound to the project's OWN git repo.

Like PartRecord, one file per project is git-merge friendly and JSON is emitted
canonically (sorted keys, 2-space indent, trailing newline) so a one-field edit
(e.g. a refreshed audit digest) produces a minimal, stable diff.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.model.category import slugify


@dataclass
class ProjectRecord:
    id: str
    name: str
    # Absolute path to the project directory, stored as_posix so a record written on
    # one OS reads the same on another (display never uses str(Path)).
    root: str
    # The project's KiCad files, relative to `root` (so the record is location-stable).
    pro_path: str = ""
    board_paths: list[str] = field(default_factory=list)
    sheet_paths: list[str] = field(default_factory=list)
    # The git repo root the project lives under (absolute, as_posix), or None when the
    # project is not under version control. Project writes require this (commit-time
    # asset gate); a None git_root makes an edit an honest refuse, never a silent write.
    git_root: str | None = None
    # A cached digest of the last audit (counts + a hash of the inputs) so Overview,
    # Health, and the Buildability verdict read one consistent result; invalidated on
    # any write. None until the project has been audited once.
    audit_digest: dict | None = None
    registered_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "root": self.root,
            "pro_path": self.pro_path,
            "board_paths": list(self.board_paths),
            "sheet_paths": list(self.sheet_paths),
            "git_root": self.git_root,
            "audit_digest": dict(self.audit_digest) if self.audit_digest is not None else None,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectRecord":
        digest = d.get("audit_digest")
        return cls(
            id=d["id"],
            name=d["name"],
            root=d["root"],
            pro_path=d.get("pro_path", ""),
            board_paths=list(d.get("board_paths", [])),
            sheet_paths=list(d.get("sheet_paths", [])),
            git_root=d.get("git_root"),
            audit_digest=dict(digest) if digest is not None else None,
            registered_at=d.get("registered_at", ""),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "ProjectRecord":
        return cls.from_dict(json.loads(text))


def new_project_id(projects_dir: Path, base: str) -> str:
    """A stable, unique, never-reused id derived from `base` (the project name).

    Slug of `base`; if `projects/<slug>.json` exists, suffix -2, -3, ... A base
    that slugifies to empty falls back to 'project'. Mirrors model.part.new_part_id."""
    projects_dir = Path(projects_dir)
    slug = slugify(base) or "project"
    candidate = slug
    n = 1
    while (projects_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{slug}-{n}"
    return candidate
