"""Ingest as a background job with SSE progress plus a synchronous, gate-enforcing
commit (spec sections 2.2, 5, 6). Inspect runs off the request path (unpacking a
zip and running kicad-cli is well over 100ms); commit is synchronous because it is
one atomic transaction whose result (added or rejected-with-missing) the caller
needs immediately. The complete-to-add gate lives in add_part, unchanged."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from stockroom.api.errors import ApiError
from stockroom.api.jobs import to_sse
from stockroom.enrich.distributor_url import vendor_from_url
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Provenance, Purchase


def _make_pipeline(ctx) -> IngestPipeline:
    return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)


def _make_enrich_pipeline(ctx):
    # The same construction the enrich router uses (cache dir, rendered-DOM
    # fetcher, optional Mouser); one seam so the two routers can never disagree.
    from stockroom.api.routers.enrich import _make_pipeline as make

    return make(ctx)


# `vendor_from_url` is imported above rather than defined here. It used to live in this router,
# where the Qt-free enrich pipeline could not reach it -- so the pipeline hardcoded
# `vendor="scrape"` and 85 of the owner's records were filed under a mechanism name instead of a
# distributor. Two host maps would drift; one, in the enrich layer both callers can reach, cannot.


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
        # Serialize purchase so the DTO is symmetric with dto_to_candidate: the
        # frontend's StagingCandidate always has a purchase array (a missing key
        # crashes the review card), and edited/scraped purchase links survive commit.
        "purchase": [
            {"vendor": p.vendor, "url": p.url, "part_number": p.part_number,
             "price_breaks": list(p.price_breaks),
             "stock": p.stock, "currency": p.currency, "fetched_at": p.fetched_at}
            for p in c.purchase
        ],
        "gaps": list(c.gaps),
        # the enriched spec bag rides the inspect -> edit -> commit trip so every field
        # a distributor page yielded reaches the committed record, not just identity
        "specs": dict(c.specs),
        # ...and so do the two maps that hang off it. `specs` alone crossed the wire, so a part
        # ADDED saved `alternates: None` while the same part REFRESHED produced 13 alternates:
        # the enrich layer computed the disagreements, StagingCandidate held them and
        # to_staged_part forwarded them, and they died here. `enrichment` is the same drop,
        # which is why the per-key provenance map was empty on every real part.
        #
        # Always emitted, even when empty, for the same reason `purchase` is: the review card
        # reads these keys unconditionally and a missing key crashes it.
        "alternates": {k: list(v) for k, v in c.alternates.items()},
        "enrichment": dict(c.enrichment),
        "catalog": {key: dict(value) for key, value in c.catalog.items()},
        "official_payloads": {
            key: dict(value) for key, value in c.official_payloads.items()
        },
        "official_evidence": {
            key: dict(value) for key, value in c.official_evidence.items()
        },
        # provenance carries the datasheet source_url that to_staged_part records
        # on the committed part, so it must survive the inspect -> edit -> commit trip
        "provenance": (
            {"source": c.provenance.source, "source_url": c.provenance.source_url,
             "original_zip_sha256": c.provenance.original_zip_sha256,
             "ingested_at": c.provenance.ingested_at}
            if c.provenance is not None
            else None
        ),
    }


def dto_to_candidate(d: dict) -> StagingCandidate:
    prov = d.get("provenance")
    provenance = (
        Provenance(
            source=str(prov.get("source", "")),
            source_url=str(prov.get("source_url", "")),
            original_zip_sha256=str(prov.get("original_zip_sha256", "")),
            ingested_at=str(prov.get("ingested_at", "")),
        )
        if isinstance(prov, dict)
        else None
    )
    return StagingCandidate(
        provenance=provenance,
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
        gaps=list(d.get("gaps", [])),
        specs=dict(d.get("specs", {})),
        alternates={k: list(v) for k, v in (d.get("alternates") or {}).items()},
        enrichment=dict(d.get("enrichment") or {}),
        catalog={
            str(key): dict(value)
            for key, value in (d.get("catalog") or {}).items()
            if isinstance(value, dict)
        },
        official_payloads={
            str(key): dict(value)
            for key, value in (d.get("official_payloads") or {}).items()
            if key in {"mouser", "digikey"} and isinstance(value, dict)
        },
        official_evidence={
            str(key): dict(value)
            for key, value in (d.get("official_evidence") or {}).items()
            if key in {"mouser", "digikey"} and isinstance(value, dict)
        },
    )


def _has_local_files(candidate: StagingCandidate) -> bool:
    return (
        candidate.symbol_lib_path is not None
        or bool(candidate.symbol_name)
        or bool(candidate.footprint_variants)
        or candidate.model_path is not None
        or candidate.datasheet_path is not None
    )


def ingest_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @r.post("/ingest/inspect")
    def inspect(_request: Request, _body: dict) -> dict:
        raise ApiError(
            422,
            (
                "local ZIP and LCSC/EasyEDA CAD ingest are disabled; add an exact "
                "part identity, then use network capture for one coherent KiCad, "
                "Altium, and STEP evidence set"
            ),
        )

    @r.post("/ingest/commit")
    def commit(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body)
        if _has_local_files(candidate):
            raise ApiError(
                422,
                (
                    "local files cannot be added through ingest; add the identity first, "
                    "then use network capture for one coherent KiCad, Altium, and STEP set"
                ),
            )
        record = pipeline.commit(candidate)  # IncompleteError -> 422 via the handler
        ctx.rebuild_index()
        ctx.auto_push()  # adding a part auto-pushes it to git so collaborators get it on next launch
        return record.to_dict()

    @r.post("/parts/{part_id}/assets/inspect")
    def inspect_assets_for_part(_request: Request, part_id: str, _body: dict) -> dict:
        del part_id
        raise ApiError(
            422,
            (
                "local CAD files cannot be inspected for activation; use network "
                "capture so KiCad, Altium, and STEP share one evidence set"
            ),
        )

    @r.post("/parts/{part_id}/assets/commit")
    def commit_assets_for_part(_request: Request, part_id: str, _body: dict) -> dict:
        del part_id
        raise ApiError(
            422,
            (
                "single-tool CAD attachment is disabled; use network capture so "
                "KiCad, Altium, and STEP activate atomically from one evidence set"
            ),
        )

    @r.get("/jobs/{job_id}/events")
    def job_events(request: Request, job_id: str) -> EventSourceResponse:
        ctx = request.app.state.ctx
        # Resolve the job on the REQUEST path so an unknown/expired id is an honest
        # 404 (KeyError -> 404 via the handler), not a silent 200 with an empty
        # stream: the KeyError would otherwise fire inside the threadpool-wrapped
        # generator after the response has started and be swallowed (spec 2.2: no
        # swallowed errors).
        ctx.jobs.get(job_id)

        def gen():
            for event in ctx.jobs.events(job_id):
                yield to_sse(event)

        return EventSourceResponse(gen())

    @r.post("/jobs/{job_id}/stop")
    def job_stop(request: Request, job_id: str) -> dict:
        """Ask a long job to stop at its next safe point.

        Cooperative, so the WORKER picks the boundary -- for a library-wide completion run
        that is between two parts, never inside one, and each part is its own atomic commit.
        A stopped run therefore leaves the library exactly as a finished one would, with
        fewer parts done. Resolving the job first makes an unknown id an honest 404 rather
        than a silent success.
        """
        ctx = request.app.state.ctx
        ctx.jobs.get(job_id)
        ctx.jobs.request_stop(job_id)
        return {"job_id": job_id, "stopping": True}

    return r
