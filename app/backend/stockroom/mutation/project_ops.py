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
