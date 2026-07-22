"""Altium Database Library surface for the active profile: a status view over every part, a
synchronous regenerate of the DbLib, and a per-part asset attach. The engine lives in
LibraryOps (regenerate_altium_dblib / attach_altium_assets); this router is thin and guarded.

Everything is scoped to the ACTIVE profile via ctx.ops / ctx.profile, so switching profiles
switches the DbLib this surface reflects."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
from stockroom.ingest.component_naming import derive_value
from stockroom.model.part import altium_assets_ready


def _row(record) -> dict:
    """One status row per part: its identity + the Value the emitter would write + the resolved
    Altium symbol/footprint names, and whether it is place-ready (assets + required fields)."""
    sym = record.altium_symbol
    fp = record.altium_footprint
    required = bool(record.mpn and record.manufacturer and record.description)
    return {
        "id": record.id,
        "display_name": record.display_name,
        "category": record.category,
        "mpn": record.mpn,
        "value": record.value or derive_value(record),
        "symbol": sym.name if sym else "",
        "footprint": fp.name if fp else "",
        "ready": bool(altium_assets_ready(record) and required),
    }


def altium_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/altium", dependencies=[Depends(require_token)])

    @r.get("/status")
    def status(request: Request) -> dict:
        ctx = request.app.state.ctx
        rows = [_row(ctx.ops.load_record(row.id)) for row in ctx.index.search("")]
        altium_dir = ctx.profile.library.parts_dir.parent / "altium"
        return {
            "profile": ctx.profile.name,
            "dblib": str(altium_dir / "Stockroom.DbLib"),
            "dblib_dir": str(altium_dir),
            "ready": sum(1 for x in rows if x["ready"]),
            "total": len(rows),
            # not-ready first (the ones needing attention), then by name
            "rows": sorted(rows, key=lambda x: (x["ready"], x["display_name"].lower())),
        }

    @r.post("/regenerate")
    def regenerate(request: Request) -> dict:
        ctx = request.app.state.ctx
        result = ctx.ops.regenerate_altium_dblib()
        ctx.auto_push()  # the DbLib commit pushes like any other library write (no-op without a token)
        return {
            "emitted": result["emitted"],
            "skipped": result["skipped"],
            "dblib": str(result["dblib"]),
        }

    @r.post("/parts/{part_id}/attach")
    def attach(request: Request, part_id: str, body: dict) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        sources = [Path(p) for p in body.get("paths", [])]
        if not sources:
            raise ApiError(422, "attach needs a .SchLib and .PcbLib pair, or a single .IntLib")
        record = ctx.ops.attach_altium_assets(part_id, *sources)  # ValueError -> 400 on bad source
        ctx.rebuild_index()
        ctx.auto_push()
        return record.to_dict()

    return r
