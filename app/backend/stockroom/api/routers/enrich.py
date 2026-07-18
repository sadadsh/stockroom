"""Enrichment surface: a fast cached single-MPN enrich, a background bulk import,
and the datasheet fetch (spec sections 6.1, 8.1). The pipeline is built with the
context's RenderedDomFetcher when the host has injected the real WebView2 one
(Windows); on Linux/CI it defaults to HttpRenderedDomFetcher, so the M4 seam is
wired end-to-end through the API today (source-agnostic completeness: a scrape miss
never blocks the gate)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.enrich.bulk import bulk_enrich, parse_bom_csv, parse_mpn_list
from stockroom.enrich.pipeline import EnrichmentPipeline
from stockroom.enrich.schema import EnrichmentResult, Sourced


def _make_pipeline(ctx) -> EnrichmentPipeline:
    mouser = None
    if ctx.config.mouser_api_key:
        from stockroom.enrich.mouser import MouserAdapter

        mouser = MouserAdapter(api_key=ctx.config.mouser_api_key)
    digikey = None
    if getattr(ctx.config, "digikey_client_id", "") and getattr(ctx.config, "digikey_client_secret", ""):
        from stockroom.enrich.digikey_api import DigiKeyAdapter

        digikey = DigiKeyAdapter(ctx.config.digikey_client_id, ctx.config.digikey_client_secret)
    return EnrichmentPipeline(
        ctx.enrich_cache_dir,
        fetcher=ctx.rendered_dom_fetcher,  # None -> pipeline's HTTP default
        mouser=mouser,
        digikey=digikey,
    )


def _sourced_dto(s: Sourced | None) -> dict | None:
    if s is None:
        return None
    return {"value": s.value, "source": s.source, "confidence": s.confidence}


def _add_plan(r: EnrichmentResult) -> dict | None:
    """The passive-or-not determination the unified Add-A-Part flow branches on: the
    {kind, package, value, tolerance} a file-less passive add needs, or None when the
    part is not an addable file-less passive (it then takes the drop-the-assets path)."""
    from stockroom.enrich.passive import passive_add_plan

    def v(s):
        return "" if s is None else str(s.value)

    return passive_add_plan(
        mpn=v(r.mpn),
        category=r.category,
        package=v(r.package),
        specs={k: str(s.value) for k, s in r.specs.items() if s is not None},
        description=v(r.description),
    )


def _result_dto(r: EnrichmentResult) -> dict:
    return {
        "category": r.category,
        "mpn": _sourced_dto(r.mpn),
        "manufacturer": _sourced_dto(r.manufacturer),
        "description": _sourced_dto(r.description),
        "datasheet_url": _sourced_dto(r.datasheet_url),
        "stock": _sourced_dto(r.stock),
        "package": _sourced_dto(r.package),
        # A2: the FULL pulled depth, not just identity + specs. These live on the schema (the
        # Mouser/LCSC paths fill them) but the DTO dropped them, so the UI could never surface
        # a part's manufacturing status, lead time, product page, or distributor order numbers.
        "lifecycle": _sourced_dto(r.lifecycle),
        "lead_time": _sourced_dto(r.lead_time),
        "product_url": _sourced_dto(r.product_url),
        "dist_pns": dict(r.dist_pns),
        "price_breaks": [
            {"qty": p.qty, "price": p.price, "currency": p.currency} for p in r.price_breaks
        ],
        "specs": {k: _sourced_dto(v) for k, v in r.specs.items()},
        # The passive determination for the unified Add-A-Part flow (null = non-passive,
        # needs the symbol/footprint/3D dropped).
        "add_plan": _add_plan(r),
        "schema_version": r.schema_version,
    }


def _report_dto(report) -> dict:
    return {
        "items": [
            {"mpn": i.mpn, "complete": i.complete, "missing": list(i.missing), "error": i.error}
            for i in report.items
        ],
    }


def enrich_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/enrich", dependencies=[Depends(require_token)])

    @r.post("/part")
    def enrich_part(request: Request, body: dict) -> dict:
        """Look a part up by MPN through the pipeline. Runs as a background job (spec
        section 8): the render tier can take seconds, so the window never blocks. The SSE
        stream emits the live `fetching -> rendering -> extracting -> validating` stages and
        ends with the sourced DTO on the `result` event."""
        ctx = request.app.state.ctx
        mpn = body["mpn"]
        category = body.get("category", "Other")
        want = body.get("want")

        def work(progress):
            pipeline = _make_pipeline(ctx)
            return _result_dto(pipeline.enrich(mpn, category, want=want, progress=progress))

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/from-url")
    def enrich_from_url(request: Request, body: dict) -> dict:
        """Paste a distributor product URL (a Mouser link) -> fetch it through the real
        browser and return EVERYTHING the page exposes: identity, price breaks, stock, a
        datasheet URL, package, and the full parametric spec set. This is the "paste a
        link and autofill all of it" seam; a blocked/dead page returns empty fields, not
        an error. A background job (spec section 8): the live stage sequence streams over
        SSE and the sourced DTO arrives on the terminal `result` event."""
        ctx = request.app.state.ctx
        url = str(body.get("url", ""))

        def work(progress):
            pipeline = _make_pipeline(ctx)
            return _result_dto(pipeline.extract_from_url(url, progress=progress))

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/bulk")
    def enrich_bulk(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        if "csv" in body:
            mpns = parse_bom_csv(body["csv"])
        else:
            mpns = parse_mpn_list(body.get("text", ""))
        category = body.get("category", "Other")

        def work(progress):
            progress({"pct": 1, "message": f"enriching {len(mpns)} parts"})
            pipeline = _make_pipeline(ctx)
            report = bulk_enrich(mpns, pipeline, category=category)
            return _report_dto(report)

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/datasheet")
    def enrich_datasheet(request: Request, body: dict) -> dict:
        from stockroom.api.routers.ingest import dto_to_candidate

        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body.get("candidate", {}))
        path = pipeline.fetch_and_store_datasheet(candidate, body["url"])
        return {"stored": str(path) if path else None}

    return r
