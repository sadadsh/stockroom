"""The projects surface (M7a-5): register / list / get / delete / audit external
KiCad projects through the ProjectOps engine (spec section 8). A registered project
is external to Stockroom: it is referenced by path, never owned; only its
registration record lives in the library repo.

List reads the derived project index (warm, rebuilt on register/delete); detail loads
the full canonical record. The audit resolves the ACTIVE profile's footprints/models
dirs at request time (projects are profile-independent, but the pin/pad and 3D-model
checks read against whichever library is active) and returns a shareable markdown report.

Routers never set a status code or invent an error shape: they raise the engine's own
exceptions and api/errors.py maps them (ValueError -> 400, FileNotFoundError -> 404).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from stockroom.api.schemas import ProjectSummary, RegisterProjectBody
from stockroom.kicad.errors import KiCadCliError


def projects_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/projects", dependencies=[Depends(require_token)])

    @r.get("")
    def list_projects(request: Request) -> list:
        ctx = request.app.state.ctx
        return [ProjectSummary.from_row(row).model_dump() for row in ctx.project_index.all()]

    @r.post("")
    def register_project(request: Request, body: RegisterProjectBody) -> dict:
        # A bad/nonexistent dir, a dir with no KiCad files, or an already-registered
        # root each raises ValueError in the store -> 400 via the error layer.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.register(body.root)
        ctx.rebuild_project_index()
        return rec.to_dict()

    @r.get("/{project_id}")
    def project_detail(request: Request, project_id: str) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return rec.to_dict()

    @r.delete("/{project_id}", status_code=204)
    def delete_project(request: Request, project_id: str) -> Response:
        # An unknown id raises FileNotFoundError -> 404; a known one unregisters (the
        # external files are never touched) and the index is rebuilt.
        ctx = request.app.state.ctx
        ctx.project_ops.delete(project_id)
        ctx.checks_cache.pop(project_id, None)  # the cached ERC/DRC is now stale
        ctx.rebuild_project_index()
        return Response(status_code=204)

    @r.get("/{project_id}/audit")
    def project_audit(request: Request, project_id: str) -> dict:
        # Read-only health pass over the registered sheets. The footprint/model dirs come
        # from the ACTIVE profile at request time (enabling the pin/pad + 3D-model checks);
        # an unknown id raises FileNotFoundError -> 404. The markdown is the shareable report.
        from stockroom.projects.health import audit_report_markdown

        ctx = request.app.state.ctx
        au = ctx.project_ops.audit(
            project_id,
            footprint_dirs=[ctx.profile.library.footprints_dir],
            model_dirs=[ctx.profile.library.models_dir],
        )
        au["markdown"] = audit_report_markdown(au)
        return au

    @r.post("/{project_id}/checks")
    def run_checks(request: Request, project_id: str) -> dict:
        # Structured ERC (root schematic) + DRC (each board) via kicad-cli, run off the
        # request path as a job with SSE progress (each check can take seconds). The
        # unknown-id 404 is resolved before the cli gate; a missing kicad-cli is an
        # honest 502 (never a fabricated clean pass, Decision 8). The result is cached
        # in AppContext so Overview and Buildability read one consistent verdict.
        ctx = request.app.state.ctx
        if ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        if not ctx.cli.available:
            raise KiCadCliError(
                "kicad-cli not found; install KiCad 10 (or set its path in Settings) to run ERC and DRC"
            )

        def work(progress):
            result = ctx.project_ops.checks(project_id, progress=progress)
            ctx.checks_cache[project_id] = result
            return result

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/{project_id}/checks")
    def get_checks(request: Request, project_id: str) -> dict:
        # The cached last run, or an honest not-run shape (never a fabricated pass) so
        # the frontend can render a stable "not checked yet" state. Unknown id -> 404.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.checks_cache.get(project_id)
        if cached is None:
            return {"project": rec.name, "ran_at": None, "erc": None, "drc": [], "summary": None}
        return cached

    return r
