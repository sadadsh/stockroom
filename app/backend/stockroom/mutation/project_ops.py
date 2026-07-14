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

from stockroom.kicad import conform, project_settings
from stockroom.kicad.board import Board
from stockroom.model.project import ProjectRecord
from stockroom.mutation.transaction import Transaction
from stockroom.projects import conform_ops, settings_ops, standards
from stockroom.sexp.document import SexpDocument
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
            # Track BEFORE the write so a save that raises mid-write is still rolled back to
            # its committed bytes (track only records the path; the write may partly land).
            txn.track(pro)
            project_settings.apply_patch(pro, patch)
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

    # --- M7f Editor writes (board setup + thickness) -------------------------

    def _primary_board(self, rec: ProjectRecord) -> Path | None:
        """The project's primary .kicad_pcb (board_paths[0], the alphabetically-first
        board KiCad emits), resolved to an absolute path, or None when the project has no
        board on disk. Board setup + thickness are per-.kicad_pcb; a multi-board project
        edits this primary board (a per-board selector is a future add, logged)."""
        for rel in rec.board_paths:
            path = Path(rec.root) / rel
            if path.exists():
                return path
        return None

    def _read_pro(self, rec: ProjectRecord) -> tuple[dict, bool]:
        """Parse the project's .kicad_pro (M7f-A2), returning (data, has_pro). A project with
        no .kicad_pro, or one whose file moved after registration, is ({}, False) so the read
        stays honest and never crashes."""
        if not rec.pro_path:
            return {}, False
        pro = Path(rec.root) / rec.pro_path
        if not pro.exists():
            return {}, False
        return project_settings.parse(pro.read_text(encoding="utf-8")), True

    def board_settings(self, project_id: str) -> dict:
        """The project's current board setup (mask/paste clearances, tenting, origins) and
        overall thickness read from its primary .kicad_pcb (M7f-A), PLUS its .kicad_pro
        settings (ERC/DRC rule severities, the ERC pin-conflict matrix, project text variables)
        and the editor catalogs (M7f-A2). Read-only. Raises FileNotFoundError for an unknown id;
        a project with no board and/or no .kicad_pro is an honest empty shape, never a crash.

        erc_pin_map is the file's matrix or None when absent: it is NEVER fabricated as an
        all-OK matrix, since that would silently disable every pin-conflict check KiCad's real
        default enforces (the editor only offers the matrix when the file already carries one)."""
        rec = self._require(project_id)
        board_path = self._primary_board(rec)
        setup: dict = {}
        thickness = None
        if board_path is not None:
            board = Board.load(board_path)
            setup = settings_ops.effective_board_setup(board.setup(include_aliases=False))
            thickness = board.thickness()

        pro_data, has_pro = self._read_pro(rec)
        erc = pro_data.get("erc") or {}
        ds = ((pro_data.get("board") or {}).get("design_settings")) or {}
        erc_sev = erc.get("rule_severities")
        drc_sev = ds.get("rule_severities")
        pin_map = erc.get("pin_map")
        text_vars = pro_data.get("text_variables")
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_board": board_path is not None,
            "has_pro": has_pro,
            "board_setup": setup,
            "thickness": thickness,
            "fields": settings_ops.BOARD_SETUP_FIELDS,
            # .kicad_pro surfaces (M7f-A2). Values are coerced defensively so a malformed entry
            # cannot break the editor; an absent map reads as {} / None (never a fabricated one).
            "erc_severities": {str(k): v for k, v in erc_sev.items() if isinstance(v, str)}
            if isinstance(erc_sev, dict) else {},
            "drc_severities": {str(k): v for k, v in drc_sev.items() if isinstance(v, str)}
            if isinstance(drc_sev, dict) else {},
            "erc_pin_map": [[int(x) for x in row] for row in pin_map]
            if isinstance(pin_map, list) and pin_map and all(isinstance(r, list) for r in pin_map)
            else None,
            "text_variables": {str(k): str(v) for k, v in text_vars.items()}
            if isinstance(text_vars, dict) else {},
            "severity_levels": list(settings_ops.SEVERITY_LEVELS),
            "erc_pin_types": list(settings_ops.ERC_PIN_TYPES),
        }

    def set_settings(self, project_id: str, *, board_setup=None, thickness=None,
                     erc_severities=None, drc_severities=None, erc_pin_map=None,
                     text_variables=None) -> dict:
        """Write the project's board setup / overall thickness (to its .kicad_pcb) and/or its
        .kicad_pro settings (ERC/DRC rule severities, the ERC pin-conflict matrix, project text
        variables), one scoped commit on the project's OWN git (M7f-A + A2). Whichever concerns
        are given land in a SINGLE atomic Transaction that touches only the files it edits (one
        commit, or every touched path restored and zero trace).

        Everything is validated BEFORE any git touch (unsupported board key, non-positive
        thickness, an unknown severity rule id, a malformed pin map, a blank text-var name are
        each a ValueError -> 400). Severities merge per-rule (a sibling rule is preserved); the
        pin map replaces its list wholesale; text_variables replaces wholesale so a var absent
        from the submitted map is DELETED. Raises FileNotFoundError (unknown id); ValueError for
        a project not under git, a board edit with no .kicad_pcb, a .kicad_pro edit with no
        .kicad_pro, or nothing to write. Returns the re-read settings plus the commit sha.

        `erc_severities`/`drc_severities`/`erc_pin_map` treat an empty/None value as 'not
        submitted'; `text_variables` uses None for 'not submitted' so an empty {} is still a
        legitimate 'clear all vars'."""
        rec = self._require(project_id)

        has_board_edit = bool(board_setup) or thickness is not None
        has_erc_sev = bool(erc_severities)
        has_drc_sev = bool(drc_severities)
        has_pin_map = erc_pin_map is not None
        has_text_vars = text_variables is not None
        has_pro_edit = has_erc_sev or has_drc_sev or has_pin_map or has_text_vars
        if not has_board_edit and not has_pro_edit:
            raise ValueError("no settings to write")

        # Validate every submitted concern before touching git (a clean 400, not a partial commit).
        if board_setup:
            settings_ops.validate_board_setup(board_setup)
        if thickness is not None:
            settings_ops.validate_thickness(thickness)

        desired_text_vars = None
        pro_path = None
        if has_pro_edit:
            pro_path = self._pro_path(rec)  # ValueError if the project has no .kicad_pro
            if not pro_path.exists():
                raise ValueError("this project's .kicad_pro is missing on disk; re-register the project")
            pro_data = project_settings.parse(pro_path.read_text(encoding="utf-8"))
            erc = pro_data.get("erc") or {}
            ds = ((pro_data.get("board") or {}).get("design_settings")) or {}
            cur_erc = erc.get("rule_severities") if isinstance(erc.get("rule_severities"), dict) else {}
            cur_drc = ds.get("rule_severities") if isinstance(ds.get("rule_severities"), dict) else {}
            if has_erc_sev:
                settings_ops.validate_severity_map(
                    erc_severities, allowed=set(cur_erc) | set(settings_ops.ERC_RULE_IDS))
            if has_drc_sev:
                settings_ops.validate_severity_map(
                    drc_severities, allowed=set(cur_drc) | set(settings_ops.DRC_RULE_IDS))
            if has_pin_map:
                settings_ops.validate_pin_map(erc_pin_map)
            if has_text_vars:
                desired_text_vars = settings_ops.reconcile_text_variables(text_variables)

        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing"
            )
        board_path = self._primary_board(rec) if has_board_edit else None
        if has_board_edit and board_path is None:
            raise ValueError("this project has no .kicad_pcb to edit")

        # Build the .kicad_pro partial-merge patch. Severities merge per-rule; pin_map replaces
        # as a list; text_variables goes through replace_keys so a deletion (a key absent from
        # the desired map) actually lands (a plain merge could only add/update).
        patch: dict = {}
        replace_keys: tuple = ()
        if has_erc_sev:
            patch.setdefault("erc", {})["rule_severities"] = dict(erc_severities)
        if has_pin_map:
            patch.setdefault("erc", {})["pin_map"] = [[int(x) for x in row] for row in erc_pin_map]
        if has_drc_sev:
            patch.setdefault("board", {}).setdefault("design_settings", {})["rule_severities"] = dict(
                drc_severities
            )
        if has_text_vars:
            patch["text_variables"] = desired_text_vars
            replace_keys = ("text_variables",)

        concerns = []
        if board_setup:
            concerns.append("board setup")
        if thickness is not None:
            concerns.append("thickness")
        if has_erc_sev or has_drc_sev:
            concerns.append("rule severities")
        if has_pin_map:
            concerns.append("ERC pin map")
        if has_text_vars:
            concerns.append("text variables")
        message = f"Edit {rec.name}: " + ", ".join(concerns)

        repo = GitRepo(Path(rec.git_root))
        with Transaction(repo) as txn:
            # Track BOTH edited files BEFORE any write: a save that raises mid-write (disk full,
            # a lock, revoked permission) must still roll BOTH back to their committed bytes.
            if has_board_edit:
                txn.track(board_path)
            if has_pro_edit:
                txn.track(pro_path)
            if has_board_edit:
                board = Board.load(board_path)
                if board_setup:
                    board.set_setup(board_setup)
                if thickness is not None:
                    board.set_thickness(thickness)
                board.save(board_path)
            if has_pro_edit:
                project_settings.apply_patch(pro_path, patch, replace_keys=replace_keys)
            sha = txn.commit(message)
        return {**self.board_settings(project_id), "committed": sha}

    # --- M7f-B Editor: object conform (font/thickness normalize) --------------

    def _kicad_files(self, rec: ProjectRecord) -> tuple[list[Path], list[Path]]:
        """(boards, sheets) as absolute paths that exist on disk. A record path that moved after
        registration is skipped (it cannot be conformed) rather than crashing the whole conform."""
        root = Path(rec.root)
        boards = [root / b for b in rec.board_paths if (root / b).exists()]
        sheets = [root / s for s in rec.sheet_paths if (root / s).exists()]
        return boards, sheets

    def conform_catalog(self, project_id: str) -> dict:
        """The object-conform category catalog (Title Case labels + suggested sizes) plus the
        project's honest state (has a board / has a sheet / under git), for the editor's initial
        render (M7f-B). Read-only. Raises FileNotFoundError for an unknown id."""
        rec = self._require(project_id)
        boards, sheets = self._kicad_files(rec)
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_pcb": bool(boards),
            "has_sch": bool(sheets),
            "pcb_categories": conform_ops.PCB_CONFORM_CATEGORIES,
            "sch_categories": conform_ops.SCH_CONFORM_CATEGORIES,
            "suggested": conform_ops.SUGGESTED,
        }

    def _stage_conform(self, rec: ProjectRecord, pcb_targets, sch_targets) -> list[dict]:
        """Compute, per project file, the conform change counts WITHOUT writing (dry run): load
        each board + sheet into a byte-preserving SexpDocument, apply the conform in memory, and
        record {path (posix, display-safe), counts, changed, _abs, _doc}. Only a file with at least
        one changed atom carries a live _doc to save; an unchanged file is left alone (minimal
        diff). A change count > 0 is exactly equivalent to a real byte difference, since the writer
        edits an atom only when its value actually differs."""
        root = Path(rec.root)
        boards, sheets = self._kicad_files(rec)
        staged: list[dict] = []
        for path in boards + sheets:
            doc = SexpDocument.load(path)
            counts = conform.conform_document(doc, pcb_targets or {}, sch_targets or {})
            total = sum(counts.values())
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = path.name
            staged.append({"path": rel, "counts": counts, "changed": total,
                           "_abs": path, "_doc": doc if total else None})
        return staged

    @staticmethod
    def _conform_summary(pcb_targets, sch_targets) -> str:
        """A human commit-message tail naming the conformed types, e.g. 'silk text, net labels'."""
        labels = {c["key"]: c["label"].lower()
                  for c in conform_ops.PCB_CONFORM_CATEGORIES + conform_ops.SCH_CONFORM_CATEGORIES}
        parts = [labels[k] for k in conform.PCB_CATEGORIES if k in (pcb_targets or {})]
        parts += [labels[k] for k in conform.SCH_CATEGORIES if k in (sch_targets or {})]
        return ", ".join(parts)

    def conform_preview(self, project_id: str, pcb_targets, sch_targets) -> dict:
        """A dry-run of an object conform: per-file change counts for the given targets, computed
        WITHOUT writing or touching git (M7f-B). Validates the targets (unknown category / bad
        size or thickness -> ValueError -> 400) and refuses an empty selection. Raises
        FileNotFoundError for an unknown id."""
        rec = self._require(project_id)
        conform_ops.validate_targets(pcb_targets, sch_targets)
        if not conform_ops.any_targets(pcb_targets, sch_targets):
            raise ValueError("select at least one object type to conform")
        staged = self._stage_conform(rec, pcb_targets, sch_targets)
        return {
            "project": rec.name,
            "files": [{"path": s["path"], "counts": s["counts"], "changed": s["changed"]}
                      for s in staged],
            "total": sum(s["changed"] for s in staged),
        }

    def conform_apply(self, project_id: str, pcb_targets, sch_targets) -> dict:
        """Apply an object conform across EVERY board + sheet of the project as ONE atomic commit
        on the project's own git (M7f-B): only the files that actually change are tracked + written
        (minimal diff), in a single Transaction (track-before-write, one scoped commit, or every
        touched path restored and zero trace). Validates before any git touch. A selection that
        produces no change is an honest no-commit no-op ({committed: None, total: 0}), never a
        fabricated empty commit. Raises FileNotFoundError (unknown id); ValueError for an empty
        selection, a bad target, or a project not under git. Returns the per-file counts + the
        commit sha (or None)."""
        rec = self._require(project_id)
        conform_ops.validate_targets(pcb_targets, sch_targets)
        if not conform_ops.any_targets(pcb_targets, sch_targets):
            raise ValueError("select at least one object type to conform")
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing"
            )
        staged = self._stage_conform(rec, pcb_targets, sch_targets)
        files_result = [{"path": s["path"], "counts": s["counts"], "changed": s["changed"]}
                        for s in staged]
        total = sum(s["changed"] for s in staged)
        changed = [s for s in staged if s["_doc"] is not None]
        if not changed:
            return {"project": rec.name, "committed": None, "files": files_result, "total": 0}

        message = f"Conform {rec.name}: " + self._conform_summary(pcb_targets, sch_targets)
        repo = GitRepo(Path(rec.git_root))
        with Transaction(repo) as txn:
            # Track every file to be written BEFORE any write, so a save that raises mid-write (a
            # later file failing after an earlier one already landed) rolls ALL of them back.
            for s in changed:
                txn.track(s["_abs"])
            for s in changed:
                s["_doc"].save(s["_abs"])
            sha = txn.commit(message)
        return {"project": rec.name, "committed": sha, "files": files_result, "total": total}
