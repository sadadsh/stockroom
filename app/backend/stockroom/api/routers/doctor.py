"""Drift detection and KiCad wiring (spec sections 2.2, 5.4). Wiring runs as a job
because it may create category libraries and rewrite the KiCad config, and it must
surface restart_needed when KiCad is running."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.wiring import KiCadWiring


def doctor_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/doctor", dependencies=[Depends(require_token)])

    @r.get("/scan")
    def scan(request: Request) -> dict:
        """A read-only health pass: what the one-click repair would fix, what it can't
        (shown so the user sees the diff before healing, spec section 3)."""
        ctx = request.app.state.ctx
        plan = ctx.ops.scan_repairs()
        return {
            "fixable": [
                {"kind": a.kind, "part_id": a.part_id, "detail": a.detail,
                 "before": a.before, "after": a.after}
                for a in plan.fixable
            ],
            "manual": [
                {"kind": f.kind, "part_id": f.part_id, "detail": f.detail,
                 "how_to_fix": f.how_to_fix}
                for f in plan.manual
            ],
            "uncommitted": list(plan.uncommitted),
            "healthy": plan.is_healthy,
        }

    @r.post("/repair")
    def repair(request: Request) -> dict:
        """Heal every fixable defect and sweep uncommitted changes into one scoped
        commit. A mutation like edit/move/delete, so it runs synchronously and returns
        what it did plus the manual findings it could not auto-fix."""
        ctx = request.app.state.ctx
        result = ctx.ops.apply_repairs()
        return {
            "healed_drift": result.healed_drift,
            "fixed_paths": result.fixed_paths,
            "committed_files": result.committed_files,
            "hidden_metadata": result.hidden_metadata,
            "commit": result.commit,
            "manual": [
                {"kind": f.kind, "part_id": f.part_id, "detail": f.detail,
                 "how_to_fix": f.how_to_fix}
                for f in result.manual
            ],
        }

    @r.post("/wire-kicad")
    def wire_kicad(request: Request) -> dict:
        ctx = request.app.state.ctx

        def work(progress):
            progress({"pct": 10, "message": "wiring KiCad"})
            report = KiCadWiring(ctx.kicad_dir, cli=ctx.cli).apply(ctx.profile)
            return {
                "sr_lib_value": report.sr_lib_value,
                "categories_registered": list(report.categories_registered),
                "symbol_rows_added": report.symbol_rows_added,
                "footprint_rows_added": report.footprint_rows_added,
                "libs_created": list(report.libs_created),
                "kicad_running": report.kicad_running,
                "restart_needed": report.restart_needed,
            }

        # write=True: wiring rewrites the shared KiCad config (sym/fp-lib-table, SR_LIB), so
        # it runs on the serialized write lane (two concurrent rewrites would interleave).
        return {"job_id": ctx.jobs.submit(work, write=True)}

    return r
