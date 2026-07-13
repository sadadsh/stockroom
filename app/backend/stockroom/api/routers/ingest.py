"""Ingest as a background job with SSE progress plus a synchronous, gate-enforcing
commit (spec sections 2.2, 5, 6). Inspect runs off the request path (unpacking a
zip and running kicad-cli is well over 100ms); commit is synchronous because it is
one atomic transaction whose result (added or rejected-with-missing) the caller
needs immediately. The complete-to-add gate lives in add_part, unchanged."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from stockroom.api.jobs import to_sse
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Purchase


def _make_pipeline(ctx) -> IngestPipeline:
    return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)


def candidate_to_dto(c: StagingCandidate) -> dict:
    return {
        "vendor": c.vendor,
        "symbol_lib_path": str(c.symbol_lib_path) if c.symbol_lib_path else None,
        "symbol_name": c.symbol_name,
        "footprint_variants": [str(p) for p in c.footprint_variants],
        "chosen_footprint_index": c.chosen_footprint_index,
        "model_path": str(c.model_path) if c.model_path else None,
        "datasheet_path": str(c.datasheet_path) if c.datasheet_path else None,
        "display_name": c.display_name,
        "entry_name": c.entry_name,
        "category": c.category,
        "mpn": c.mpn,
        "manufacturer": c.manufacturer,
        "description": c.description,
        "tags": list(c.tags),
        "gaps": list(c.gaps),
    }


def dto_to_candidate(d: dict) -> StagingCandidate:
    return StagingCandidate(
        vendor=d.get("vendor", ""),
        symbol_lib_path=Path(d["symbol_lib_path"]) if d.get("symbol_lib_path") else None,
        symbol_name=d.get("symbol_name", ""),
        footprint_variants=[Path(p) for p in d.get("footprint_variants", [])],
        chosen_footprint_index=d.get("chosen_footprint_index", 0),
        model_path=Path(d["model_path"]) if d.get("model_path") else None,
        datasheet_path=Path(d["datasheet_path"]) if d.get("datasheet_path") else None,
        display_name=d.get("display_name", ""),
        entry_name=d.get("entry_name", ""),
        category=d.get("category", "Other"),
        mpn=d.get("mpn", ""),
        manufacturer=d.get("manufacturer", ""),
        description=d.get("description", ""),
        tags=list(d.get("tags", [])),
        purchase=[Purchase(**p) for p in d.get("purchase", [])],
    )


def ingest_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @r.post("/ingest/inspect")
    def inspect(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        paths = [Path(p) for p in body.get("paths", [])]
        lcsc_ids = list(body.get("lcsc_ids", []))

        def work(progress):
            progress({"pct": 5, "message": "unpacking"})
            pipeline = _make_pipeline(ctx)
            candidates = pipeline.inspect(inputs=paths, lcsc_ids=lcsc_ids)
            progress({"pct": 90, "message": "staged"})
            return [candidate_to_dto(c) for c in candidates]

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/ingest/commit")
    def commit(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body)
        record = pipeline.commit(candidate)  # IncompleteError -> 422 via the handler
        ctx.rebuild_index()
        return record.to_dict()

    @r.get("/jobs/{job_id}/events")
    def job_events(request: Request, job_id: str) -> EventSourceResponse:
        ctx = request.app.state.ctx

        def gen():
            for event in ctx.jobs.events(job_id):
                yield to_sse(event)

        return EventSourceResponse(gen())

    return r
