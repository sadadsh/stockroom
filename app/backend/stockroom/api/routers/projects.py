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

from stockroom.api.schemas import (
    ProjectSummary,
    RegisterProjectBody,
    SetDesignRulesBody,
    SetNetClassesBody,
    SetSettingsBody,
)
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
        ctx.bom_cache.pop(project_id, None)  # the cached BOM is now stale too
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
            # A DELETE may have landed (and evicted the cache) while this ran; do not
            # resurrect a cache entry for a now-gone id (project ids are reusable slugs).
            if ctx.project_ops.get(project_id) is not None:
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

    @r.post("/{project_id}/bom")
    def build_bom(request: Request, project_id: str, body: dict | None = None) -> dict:
        # Build a grouped, priced BOM off the request path as a job with SSE progress
        # (pricing each unique MPN through the enrich layer is network-bound). Grouping is
        # offline, so there is NO kicad-cli gate: the BOM works without KiCad installed;
        # pricing degrades honestly to unpriced lines when the enrich layer cannot reach a
        # distributor (Decision 8), never a fabricated price. Cached in AppContext so a
        # re-open renders instantly. Unknown id -> 404.
        ctx = request.app.state.ctx
        if ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        boards = (body or {}).get("boards", 1)

        def work(progress):
            price_lookup = _bom_price_lookup(ctx)
            result = ctx.project_ops.bom(
                project_id, boards=boards, price_lookup=price_lookup, progress=progress
            )
            # A DELETE may have landed (and evicted the cache) during this network-bound
            # build; do not resurrect a cache entry for a now-gone id (ids are reusable
            # name-slugs, so a re-registered same-named project would surface stale data).
            if ctx.project_ops.get(project_id) is not None:
                ctx.bom_cache[project_id] = result
            return result

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/{project_id}/bom")
    def get_bom(request: Request, project_id: str) -> dict:
        # The cached last build, or an honest not-built shape so the frontend renders a
        # stable "not built yet" state (summary None, never a fabricated cost). Unknown id -> 404.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.bom_cache.get(project_id)
        if cached is None:
            return {"project": rec.name, "ran_at": None, "boards": 1, "priced": False,
                    "line_count": 0, "component_count": 0, "lines": [],
                    "summary": None, "by_source": None, "cost_at_qty": None}
        return cached

    @r.get("/{project_id}/procurement")
    def get_procurement(request: Request, project_id: str) -> dict:
        # Per-line orderability + sourcing/stock risk + lead time, computed offline over
        # the CACHED BOM build (M7d). No rebuild: procurement is a pure read of the last
        # priced BOM, so before a build it is an honest not-built shape (never a fabricated
        # risk), and an unpriced build lists its lines with unknown (never-a-risk) stock.
        # Unknown id -> 404.
        from stockroom.projects.procurement import project_procurement

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.bom_cache.get(project_id) or {"ran_at": None, "boards": 1,
                                                   "priced": False, "lines": []}
        proc = project_procurement(cached)
        proc["project"] = rec.name
        return proc

    @r.get("/{project_id}/bom/export")
    def export_bom(request: Request, project_id: str, kind: str = "csv",
                   boards: int | None = None, spares_pct: float = 0.0,
                   pcb_multiple: int = 3, tax_rate: float = 0.0, shipping: float = 0.0,
                   labour_per_board: float = 0.0, assembly_surcharge_rate: float = 0.0):
        # Render the CACHED BOM into a downloadable export (M7d): kind is one of
        # csv/priced/cart/jlcpcb/xlsx/procurement. Read-only, offline. An unknown kind is a
        # ValueError -> 400; an unbuilt project is a 400 (nothing to export yet, never an
        # empty/fabricated file); an unknown id -> 404. The procurement knobs (spares,
        # pcb_multiple, tax, shipping, assembly) pass through to the procurement sheet.
        from stockroom.projects.bom_export import project_bom_export

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.bom_cache.get(project_id)
        if cached is None or cached.get("ran_at") is None:
            raise ValueError("build the BOM before exporting it")
        out = project_bom_export(
            cached, kind, boards=boards, spares_pct=spares_pct, pcb_multiple=pcb_multiple,
            tax_rate=tax_rate, shipping=shipping, labour_per_board=labour_per_board,
            assembly_surcharge_rate=assembly_surcharge_rate,
        )
        data = out["data"]
        body = data.encode("utf-8") if isinstance(data, str) else data
        return Response(
            content=body, media_type=out["content_type"],
            headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'},
        )

    @r.get("/{project_id}/revisions")
    def project_revisions(request: Request, project_id: str) -> dict:
        # The project's git history, for the revision-diff pickers (M7d). A project not under
        # git is an honest {under_git: False, revisions: []}; an unknown id -> 404.
        ctx = request.app.state.ctx
        return ctx.project_ops.revisions(project_id)

    @r.get("/{project_id}/bom/diff")
    def bom_diff(request: Request, project_id: str, a: str = "", b: str = "") -> dict:
        # Diff the BOM between revision `a` (reconstructed from the project's git) and `b`
        # (blank = the current build). The current build's cached priced lines feed the
        # cost/lead deltas so they are meaningful. A missing `a` or a non-git project is a
        # ValueError -> 400; an unknown id -> 404.
        ctx = request.app.state.ctx
        cached = ctx.bom_cache.get(project_id)
        current_rows = cached["lines"] if (cached and cached.get("ran_at")) else None
        return ctx.project_ops.bom_diff(project_id, a, b, current_rows=current_rows)

    @r.get("/{project_id}/design")
    def get_design(request: Request, project_id: str, floor: str = "none") -> dict:
        # The project's current net classes + design rules read straight from its
        # .kicad_pro, plus a fab-floor validation and the fab-floor catalog for the
        # picker (M7e). Read-only. Unknown id -> 404; a project with no .kicad_pro is an
        # honest empty shape, never a crash.
        ctx = request.app.state.ctx
        return ctx.project_ops.design_settings(project_id, floor=floor)

    @r.patch("/{project_id}/net-classes")
    def patch_net_classes(request: Request, project_id: str, body: SetNetClassesBody) -> dict:
        # Edit the project's net classes: reconcile the submitted set onto the on-disk
        # classes and write net_settings.classes back as a minimal diff, one scoped commit
        # on the project's OWN git (M7e). A class with no name is a clean 422; an unknown id
        # -> 404; a project not under git (or without a .kicad_pro) -> 400; a GitError -> 503.
        # A net-class change can alter DRC, so the stale cached ERC/DRC is evicted (never a
        # fabricated pass) and the next check re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_net_classes(
            project_id, [c.model_dump() for c in body.classes],
            deleted=body.deleted, floor=body.floor,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.patch("/{project_id}/design-rules")
    def patch_design_rules(request: Request, project_id: str, body: SetDesignRulesBody) -> dict:
        # Edit the board design-rule constraints (and, when given, the track/via/diff-pair
        # size lists), one scoped commit on the project's own git (M7e). Unknown id -> 404;
        # a project not under git (or without a .kicad_pro) -> 400; a GitError -> 503. The
        # stale cached ERC/DRC is evicted since a design-rule change can alter DRC outcomes.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_design_rules(
            project_id, body.rules, track_widths=body.track_widths,
            via_dimensions=body.via_dimensions, diff_pair_dimensions=body.diff_pair_dimensions,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/settings")
    def get_settings(request: Request, project_id: str) -> dict:
        # The project's board setup + thickness (from its .kicad_pcb) AND its .kicad_pro
        # settings (ERC/DRC rule severities, the ERC pin-conflict matrix, project text variables)
        # plus the editor catalogs (M7f-A + A2). Read-only. Unknown id -> 404; a project with no
        # board and/or no .kicad_pro is an honest empty shape (pin_map None, never fabricated).
        ctx = request.app.state.ctx
        return ctx.project_ops.board_settings(project_id)

    @r.patch("/{project_id}/settings")
    def patch_settings(request: Request, project_id: str, body: SetSettingsBody) -> dict:
        # Write board setup / thickness (to the .kicad_pcb) and/or ERC/DRC severities, the ERC
        # pin map, project text variables (to the .kicad_pro) as a minimal diff, one atomic
        # commit on the project's OWN git (M7f-A + A2). Unknown id -> 404; a project not under
        # git, with no board (for a board edit) or no .kicad_pro (for a pro edit), nothing to
        # write, or a bad value -> 400; a GitError -> 503. A severity/board change can alter
        # ERC/DRC outcomes, so the stale cached ERC/DRC is evicted and the next check re-runs.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_settings(
            project_id, board_setup=body.board_setup, thickness=body.thickness,
            erc_severities=body.erc_severities, drc_severities=body.drc_severities,
            erc_pin_map=body.erc_pin_map, text_variables=body.text_variables,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    return r


def _bom_price_lookup(ctx):
    """A price_lookup(mpn) served by Stockroom's own enrich layer: build the same
    pipeline the enrich routes use, enrich each MPN (cache-first), and adapt the result
    into the BOM's flat cost dict. Any failure or a total miss returns None, so the line
    stays honestly unpriced and a price is never invented."""
    from stockroom.api.routers.enrich import _make_pipeline
    from stockroom.projects.bom import enrichment_to_bom_lookup

    pipeline = _make_pipeline(ctx)

    def lookup(mpn):
        try:
            result = pipeline.enrich(mpn, "Other")
        except Exception:  # noqa: BLE001 - a dead lookup leaves the line unpriced, never blocks
            return None
        return enrichment_to_bom_lookup(result)

    return lookup
