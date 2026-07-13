"""Drift detection and KiCad wiring (spec sections 2.2, 5.4). Wiring runs as a job
because it may create category libraries and rewrite the KiCad config, and it must
surface restart_needed when KiCad is running."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.wiring import KiCadWiring


def doctor_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/doctor", dependencies=[Depends(require_token)])

    @r.get("/drift")
    def drift(request: Request) -> dict:
        ctx = request.app.state.ctx
        report = ctx.ops.detect_drift()
        return {
            "items": [
                {"part_id": i.part_id, "property": i.property,
                 "json_value": i.json_value, "symbol_value": i.symbol_value}
                for i in report.items
            ],
            "missing_symbol": list(report.missing_symbol),
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

        return {"job_id": ctx.jobs.submit(work)}

    return r
