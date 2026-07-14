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

from stockroom.model.project import ProjectRecord
from stockroom.projects.bom import project_bom
from stockroom.projects.checks import project_checks
from stockroom.projects.health import audit_project
from stockroom.store.project_store import ProjectStore


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
