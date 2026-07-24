"""High-level project operations (M7a): register / list / get / delete a KiCad
project and audit it. Mirrors LibraryOps as the engine object the AppContext holds
and the router calls. Registration/deletion delegate to ProjectStore (each a scoped
commit); audit resolves the record's sheet paths and runs the Qt-free health audit.

The audit is read-only. Editor writes (design rules, net classes, board setup) land
in M7e/M7f and will route through a Transaction bound to the project's own git repo.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import os
from pathlib import Path

from stockroom.kicad import conform, project_settings, stackup
from stockroom.kicad.board import Board
from stockroom.model.project import ProjectRecord
from stockroom.mutation.transaction import Transaction
from stockroom.projects import conform_ops, fab_export as fab_export_mod, fab_ops, fields as fields_mod, fill, settings_ops, standards
from stockroom.sexp.document import SexpDocument
from stockroom.projects.bom import project_bom
from stockroom.projects.checks import project_checks
from stockroom.projects.health import audit_altium_project, audit_project
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo


def _resolve_parts(library_parts):
    """Resolve `library_parts` to a concrete list. It may be a THUNK (a zero-arg callable) so the
    router can defer reading the whole shared library from disk until AFTER an unknown-id 404 / a
    non-git 400 has been ruled out (never load a large library just to reject a request)."""
    parts = library_parts() if callable(library_parts) else library_parts
    return list(parts or ())


# What each EDA's registration can do in the Projects surface. The base set works for
# any project (the audit reads the schematics, the BOM builds offline, git history is
# git). The KiCad-only set needs KiCad files or kicad-cli: ERC/DRC, fab exports, the
# .kicad_pro editors (setup/net classes), Prepare (annotate/fill writes), and the
# board/schematic viewer. Altium binaries are read-only here, so those honestly stay off.
KICAD_ONLY_CAPABILITIES = ("checks", "fab", "setup", "netclasses", "prepare", "viewer")


def project_capabilities(rec: ProjectRecord) -> list[str]:
    caps = ["audit", "bom", "revisions", "restore", "file"]
    if rec.eda == "kicad":
        caps += list(KICAD_ONLY_CAPABILITIES)
    return caps


class ProjectOps:
    def __init__(self, store: ProjectStore, cli=None):
        self.store = store
        self.cli = cli

    def register(self, root, eda: str | None = None) -> ProjectRecord:
        return self.store.register(root, eda=eda)

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
        if rec.eda == "altium":
            au = audit_altium_project(root, rec.pro_path, rec.sheet_paths)
        else:
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
        rec = self.require_kicad(project_id)
        cli = getattr(self.cli, "binary", self.cli)
        return project_checks(
            rec.root, rec.pro_path, rec.board_paths, rec.sheet_paths,
            cli, name=rec.name, progress=progress,
        )

    def bom(self, project_id: str, boards=1, tax_rate=0.0, library_parts=None,
            price_lookup=None, progress=None) -> dict:
        """Build a grouped, optionally priced BOM for the registered project, COMBINING the KiCad
        schematic with the Stockroom library (M7c). `library_parts` (the active profile's
        PartRecords, injected by the router) fills each component's blank identity from its matching
        library part and prices it from the library's stored prices first; `price_lookup` (the
        enrich layer) prices whatever the library cannot. Grouping is offline (no kicad-cli); a miss
        leaves the line honestly unpriced. Raises FileNotFoundError for an unknown id."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return project_bom(
            rec.root, rec.pro_path, rec.sheet_paths,
            name=rec.name, boards=boards, tax_rate=tax_rate,
            library_parts=_resolve_parts(library_parts),
            price_lookup=price_lookup, progress=progress,
        )

    def fab_preview(self, project_id: str) -> dict:
        """The honest state the Fab panel gates on (M7i): whether the project has a board to
        fabricate and whether kicad-cli is available, plus the board file names for the
        picker. Read-only, no shell-out. Raises FileNotFoundError for an unknown id."""
        rec = self.require_kicad(project_id)
        cli = getattr(self.cli, "binary", self.cli)
        boards = [Path(b).name for b in rec.board_paths]
        return {
            "project": rec.name,
            "cli_available": bool(cli),
            "has_board": bool(boards),
            "boards": boards,
        }

    def fab_export(self, project_id: str, *, board: str | None = None,
                   drill_format: str = "excellon", drill_map: bool = True,
                   include_pos: bool = True, pos_format: str = "csv",
                   protel_ext: bool = True) -> dict:
        """Plot the fab set (gerbers + drill + placement) for the project's board via kicad-cli
        and return the zipped bundle {data, filename, content_type, files} the download
        endpoint streams (M7i). Read-only. Raises FileNotFoundError (unknown id), ValueError
        (no board / an unknown board name) and KiCadCliError (missing cli / failed plot).
        `board` selects one board file by name when the project has more than one; the first
        board is the default."""
        rec = self.require_kicad(project_id)
        if not rec.board_paths:
            raise ValueError("this project has no .kicad_pcb to fabricate")
        if board:
            chosen = next((b for b in rec.board_paths if Path(b).name == board), None)
            if chosen is None:
                raise ValueError(f"no such board in this project: {board}")
        else:
            chosen = rec.board_paths[0]
        cli = getattr(self.cli, "binary", self.cli)
        return fab_export_mod.build_fab_bundle(
            Path(rec.root) / chosen, cli,
            drill_format=drill_format, drill_map=drill_map,
            include_pos=include_pos, pos_format=pos_format, protel_ext=protel_ext,
        )

    def project_file(self, project_id: str, rel: str) -> bytes:
        """Return the raw bytes of one of the project's REGISTERED KiCad files (a board, a sheet,
        or the .kicad_pro), for the in-app kicanvas viewer (M7 #11). Read-only. Only a path the
        project actually registered is served: an ALLOWLIST, so there is no traversal and no
        arbitrary-file read, and the resolved path must still land inside the project root
        (defense in depth). Raises FileNotFoundError for an unknown id, an unregistered path, an
        escape, or a file missing on disk."""
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        allowed = set(rec.board_paths) | set(rec.sheet_paths)
        if rec.pro_path:
            allowed.add(rec.pro_path)
        if rel not in allowed:
            raise FileNotFoundError(f"not a registered project file: {rel}")
        root = Path(rec.root).resolve()
        resolved = (root / rel).resolve()
        if os.path.commonpath([str(root), str(resolved)]) != str(root):
            raise FileNotFoundError(f"path escapes the project: {rel}")
        if not resolved.is_file():
            raise FileNotFoundError(f"file not found: {rel}")
        return resolved.read_bytes()

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

    def buildability(self, project_id: str, checks=None, bom=None) -> dict:
        """Fuse the readiness signals into ONE ready-to-build verdict (M7g). READ-only: no
        Transaction, no commit, no cache eviction. `checks` / `bom` are the CACHED results the
        router injects (ctx.checks_cache.get(id) / ctx.bom_cache.get(id)); a cold cache is an
        honest 'not run yet' HARD blocker, NEVER a fabricated pass (a false READY is worse than
        a false NOT-READY). Completeness is computed LIVE (no library needed): its identity residual
        matches the Prepare section, though the unannotated count is the full on-disk set (a superset
        of what Prepare auto-numbers, since multi-unit / repeated-hierarchy refs are deferred to
        KiCad, so its blocker names KiCad too). Separation of concerns: completeness owns the
        physical board (annotation + footprint), the BOM owns orderability (priced + stock +
        lifecycle). Returns {project, ready, signals, blockers, warnings}; `ready` is True only
        when there are ZERO hard blockers. Raises FileNotFoundError for an unknown id."""
        rec = self._require(project_id)
        blockers: list[dict] = []
        warnings: list[dict] = []

        # -- completeness (live read; no library) --
        kicad = rec.eda == "kicad"
        sheets = self._sheet_abs(rec)
        has_sch = bool(sheets)
        comps: list[dict] = []
        if kicad:
            for p in sheets:
                with open(p, encoding="utf-8", newline="") as fh:
                    comps.extend(fill.read_components(SexpDocument.parse(fh.read())))
        else:
            # Altium sheets read through the schdoc reader into the SAME component
            # shape, so readiness computes identically for both EDAs.
            from stockroom.projects.health import altium_project_components

            comps = altium_project_components(Path(rec.root), rec.sheet_paths)
        cr = fill.project_readiness(comps)
        comp_state = "pass"
        if not has_sch:
            comp_state = "fail"
            blockers.append({"kind": "no_schematic",
                             "detail": "This project has no schematic to build from.",
                             "next_step": "Register a project that has a "
                                          + (".kicad_sch." if kicad else ".SchDoc.")})
        else:
            if cr["unannotated"]:
                comp_state = "fail"
                # Prepare auto-numbers single-unit refs but DEFERS multi-unit / repeated-hierarchy
                # ones to KiCad (fill.annotate_document), so the count is a superset of what
                # Prepare can fix; the remedy must name KiCad too, never a Prepare-only dead-end.
                # An Altium schematic annotates in Altium (Prepare is a KiCad-only writer).
                blockers.append({"kind": "unannotated",
                                 "detail": f"{cr['unannotated']} reference(s) are not annotated.",
                                 "next_step": "Prepare the project (Prepare section), or annotate the schematic in KiCad."
                                 if kicad else "Annotate the schematic in Altium."})
            if cr["missing_footprint"]:
                comp_state = "fail"
                blockers.append({"kind": "missing_footprint",
                                 "detail": f"{cr['missing_footprint']} component(s) have no footprint.",
                                 "next_step": "Assign footprints (Prepare, or in KiCad)."
                                 if kicad else "Assign footprints in Altium."})
            incomplete = cr["total"] - cr["complete"]
            if incomplete:
                warnings.append({"kind": "identity_incomplete",
                                 "detail": f"{incomplete} component(s) have incomplete library identity.",
                                 "next_step": "Prepare the project (Prepare section)."
                                 if kicad else "Complete the parts in Altium or the library."})
                # A warning-only completeness must read amber "warn", agreeing with the Prepare
                # section, not green "pass" (mirrors the BOM signal's soft-issue downgrade).
                if comp_state == "pass":
                    comp_state = "warn"
        completeness = {"state": comp_state, "has_sch": has_sch, "total": cr["total"],
                        "complete": cr["complete"], "unannotated": cr["unannotated"],
                        "missing_footprint": cr["missing_footprint"],
                        "incomplete_refs": cr["incomplete_refs"], "missing_counts": cr["missing_counts"]}

        # -- ERC/DRC (cached; cold cache = not run = HARD blocker, never a pass) --
        # An Altium project runs its rule checks inside Altium, not here: the signal
        # says so honestly and never blocks (a not_applicable is not a cold cache).
        if not kicad:
            checks_signal = {"state": "not_applicable", "ran_at": None, "errors": 0,
                             "warnings": 0, "checked": 0, "ok": True}
        elif not checks or checks.get("ran_at") is None:
            checks_signal = {"state": "not_run", "ran_at": None, "errors": 0,
                             "warnings": 0, "checked": 0, "ok": False}
            blockers.append({"kind": "checks_not_run",
                             "detail": "ERC and DRC have not been run.",
                             "next_step": "Run the checks (Checks section)."})
        else:
            summ = checks.get("summary") or {}
            errors, warns = summ.get("errors", 0), summ.get("warnings", 0)
            checked, ok = summ.get("checked", 0), bool(summ.get("ok"))
            checks_signal = {"state": "pass", "ran_at": checks.get("ran_at"), "errors": errors,
                             "warnings": warns, "checked": checked, "ok": ok}
            if errors > 0 or not ok:
                checks_signal["state"] = "fail"
                detail = (f"{errors} ERC/DRC error(s)." if errors > 0
                          else "The last ERC/DRC run did not complete cleanly.")
                blockers.append({"kind": "checks_failed", "detail": detail,
                                 "next_step": "Fix the errors and re-run (Checks section)."})
            elif warns > 0:
                # Amber "warn", agreeing with the Checks section's warning badge, not green "pass".
                checks_signal["state"] = "warn"
                warnings.append({"kind": "checks_warnings",
                                 "detail": f"{warns} ERC/DRC warning(s).",
                                 "next_step": "Review the warnings (Checks section)."})

        # -- BOM (cached; cold cache = not built = HARD blocker, never a fabricated cost) --
        if not bom or bom.get("ran_at") is None:
            bom_signal = {"state": "not_built", "ran_at": None, "priced": False,
                          "line_count": 0, "unpriced_lines": 0, "risks": None}
            blockers.append({"kind": "bom_not_built",
                             "detail": "The BOM has not been built.",
                             "next_step": "Build the BOM (BOM section)."})
        else:
            from stockroom.projects.procurement import project_procurement

            proc = project_procurement(bom)
            risks = proc["risks"]
            unpriced = (bom.get("summary") or {}).get("unpriced_lines", 0)
            bom_signal = {"state": "pass", "ran_at": bom.get("ran_at"), "priced": bool(proc["priced"]),
                          "line_count": len(proc["lines"]), "unpriced_lines": unpriced, "risks": risks}
            soft = False
            if unpriced:
                soft = True
                warnings.append({"kind": "bom_unpriced",
                                 "detail": f"{unpriced} BOM line(s) are unpriced.",
                                 "next_step": "Price the BOM (BOM section)."})
            short = risks.get("no_stock", 0) + risks.get("insufficient_stock", 0)
            if short:
                soft = True
                warnings.append({"kind": "bom_stock",
                                 "detail": f"{short} BOM line(s) are out of or short on stock.",
                                 "next_step": "Review sourcing (Procurement)."})
            if risks.get("not_active"):
                soft = True
                warnings.append({"kind": "bom_lifecycle",
                                 "detail": f"{risks['not_active']} BOM line(s) are NRND or EOL.",
                                 "next_step": "Review sourcing (Procurement)."})
            if soft:
                bom_signal["state"] = "warn"

        # -- git working tree (scoped to THIS project's files) --
        if not rec.git_root:
            git_signal = {"state": "not_git", "under_git": False, "dirty": False}
            warnings.append({"kind": "not_git",
                             "detail": "This project is not under version control.",
                             "next_step": "Initialize a git repo for it."})
        else:
            root = Path(rec.root)
            proj_files = [root / rel for rel in
                          (list(rec.sheet_paths) + list(rec.board_paths)
                           + ([rec.pro_path] if rec.pro_path else []))
                          if (root / rel).exists()]
            clean = GitRepo(Path(rec.git_root)).is_clean(proj_files) if proj_files else True
            git_signal = {"state": "clean" if clean else "dirty", "under_git": True, "dirty": not clean}
            if not clean:
                warnings.append({"kind": "dirty_tree",
                                 "detail": "There are uncommitted changes; this build will not match a commit.",
                                 "next_step": "Commit or discard your changes."})

        return {
            "project": rec.name,
            "ready": len(blockers) == 0,
            "signals": {"completeness": completeness, "checks": checks_signal,
                        "bom": bom_signal, "git": git_signal},
            "blockers": blockers,
            "warnings": warnings,
        }

    # --- M7e Editor writes (design rules + net classes) ----------------------

    def _require(self, project_id: str) -> ProjectRecord:
        rec = self.store.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return rec

    def require_kicad(self, project_id: str) -> ProjectRecord:
        """The KiCad-only operations (ERC/DRC, fab exports, the .kicad_pro editors,
        Prepare writes, the viewer) refuse an Altium registration with an honest 400
        (ValueError) instead of failing deep in a file parser."""
        rec = self._require(project_id)
        if rec.eda != "kicad":
            raise ValueError(
                f"{rec.name} is an Altium project; this operation applies only to "
                "KiCad projects"
            )
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
        rec = self.require_kicad(project_id)
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
        rec = self.require_kicad(project_id)
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
        rec = self.require_kicad(project_id)
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

    @staticmethod
    def _validate_netclass_patterns(patterns, valid_netclasses, *, check_membership) -> list:
        """Validate + normalize the submitted netclass-pattern rows to exactly
        {netclass, pattern} (the two keys KiCad 10 writes, verified against the real NETDECK
        .kicad_pro). Each row needs a non-empty pattern and a non-empty netclass; when
        check_membership, the netclass must exist among the project's classes (an unknown one
        is a ValueError -> 400). List order is preserved (KiCad applies patterns in order)."""
        if not isinstance(patterns, list):
            raise ValueError("netclass_patterns must be a list")
        rows = []
        for i, row in enumerate(patterns):
            if not isinstance(row, dict):
                raise ValueError(f"netclass pattern {i} must be an object")
            pattern = row.get("pattern")
            netclass = row.get("netclass")
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(f"netclass pattern {i} needs a non-empty pattern")
            if not isinstance(netclass, str) or not netclass.strip():
                raise ValueError(f"netclass pattern {i} needs a net class")
            if check_membership and netclass not in valid_netclasses:
                raise ValueError(
                    f"netclass pattern {i} references unknown net class {netclass!r}"
                )
            rows.append({"netclass": netclass, "pattern": pattern})
        return rows

    def set_netclass_patterns(self, project_id: str, patterns) -> dict:
        """Replace net_settings.netclass_patterns in the project's .kicad_pro (net-name glob
        -> net class rows) as a minimal diff, one scoped commit on the project's own git
        (roadmap #4). The list is REPLACED wholesale (the editor sends the full list; a plain
        merge replaces a list value, so an empty list clears every pattern and no replace_keys
        is needed). Each row is validated BEFORE any git touch: a non-empty pattern and a
        netclass that exists among the project's classes (an unknown one is a ValueError ->
        400). Raises FileNotFoundError (unknown id) / ValueError (no .kicad_pro, not under git,
        or a bad row)."""
        rec = self.require_kicad(project_id)
        pro = self._pro_path(rec)
        # Read the project's own classes to validate the netclass references. When the file is
        # gone from disk we cannot know the valid set, so membership is deferred and _write_pro
        # raises the honest 'missing on disk' (re-register) rather than a misleading 'unknown
        # net class'. A truly present-but-classless file yields an empty valid set (correct: no
        # class to reference).
        valid: set = set()
        exists = pro.exists()
        if exists:
            data = project_settings.parse(pro.read_text(encoding="utf-8"))
            net = data.get("net_settings") or {}
            valid = {
                c.get("name")
                for c in (net.get("classes") or [])
                if isinstance(c, dict) and isinstance(c.get("name"), str)
            }
        rows = self._validate_netclass_patterns(patterns, valid, check_membership=exists)
        sha = self._write_pro(
            rec,
            {"net_settings": {"netclass_patterns": rows}},
            f"Edit {rec.name}: netclass patterns",
        )
        return {"project": rec.name, "committed": sha, "netclass_patterns": rows}

    # --- M7f Editor writes (board setup + thickness) -------------------------

    # -- M7h KiField bulk-field editor ----------------------------------------

    def _placed_components(self, rec: ProjectRecord) -> list[dict]:
        """Every placed component across every existing sheet, each tagged with its relative
        sheet path, for the field grid. Read-only."""
        root = Path(rec.root).resolve()
        comps: list[dict] = []
        for path in self._sheet_abs(rec):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel = path.name
            for c in fill.read_components(SexpDocument.load(path)):
                c["_sheet"] = rel
                comps.append(c)
        return comps

    def fields(self, project_id: str) -> dict:
        """The KiField bulk-field grid: every placed component across every sheet as a
        rows-by-fields table, Reference read-only (M7h). Read-only. Raises FileNotFoundError for
        an unknown id; a project with no schematic is an honest empty grid, never a crash."""
        rec = self.require_kicad(project_id)
        grid = fields_mod.build_field_grid(self._placed_components(rec))
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_sch": bool(self._sheet_abs(rec)),
            **grid,
        }

    def set_fields(self, project_id: str, edits) -> dict:
        """Apply a batch of {ref, field, value} field-cell edits across every sheet as ONE atomic
        commit on the project's own git (M7h). The edits are validated against the CURRENT on-disk
        grid (a read-only Reference field, an unknown or non-editable ref, or a blank field name is
        a ValueError -> 400), each change is written byte-preservingly via fill_document, and only
        the sheets that actually change are tracked + committed (minimal diff); an edit that changes
        nothing is an honest no-commit no-op. Raises FileNotFoundError (unknown id); ValueError for a
        project not under git or with uncommitted schematic changes (the same dirty-tree guard as
        Prepare, so a user's in-progress sheet edits are never swept into the field commit)."""
        rec = self.require_kicad(project_id)
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing fields"
            )
        repo = GitRepo(Path(rec.git_root))
        sheets = self._sheet_abs(rec)
        if sheets and not repo.is_clean(sheets):
            raise ValueError(
                "this project has uncommitted changes to a schematic; commit or discard them before editing fields"
            )
        grid = fields_mod.build_field_grid(self._placed_components(rec))
        changes_by_ref = fields_mod.field_changes_by_ref(grid["rows"], edits)
        empty = {"project": rec.name, "committed": None, "components": 0, "fields": 0, "files": []}
        if not changes_by_ref:
            return empty
        root = Path(rec.root).resolve()
        changed: list[tuple[Path, SexpDocument]] = []
        files: list[dict] = []
        for path in sheets:
            doc = SexpDocument.load(path)
            n = fill.fill_document(doc, changes_by_ref)
            if n:
                try:
                    rel = path.resolve().relative_to(root).as_posix()
                except ValueError:
                    rel = path.name
                changed.append((path, doc))
                files.append({"path": rel, "components": n})
        if not changed:  # every submitted value already matched on disk (byte no-op)
            return empty
        total_fields = sum(len(v) for v in changes_by_ref.values())
        message = (f"Edit {rec.name} fields: {total_fields} value(s) on "
                   f"{len(changes_by_ref)} component(s)")
        with Transaction(repo) as txn:
            for path, _doc in changed:
                txn.track(path)
            for path, doc in changed:
                doc.save(path)
            sha = txn.commit(message)
        return {"project": rec.name, "committed": sha, "components": len(changes_by_ref),
                "fields": total_fields, "files": files}

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
        rec = self.require_kicad(project_id)
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
        rec = self.require_kicad(project_id)

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
        rec = self.require_kicad(project_id)
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
        rec = self.require_kicad(project_id)
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
        rec = self.require_kicad(project_id)
        conform_ops.validate_targets(pcb_targets, sch_targets)
        if not conform_ops.any_targets(pcb_targets, sch_targets):
            raise ValueError("select at least one object type to conform")
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing"
            )
        # Refuse a dirty tree: conform saves + commits whole files, so uncommitted user edits to any
        # touched board/sheet would be swept into the conform commit and then destroyed by a Restore
        # that reverts it. Guard before any read (mirrors prepare_apply).
        repo = GitRepo(Path(rec.git_root))
        root = Path(rec.root)
        touched = self._sheet_abs(rec) + [root / b for b in rec.board_paths if (root / b).exists()]
        if touched and not repo.is_clean(touched):
            raise ValueError(
                "this project has uncommitted changes; commit or discard them before conforming"
            )
        staged = self._stage_conform(rec, pcb_targets, sch_targets)
        files_result = [{"path": s["path"], "counts": s["counts"], "changed": s["changed"]}
                        for s in staged]
        total = sum(s["changed"] for s in staged)
        changed = [s for s in staged if s["_doc"] is not None]
        if not changed:
            return {"project": rec.name, "committed": None, "files": files_result, "total": 0}

        message = f"Conform {rec.name}: " + self._conform_summary(pcb_targets, sch_targets)
        with Transaction(repo) as txn:
            # Track every file to be written BEFORE any write, so a save that raises mid-write (a
            # later file failing after an earlier one already landed) rolls ALL of them back.
            for s in changed:
                txn.track(s["_abs"])
            for s in changed:
                s["_doc"].save(s["_abs"])
            sha = txn.commit(message)
        return {"project": rec.name, "committed": sha, "files": files_result, "total": total}

    # --- M7f-C Editor: stackup / fab-preset ----------------------------------

    def stackup_read(self, project_id: str) -> dict:
        """The project's current physical layer stack read from its primary .kicad_pcb (structured
        layers + copper_finish + dielectric_constraints), its copper layer names (physical order),
        overall thickness, and the fab-preset catalog, for the Stackup editor's render (M7f-C).
        Read-only. Raises FileNotFoundError for an unknown id; a project with no board is an honest
        empty shape, never a crash."""
        rec = self.require_kicad(project_id)
        board_path = self._primary_board(rec)
        current = None
        copper_names: list[str] = []
        thickness = None
        if board_path is not None:
            board = Board.load(board_path)
            current = board.stackup()
            copper_names = board.copper_layer_names()
            thickness = board.thickness()
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_board": board_path is not None,
            "stackup": current,
            "copper_layers": copper_names,
            "thickness": thickness,
            "presets": fab_ops.preset_catalog(),
        }

    def _stage_stackup(self, board: Board, original: str, *, preset_key, copper_finish,
                       dielectric_constraints, layer_edits):
        """Validate a stackup request and apply it to `board` IN MEMORY (no save). A request is
        EITHER a fab-preset apply (whole-block generate + board thickness) OR a set of per-field
        edits, never both. Returns (preset_or_None, new_thickness). Raises ValueError (-> 400) for a
        malformed / empty / mode-conflicting request, an unknown or layer-mismatched preset, or a
        field edit on a board with no stackup. `original` is the board's pre-edit serialized text
        (for whitespace-format detection)."""
        is_preset = bool(preset_key)
        is_fields = (
            copper_finish is not None or dielectric_constraints is not None or bool(layer_edits)
        )
        if is_preset and is_fields:
            raise ValueError("apply a fab preset or edit stackup fields in one action, not both")
        if not is_preset and not is_fields:
            raise ValueError("choose a fab preset to apply, or edit at least one stackup field")
        current = board.stackup()
        if is_fields:
            if current is None:
                raise ValueError(
                    "this board has no stackup to edit; apply a fab preset first to create one"
                )
            fab_ops.validate_field_edits(copper_finish, dielectric_constraints, layer_edits)
            # A per-field edit must name a layer that exists and a field that layer actually carries
            # (update-if-present never manufactures an atom, so a wrong layer/field would silently
            # no-op with committed:null); reject it as an honest 400 instead.
            by_name = {lyr["name"]: lyr for lyr in current["layers"]}
            for lname, fields in (layer_edits or {}).items():
                lyr = by_name.get(lname)
                if lyr is None:
                    raise ValueError(f"no such stackup layer: {lname!r}")
                for field, val in fields.items():
                    if val is not None and field not in lyr:
                        raise ValueError(f"the {lname} layer has no {field} to set")
            board.set_stackup_fields(
                copper_finish=copper_finish, dielectric_constraints=dielectric_constraints,
                layers=layer_edits)
            return None, board.thickness()
        if is_preset:
            if not board.has_setup():
                raise ValueError(
                    "this board has no (setup ...) block to hold a stackup; open it in KiCad first"
                )
            copper_names = board.copper_layer_names()
            if not copper_names:
                raise ValueError("this board declares no copper layers; a stackup cannot be applied")
            preset = fab_ops.validate_preset_apply(preset_key, len(copper_names))
            unit, nl = stackup.detect_format(original)
            layers = stackup.build_preset_layers(
                copper_names, preset["physical"], mask_color=preset["soldermask_color"])
            block = stackup.render_stackup_block(
                layers, copper_finish=preset["finish"], dielectric_constraints=False,
                unit=unit, nl=nl)
            board.apply_stackup_block(block)
            # Set (general (thickness)) to the generated stack's own sum, not the preset's nominal
            # label: KiCad keeps the board thickness equal to the sum of its stackup layers, so
            # writing the sum makes the board internally consistent instead of a value KiCad would
            # recompute away. (The nominal label is still shown in the preset picker.)
            new_thickness = stackup.stackup_thickness_sum(layers)
            board.set_thickness(new_thickness)
            return preset, new_thickness
        # unreachable: is_preset/is_fields are exhaustive (both-false is rejected above)
        raise ValueError("choose a fab preset to apply, or edit at least one stackup field")

    def stackup_preview(self, project_id: str, *, preset_key=None, copper_finish=None,
                        dielectric_constraints=None, layer_edits=None) -> dict:
        """A dry-run of a stackup change: the RESULTING structured stackup + new board thickness +
        whether it differs from disk + (for a preset) the verify_note, computed WITHOUT writing or
        touching git (M7f-C). Validates the request (bad/empty/conflicting mode, unknown or
        mismatched preset, field edit on a stackless board -> ValueError -> 400). Raises
        FileNotFoundError for an unknown id."""
        rec = self.require_kicad(project_id)
        board_path = self._primary_board(rec)
        if board_path is None:
            raise ValueError("this project has no .kicad_pcb to preview")
        board = Board.load(board_path)
        original = board.serialize()
        preset, new_thickness = self._stage_stackup(
            board, original, preset_key=preset_key, copper_finish=copper_finish,
            dielectric_constraints=dielectric_constraints, layer_edits=layer_edits)
        return {
            "project": rec.name,
            "stackup": board.stackup(),
            "thickness": new_thickness,
            "changed": board.serialize() != original,
            "verify_note": preset["verify_note"] if preset else None,
        }

    def stackup_apply(self, project_id: str, *, preset_key=None, copper_finish=None,
                      dielectric_constraints=None, layer_edits=None) -> dict:
        """Apply a stackup change to the project's primary .kicad_pcb as ONE atomic commit on its own
        git (M7f-C): a fab-preset apply (whole-block generate + board thickness) OR per-field edits,
        in a single Transaction (track-before-write, one scoped commit, or the board restored and
        zero trace). Validates before any git touch. A request that produces no byte change is an
        honest no-commit no-op ({committed: None, changed: False}). Raises FileNotFoundError (unknown
        id); ValueError for a bad request, no board, or a project not under git. Returns the re-read
        stackup + the commit sha (or None)."""
        rec = self.require_kicad(project_id)
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before editing"
            )
        board_path = self._primary_board(rec)
        if board_path is None:
            raise ValueError("this project has no .kicad_pcb to edit")
        # Refuse a board with uncommitted changes: this apply saves + commits the whole board, so a
        # dirty board's in-progress user edits would be swept into the stackup commit and then
        # destroyed by a Restore that reverts it. Guard before any read (mirrors prepare_apply).
        repo = GitRepo(Path(rec.git_root))
        if not repo.is_clean([board_path]):
            raise ValueError(
                "this project has uncommitted changes to the board; commit or discard them before editing the stackup"
            )
        board = Board.load(board_path)
        original = board.serialize()
        preset, _new_thickness = self._stage_stackup(
            board, original, preset_key=preset_key, copper_finish=copper_finish,
            dielectric_constraints=dielectric_constraints, layer_edits=layer_edits)
        if board.serialize() == original:
            return {**self.stackup_read(project_id), "committed": None, "changed": False}

        label = preset["label"] if preset else "fields"
        message = f"Set {rec.name} stackup: {label}"
        with Transaction(repo) as txn:
            # Track BEFORE the write so a save that raises mid-write still rolls the board back to
            # its committed bytes.
            txn.track(board_path)
            board.save(board_path)
            sha = txn.commit(message)
        return {**self.stackup_read(project_id), "committed": sha, "changed": True}

    # --- M7f-D Editor: Library Fill + Prepare/Complete-All + reversible Restore ---

    def _sheet_abs(self, rec: ProjectRecord) -> list[Path]:
        """The project's schematic sheets that exist on disk, as absolute paths in sorted (registered)
        order. A sheet that moved after registration is skipped (it cannot be prepared)."""
        root = Path(rec.root)
        return [root / s for s in rec.sheet_paths if (root / s).exists()]

    def _stage_prepare(self, rec: ProjectRecord, index: list[dict]):
        """Compute a Prepare across every sheet WITHOUT writing: seed the project-wide used-reference
        set, then per sheet (in registered order so annotation is deterministic and project-unique)
        annotate every unannotated reference and auto-fill every BLANK identity field of a confidently
        matched component (never an overwrite, so a user-set value is never clobbered). Returns
        (staged, plan, completion_current, completion_after):

          - staged: per-sheet {path, _abs, annotated, filled, _doc} (a live doc only when it changed);
          - plan:   the reviewable fill plan (proposed changes of ALL kinds), keyed on the CURRENT
                    on-disk designators so the preview + the manual-fill picker name refs that exist;
          - completion_current: the completion passport residual as the project is ON DISK RIGHT NOW
                    (disk designators, so a manual fill always names a real component);
          - completion_after:   the projected residual AFTER the auto-fill (annotated designators = what
                    those refs will be on disk once Prepare is applied).

        Every edit lands on a byte-preserving SexpDocument in memory; the caller saves the changed docs
        in one atomic Transaction (apply) or discards them (preview)."""
        root = Path(rec.root)
        sheets = self._sheet_abs(rec)
        texts: list[str] = []
        for p in sheets:
            with open(p, encoding="utf-8", newline="") as fh:
                texts.append(fh.read())
        used = fill.used_references(texts)  # seed project-wide before any sheet is numbered
        staged: list[dict] = []
        pre_comps: list[dict] = []      # current on-disk designators (for the plan + current residual)
        final_comps: list[dict] = []    # post-annotate + post-fill (for the projected residual)
        for path, text in zip(sheets, texts):
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = path.name
            doc = SexpDocument.parse(text)
            # Read the CURRENT on-disk components (disk designators) BEFORE annotation, so the plan and
            # the manual-fill picker name refs that actually exist on disk (a manual fill matches disk,
            # not the projected annotated ref). Matching is designator-independent (by lib_id / MPN).
            for c in fill.read_components(doc):
                c["_sheet"] = rel
                pre_comps.append(c)
            annotated = fill.annotate_document(doc, used)
            # Read AFTER annotation so the auto-fill keys off the FINAL designators annotation just
            # assigned (the doc it will save), not the R? placeholders.
            changes_by_ref: dict[str, dict[str, str]] = {}
            for c in fill.read_components(doc):
                m = fill.match_component(c, index)
                if m["part"] is None:
                    continue
                fills = {ch["prop"]: ch["new"]
                         for ch in fill.proposed_changes(m["part"], c["props"]) if ch["kind"] == "fill"}
                if fills:
                    changes_by_ref[c["ref"]] = fills
            # fill_document returns the count of INSTANCES touched (the byte-level change gate);
            # the reported "fill_fields" is the number of property fields filled (its own count).
            filled_comps = fill.fill_document(doc, changes_by_ref)
            filled_fields = sum(len(v) for v in changes_by_ref.values())
            for c in fill.read_components(doc):
                final_comps.append(c)
            changed = (annotated + filled_comps) > 0
            staged.append({"path": rel, "_abs": path, "annotated": annotated,
                           "filled": filled_fields, "components": filled_comps,
                           "_doc": doc if changed else None})
        plan = fill.build_fill_plan(pre_comps, index,
                                    {c["ref"]: c["_sheet"] for c in pre_comps})
        return (staged, plan,
                fill.project_completion(pre_comps), fill.project_completion(final_comps))

    def prepare_read(self, project_id: str, library_parts=()) -> dict:
        """A dry-run of Prepare / Complete-All: the annotate count, the fill plan (per-ref proposed
        changes), and the completion residual before and after the auto-fill, computed WITHOUT writing
        or touching git (M7f-D). `library_parts` (the active profile's PartRecords, passed by the
        router) is the match library. Read-only. Raises FileNotFoundError for an unknown id; a project
        with no sheets is an honest empty shape, never a crash."""
        rec = self.require_kicad(project_id)  # 404 before the (possibly large) library is loaded
        index = fill.library_match_records(_resolve_parts(library_parts))
        staged, plan, current, after = self._stage_prepare(rec, index)
        return {
            "project": rec.name,
            "under_git": bool(rec.git_root),
            "has_sch": bool(self._sheet_abs(rec)),
            "annotate": sum(s["annotated"] for s in staged),
            "fill_fields": sum(s["filled"] for s in staged),
            "files": [{"path": s["path"], "annotated": s["annotated"], "filled": s["filled"]}
                      for s in staged],
            "plan": plan,
            # The CURRENT on-disk residual: its incomplete_refs are real disk designators, so the
            # manual-fill picker never offers a ref that a fill would fail to find. `completion_after`
            # is the projection once Complete-All is applied (the annotated designators).
            "completion": current,
            "completion_after": after,
        }

    def prepare_apply(self, project_id: str, library_parts=(), progress=None) -> dict:
        """Prepare / Complete-All: annotate every unannotated reference and auto-fill every blank
        identity field of a confidently matched component across EVERY sheet, as ONE atomic commit on
        the project's own git (M7f-D). Only the sheets that actually change are tracked + written
        (minimal diff), in a single Transaction (track-before-write, one scoped commit, or every touched
        path restored and zero trace). A Prepare that changes nothing is an honest no-commit no-op
        ({committed: None}). `progress` (an SSE callback) reports the phase. Raises FileNotFoundError
        (unknown id); ValueError for a project not under git. Returns the counts + the residual passport
        + the commit sha (or None)."""
        rec = self.require_kicad(project_id)
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before preparing"
            )

        def _p(pct, msg):
            if progress:
                progress({"pct": pct, "message": msg})

        repo = GitRepo(Path(rec.git_root))
        sheets = self._sheet_abs(rec)
        # Refuse a sheet with uncommitted changes: Prepare saves + commits the whole sheet, so a dirty
        # sheet's in-progress user edits would be swept into the Prepare commit and then destroyed by a
        # Restore that reverts it. Guard before any read so the tree is committed-clean first.
        if sheets and not repo.is_clean(sheets):
            raise ValueError(
                "this project has uncommitted changes to a schematic; commit or discard them before preparing"
            )
        index = fill.library_match_records(_resolve_parts(library_parts))
        _p(15, "Reading schematics")
        staged, plan, _current, after = self._stage_prepare(rec, index)
        _p(70, "Matching library and filling")
        annotated = sum(s["annotated"] for s in staged)
        filled = sum(s["filled"] for s in staged)
        files = [{"path": s["path"], "annotated": s["annotated"], "filled": s["filled"]}
                 for s in staged]
        changed = [s for s in staged if s["_doc"] is not None]
        result = {"project": rec.name, "annotated": annotated, "fill_fields": filled,
                  "files": files, "completion": after}
        if not changed:
            _p(100, "Nothing to prepare")
            return {**result, "committed": None}
        message = f"Prepare {rec.name}: annotate {annotated}, fill {filled}"
        _p(85, "Committing")
        with Transaction(repo) as txn:
            for s in changed:
                txn.track(s["_abs"])
            for s in changed:
                s["_doc"].save(s["_abs"])
            sha = txn.commit(message)
        _p(100, "Prepared")
        return {**result, "committed": sha}

    def manual_fill(self, project_id: str, ref: str, part_id: str, library_parts=()) -> dict:
        """Link a specific placed component `ref` to the library part `part_id`, filling ALL its
        identity fields (overwrite allowed, since this is an explicit user choice, unlike the
        conservative auto pass) and repointing its `(lib_id ...)`, as ONE atomic commit on the
        project's own git (M7f-D). The residual filler for a component the auto pass could not match.
        A link that changes nothing is an honest no-commit no-op. Raises FileNotFoundError (unknown id);
        ValueError for a project not under git, an unknown library part, or no such component `ref`."""
        rec = self.require_kicad(project_id)
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before filling"
            )
        repo = GitRepo(Path(rec.git_root))
        sheets = self._sheet_abs(rec)
        # Same dirty-tree guard as Prepare: a fill saves + commits the whole sheet, so a dirty sheet's
        # in-progress user edits must not be swept into the Fill commit (a later Restore would revert
        # them). Require the sheets committed-clean first.
        if sheets and not repo.is_clean(sheets):
            raise ValueError(
                "this project has uncommitted changes to a schematic; commit or discard them before filling"
            )
        index = fill.library_match_records(_resolve_parts(library_parts))
        part = next((p for p in index if p["id"] == part_id), None)
        if part is None:
            raise ValueError(f"no such library part: {part_id}")
        lib_id = fill.lib_id_for(part)
        found = False
        changed: list[tuple[Path, SexpDocument]] = []
        for path in sheets:
            doc = SexpDocument.load(path)
            comps = {c["ref"]: c for c in fill.read_components(doc)}
            comp = comps.get(ref)
            if comp is None:
                continue
            found = True
            changes = {ch["prop"]: ch["new"] for ch in fill.proposed_changes(part, comp["props"])}
            n = fill.fill_document(doc, {ref: changes} if changes else {},
                                   lib_id_by_ref={ref: lib_id} if lib_id else None)
            if n:
                changed.append((path, doc))
        if not found:
            raise ValueError(f"no component {ref!r} in this project")
        if not changed:
            return {"project": rec.name, "committed": None, "ref": ref, "part_id": part_id}
        message = f"Fill {rec.name}: {ref} from library"
        with Transaction(repo) as txn:
            for path, _doc in changed:
                txn.track(path)
            for path, doc in changed:
                doc.save(path)
            sha = txn.commit(message)
        return {"project": rec.name, "committed": sha, "ref": ref, "part_id": part_id}

    def restore(self, project_id: str) -> dict:
        """Undo the project's last Prepare / Fill by git-reverting that commit as a new commit
        (non-destructive; history and any later commits stand) (M7f-D). Since Prepare/Fill is ONE
        atomic commit on the project's own git, Restore leans on git rather than a hand-rolled backup.
        Refuses when the project has uncommitted changes in its KiCad files (a revert on a dirty tree is
        unsafe) or when no Prepare/Fill commit exists. Raises FileNotFoundError (unknown id); ValueError
        for a project not under git, a dirty tree, or nothing to restore; GitError (-> 503) when a later
        commit conflicts with the revert."""
        rec = self._require(project_id)
        if not rec.git_root:
            raise ValueError("this project is not under git; there is nothing to restore")
        repo = GitRepo(Path(rec.git_root))
        root, git_root = Path(rec.root).resolve(), Path(rec.git_root).resolve()
        rels: list[Path] = []
        abs_paths: list[Path] = []
        for rel in list(rec.sheet_paths) + list(rec.board_paths) + (
                [rec.pro_path] if rec.pro_path else []):
            ap = (root / rel)
            if not ap.exists():
                continue
            abs_paths.append(ap)
            try:
                rels.append(ap.resolve().relative_to(git_root))
            except ValueError:
                continue
        if not repo.is_clean(abs_paths):
            raise ValueError(
                "this project has uncommitted changes; commit or discard them before restoring"
            )
        # Match Stockroom's OWN prepare/fill commits specifically ("Prepare <name>:" / "Fill <name>:",
        # exactly what prepare_apply/manual_fill write) rather than a bare "Prepare "/"Fill " prefix,
        # so a user's own commit (e.g. "Prepare the board for fab") is never mistaken for one to revert.
        prefixes = (f"Prepare {rec.name}:", f"Fill {rec.name}:")
        commits = repo.log_paths(rels, max_count=100) if rels else []
        # A git revert leaves a `Revert "<subject>"` commit; a prepare/fill already undone that way must
        # be skipped so a REPEATED Restore steps back to the PRIOR prepare/fill instead of re-reverting
        # the same commit (which git would refuse as an empty/conflicting revert). This makes Restore
        # walk the prepare/fill history one step per call.
        already_reverted = {
            c.subject[len('Revert "'):-1]
            for c in commits
            if c.subject.startswith('Revert "') and c.subject.endswith('"')
        }
        target = next(
            (c for c in commits
             if c.subject.startswith(prefixes) and c.subject not in already_reverted),
            None,
        )
        if target is None:
            raise ValueError("nothing to restore: this project has no Prepare or Fill commit to undo")
        new_head = repo.revert(target.sha)  # GitError on a conflict -> 503
        return {"project": rec.name, "restored": target.sha, "short": target.sha[:7],
                "subject": target.subject, "committed": new_head}
