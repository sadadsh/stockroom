"""High-level project operations (M7a): register / list / get / delete a KiCad
project and audit it. Mirrors LibraryOps as the engine object the AppContext holds
and the router calls. Registration/deletion delegate to ProjectStore (each a scoped
commit); audit resolves the record's sheet paths and runs the Qt-free health audit.

The audit is read-only. Editor writes (design rules, net classes, board setup) land
in M7e/M7f and will route through a Transaction bound to the project's own git repo.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad import project_settings
from stockroom.model.project import ProjectRecord
from stockroom.mutation.transaction import Transaction
from stockroom.projects import standards
from stockroom.projects.bom import project_bom
from stockroom.projects.checks import project_checks
from stockroom.projects.health import audit_project
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo


class ProjectOps:
    def __init__(self, store: ProjectStore, cli=None):
        self.store = store
        self.cli = cli

    def register(self, root) -> ProjectRecord:
        return self.store.register(root)

    def list(self) -> list[ProjectRecord]:
        return self.store.list()

    def get(self, project_id: str) -> ProjectRecord | None:
        return self.store.get(project_id)

    def delete(self, project_id: str) -> None:
        self.store.delete(project_id)

    def audit(self, project_id: str, footprint_dirs=None, model_dirs=None) -> dict:
        """Audit the registered project's schematic sheets. footprint_dirs/model_dirs
        (the active profile's footprints/models, passed by the router) enable the
        pin-vs-pad and missing-3D-model checks. Raises FileNotFoundError for an
        unknown id (mapped to 404 by the router)."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        root = Path(rec.root)
        sheet_paths = [root / s for s in rec.sheet_paths]
        au = audit_project(sheet_paths, footprint_dirs=footprint_dirs, model_dirs=model_dirs)
        au["project"] = rec.name
        return au

    def checks(self, project_id: str, progress=None) -> dict:
        """Run structured ERC (root schematic) + DRC (each board) via kicad-cli (M7b).
        Returns the combined {erc, drc, summary, ran_at} result the Overview and the
        Buildability verdict read. Raises FileNotFoundError for an unknown id. A missing
        kicad-cli surfaces an honest per-check cli-absent result rather than a fabricated
        pass; the router gates on cli availability first for an immediate honest 502."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cli = getattr(self.cli, "binary", self.cli)
        return project_checks(
            rec.root, rec.pro_path, rec.board_paths, rec.sheet_paths,
            cli, name=rec.name, progress=progress,
        )

    def bom(self, project_id: str, boards=1, price_lookup=None, progress=None) -> dict:
        """Build a grouped, optionally priced BOM for the registered project (M7c).
        Grouping is offline (no kicad-cli); `price_lookup` (injected by the router from
        Stockroom's enrich layer) prices each MPN line, and a miss leaves the line
        honestly unpriced. Raises FileNotFoundError for an unknown id."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return project_bom(
            rec.root, rec.pro_path, rec.sheet_paths,
            name=rec.name, boards=boards, price_lookup=price_lookup, progress=progress,
        )

    def revisions(self, project_id: str, max_count: int = 50) -> dict:
        """The registered project's git history (the commits touching its schematic sheets
        and project file), for the revision-diff pickers (M7d). Reads the project's OWN git
        repo (rec.git_root); a project not under git is an honest {under_git: False,
        revisions: []}, never a crash. Raises FileNotFoundError for an unknown id."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        if not rec.git_root:
            return {"project": rec.name, "under_git": False, "revisions": []}
        from stockroom.vcs.repo import GitRepo

        repo = GitRepo(Path(rec.git_root))
        root, git_root = Path(rec.root).resolve(), Path(rec.git_root).resolve()
        rels = []
        for rel in (list(rec.sheet_paths) + ([rec.pro_path] if rec.pro_path else [])):
            try:
                rels.append((root / rel).resolve().relative_to(git_root))
            except ValueError:
                continue
        commits = repo.log_paths(rels, max_count=max_count) if rels else []
        return {
            "project": rec.name,
            "under_git": True,
            "revisions": [
                {"sha": c.sha, "short": c.sha[:7], "subject": c.subject,
                 "author": c.author, "date": c.iso_date}
                for c in commits
            ],
        }

    def bom_diff(self, project_id: str, rev_a: str, rev_b: str = "",
                 current_rows=None) -> dict:
        """Diff the project's BOM between rev_a (reconstructed from git) and rev_b (a blank /
        'current' sentinel = the current build) (M7d). `current_rows` (the cached priced BOM
        lines, passed by the router) makes the cost/lead deltas meaningful. Raises
        FileNotFoundError for an unknown id, and ValueError when rev_a is missing or the
        project is not under git (both -> 400)."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        if not (rev_a or "").strip():
            raise ValueError("a revision to diff against (a=) is required")
        if not rec.git_root:
            raise ValueError("this project is not under git; a revision diff needs git history")
        from stockroom.projects.bom_diff import project_bom_diff

        result = project_bom_diff(
            rec.root, rec.sheet_paths, rec.git_root, rev_a, rev_b, current_rows=current_rows,
        )
        result["project"] = rec.name
        return result

    # --- M7e Editor writes (design rules + net classes) ----------------------

    def _require(self, project_id: str) -> ProjectRecord:
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return rec

    def _pro_path(self, rec: ProjectRecord) -> Path:
        if not rec.pro_path:
            raise ValueError("this project has no .kicad_pro to edit")
        return Path(rec.root) / rec.pro_path

    def design_settings(self, project_id: str, floor="none") -> dict:
        """The project's current net classes + design rules read straight from its
        .kicad_pro, plus a fab-floor validation of the classes (M7e). Raises
        FileNotFoundError for an unknown id; a project with no .kicad_pro is an honest
        empty shape, never a crash."""
        rec = self._require(project_id)
        data = {}
        if rec.pro_path:
            pro = Path(rec.root) / rec.pro_path
            if pro.exists():
                data = project_settings.parse(pro.read_text(encoding="utf-8"))
        net = data.get("net_settings") or {}
        ds = ((data.get("board") or {}).get("design_settings")) or {}
        classes = net.get("classes") or []
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_pro": bool(rec.pro_path),
            "net_classes": classes,
            "netclass_patterns": net.get("netclass_patterns") or [],
            "design_rules": ds.get("rules") or {},
            "track_widths": ds.get("track_widths") or [],
            "via_dimensions": ds.get("via_dimensions") or [],
            "diff_pair_dimensions": ds.get("diff_pair_dimensions") or [],
            "fab_floors": standards.FAB_FLOORS,
            "validation": standards.validate_classes(classes, floor),
        }

    def _write_pro(self, rec: ProjectRecord, patch: dict, message: str) -> str:
        """Apply a partial-merge patch to the project's .kicad_pro inside a Transaction
        bound to the project's OWN git repo: a single scoped commit, or every touched
        path restored and zero trace. Refuses a project not under git (the atomic commit
        + the commit-time asset gate need it, Decision 1)."""
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing"
            )
        pro = self._pro_path(rec)
        if not pro.exists():
            # pro_path is set but the file moved/was deleted after registration. An honest
            # 400 (re-register), never a raw FileNotFoundError that 404s and leaks the path.
            raise ValueError("this project's .kicad_pro is missing on disk; re-register the project")
        repo = GitRepo(Path(rec.git_root))
        with Transaction(repo) as txn:
            project_settings.apply_patch(pro, patch)
            txn.track(pro)
            return txn.commit(message)

    def set_net_classes(self, project_id: str, classes, deleted=None, floor="none") -> dict:
        """Reconcile the submitted net classes onto the project's on-disk classes
        (safe-merge, Default + unmanaged preserved) and write net_settings.classes back
        as a minimal diff, one scoped commit on the project's own git (M7e). Returns the
        reconciled classes + a fab-floor validation. Raises FileNotFoundError (unknown id)
        / ValueError (no .kicad_pro or not under git)."""
        rec = self._require(project_id)
        pro = self._pro_path(rec)
        existing = []
        if pro.exists():
            data = project_settings.parse(pro.read_text(encoding="utf-8"))
            existing = (data.get("net_settings") or {}).get("classes") or []
        reconciled = standards.reconcile_classes(existing, classes, deleted=deleted)
        sha = self._write_pro(
            rec, {"net_settings": {"classes": reconciled}}, f"Edit {rec.name}: net classes"
        )
        return {
            "project": rec.name,
            "committed": sha,
            "net_classes": reconciled,
            "validation": standards.validate_classes(reconciled, floor),
        }

    def set_design_rules(self, project_id: str, rules, track_widths=None,
                         via_dimensions=None, diff_pair_dimensions=None) -> dict:
        """Partial-merge the board design-rule constraints (and, when given, the
        track/via/diff-pair size lists) into board.design_settings, one scoped commit on
        the project's own git (M7e). The size lists are replaced wholesale (the editor
        sends the full list); rules are field-merged so an unspecified rule is preserved.
        Raises FileNotFoundError (unknown id) / ValueError (no .kicad_pro or not under git)."""
        rec = self._require(project_id)
        ds: dict = {"rules": dict(rules)}
        if track_widths is not None:
            ds["track_widths"] = list(track_widths)
        if via_dimensions is not None:
            ds["via_dimensions"] = list(via_dimensions)
        if diff_pair_dimensions is not None:
            ds["diff_pair_dimensions"] = list(diff_pair_dimensions)
        sha = self._write_pro(
            rec, {"board": {"design_settings": ds}}, f"Edit {rec.name}: design rules"
        )
        return {"project": rec.name, "committed": sha, "design_rules": dict(rules)}
