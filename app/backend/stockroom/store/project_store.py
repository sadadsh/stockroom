"""Registered PCB projects (KiCad or Altium): one JSON ProjectRecord per project.

A PCB project is external to Stockroom (M7): Stockroom registers it by path, never
owns its files. The ProjectRecord (a registration plus a cached audit digest) is
written under a `projects/` directory in the library repo and committed like every
other record; the actual `.kicad_pro`/`.kicad_pcb`/`.kicad_sch` (KiCad) or
`.PrjPcb`/`.PcbDoc`/`.SchDoc` (Altium) stay at their external `root`. Mirrors
store/profile.py: each mutation is one scoped git commit (git is the undo system),
and delete removes only the registration, never the external files.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from stockroom.model.project import ProjectRecord, new_project_id
from stockroom.vcs.repo import GitRepo

# Project ids come from new_project_id (a slug of the project name), so they are always
# [a-z0-9_-]. get()/delete() take an id straight from a URL path param, so anything that
# is not a bare slug (a separator, a dot, traversal) can never reach the filesystem.
_ID_RE = re.compile(r"[a-z0-9_-]+")


def _safe_id(project_id: str) -> bool:
    return bool(_ID_RE.fullmatch(project_id))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_git_root(start: Path) -> str | None:
    """The nearest ancestor of `start` (inclusive) that holds `.git`, as_posix, or None.

    `.git` is tested with exists() so a submodule/worktree `.git` FILE counts, not just a
    directory. This is what makes the commit-time asset gate meaningful: a project write
    commits into the project's own repo, and a project with no git_root refuses the write."""
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate.as_posix()
    return None


def _discover(root: Path) -> tuple[str, list[str], list[str], str]:
    """Scan the project dir (top level) for its KiCad files, returning paths relative to
    `root` (a top-level glob makes the relative path just the file name) and a name
    defaulting to the .kicad_pro stem (else the first board/sheet stem, else the dir name)."""
    root = Path(root)
    pros = sorted(root.glob("*.kicad_pro"))
    boards = sorted(root.glob("*.kicad_pcb"))
    sheets = sorted(root.glob("*.kicad_sch"))
    pro = pros[0].name if pros else ""
    if pros:
        name = pros[0].stem
    elif boards:
        name = boards[0].stem
    elif sheets:
        name = sheets[0].stem
    else:
        name = root.name
    return pro, [p.name for p in boards], [p.name for p in sheets], name


# A .PrjPcb is INI-style text; each [DocumentN] section carries one DocumentPath. The
# paths are Windows-relative (backslashes), so they normalize to posix for the record.
_DOCUMENT_PATH = re.compile(r"^DocumentPath=(.+)$", re.MULTILINE)


def _prjpcb_documents(prjpcb: Path) -> list[str]:
    """Every DocumentPath the .PrjPcb lists, normalized to posix, order preserved. A
    missing/unreadable project file lists nothing (the glob fallback still finds docs)."""
    try:
        text = prjpcb.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    docs = []
    for m in _DOCUMENT_PATH.finditer(text):
        rel = m.group(1).strip().replace("\\", "/")
        if rel and rel not in docs:
            docs.append(rel)
    return docs


def _discover_altium(root: Path) -> tuple[str, list[str], list[str], str]:
    """Scan the project dir for its Altium files: documents come from the .PrjPcb's
    DocumentPath entries (recorded even when missing on disk: registration records what
    the project CLAIMS; a missing document is a health finding) plus any loose top-level
    .SchDoc/.PcbDoc the project file does not list. Name mirrors the KiCad rule: the
    .PrjPcb stem, else the first board/sheet stem, else the dir name."""
    root = Path(root)
    pros = sorted(root.glob("*.PrjPcb"))
    pro = pros[0].name if pros else ""
    listed = _prjpcb_documents(pros[0]) if pros else []
    sheets = [d for d in listed if d.lower().endswith(".schdoc")]
    boards = [d for d in listed if d.lower().endswith(".pcbdoc")]
    for p in sorted(root.glob("*.SchDoc")):
        if p.name not in sheets:
            sheets.append(p.name)
    for p in sorted(root.glob("*.PcbDoc")):
        if p.name not in boards:
            boards.append(p.name)
    if pros:
        name = pros[0].stem
    elif boards:
        name = Path(boards[0]).stem
    elif sheets:
        name = Path(sheets[0]).stem
    else:
        name = root.name
    return pro, boards, sheets, name


class ProjectStore:
    def __init__(self, projects_root: Path, repo: GitRepo):
        self.projects_root = Path(projects_root)
        self.repo = repo

    def _path(self, project_id: str) -> Path:
        return self.projects_root / f"{project_id}.json"

    def register(self, root: Path, eda: str | None = None) -> ProjectRecord:
        root = Path(root)
        if not root.is_dir():
            raise ValueError(f"not a directory: {root.as_posix()}")
        if eda not in (None, "kicad", "altium"):
            raise ValueError(f"unknown eda: {eda!r} (expected 'kicad' or 'altium')")
        kicad = _discover(root)
        altium = _discover_altium(root)
        has_kicad = any(kicad[:3])
        has_altium = any(altium[:3])
        if eda is None:
            # Auto-detect by which EDA's files exist; a dir holding BOTH is ambiguous
            # and needs an explicit choice rather than a silent guess.
            if has_kicad and has_altium:
                raise ValueError(
                    f"{root.as_posix()} holds both KiCad and Altium project files; "
                    "pass eda='kicad' or eda='altium' to choose"
                )
            eda = "altium" if has_altium else "kicad"
        if eda == "altium":
            if not has_altium:
                raise ValueError(f"no Altium project files found in {root.as_posix()}")
            pro, boards, sheets, name = altium
        else:
            if not has_kicad:
                raise ValueError(f"no KiCad project files found in {root.as_posix()}")
            pro, boards, sheets, name = kicad
        root_posix = root.as_posix()
        if any(rec.root == root_posix for rec in self.list()):
            raise ValueError(f"project already registered: {root_posix}")
        self.projects_root.mkdir(parents=True, exist_ok=True)
        project_id = new_project_id(self.projects_root, name)
        rec = ProjectRecord(
            id=project_id,
            name=name,
            root=root_posix,
            pro_path=pro,
            board_paths=boards,
            sheet_paths=sheets,
            eda=eda,
            git_root=_resolve_git_root(root),
            registered_at=_utc_now_iso(),
        )
        path = self._path(project_id)
        path.write_text(rec.dumps(), encoding="utf-8")
        self.repo.commit(f"Register project {name}", [path])
        return rec

    def list(self) -> list[ProjectRecord]:
        if not self.projects_root.exists():
            return []
        recs = [
            ProjectRecord.loads(p.read_text(encoding="utf-8"))
            for p in sorted(self.projects_root.glob("*.json"))
        ]
        return sorted(recs, key=lambda r: (r.name.lower(), r.id))

    def get(self, project_id: str) -> ProjectRecord | None:
        if not _safe_id(project_id):
            return None
        path = self._path(project_id)
        if not path.exists():
            return None
        return ProjectRecord.loads(path.read_text(encoding="utf-8"))

    def delete(self, project_id: str) -> None:
        rec = self.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        path = self._path(project_id)
        path.unlink()
        # the now-missing path is staged as a deletion by the scoped commit (git add -A
        # records removals), exactly as ProfileStore.delete does; the external files stay.
        self.repo.commit(f"Unregister project {rec.name}", [path])
