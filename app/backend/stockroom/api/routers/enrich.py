"""Enrichment surface: a fast cached single-MPN enrich, a background bulk import,
and the datasheet fetch (spec sections 6.1, 8.1). The pipeline is built with the
context's RenderedDomFetcher when the host has injected the real WebView2 one
(Windows); on Linux/CI it defaults to HttpRenderedDomFetcher, so the M4 seam is
wired end-to-end through the API today (source-agnostic completeness: a scrape miss
never blocks the gate)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError
from stockroom.enrich.pipeline import EnrichmentPipeline
from stockroom.enrich.schema import SOURCED_FIELDS, EnrichmentResult, Sourced


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
        # A2: the FULL pulled depth, not just identity + specs. Every single-valued canonical
        # field, enumerated from the schema rather than retyped, because a hand-written list here
        # dropped lifecycle/lead_time/product_url once and then country_of_origin/tariff_rate
        # again: the Mouser path filled a part's origin and its real US import tariff and the UI
        # could never see either. Iterating means a field added to the schema reaches the UI by
        # construction.
        **{name: _sourced_dto(getattr(r, name)) for name in SOURCED_FIELDS},
        "dist_pns": dict(r.dist_pns),
        # every vendor's own ladder + stock for the comparison view (owner 2026-07-24)
        "dist_price_breaks": {
            k: [{"qty": p.qty, "price": p.price, "currency": p.currency} for p in v]
            for k, v in r.dist_price_breaks.items()
        },
        "dist_stock": dict(r.dist_stock),
        "catalog": {key: dict(value) for key, value in r.catalog.items()},
        # both distributor buy links (mouser + digikey) when both APIs answered, so the committed
        # part carries every place it can be ordered, not only the pasted link.
        "dist_urls": dict(r.dist_urls),
        "price_breaks": [
            {"qty": p.qty, "price": p.price, "currency": p.currency} for p in r.price_breaks
        ],
        "specs": {k: _sourced_dto(v) for k, v in r.specs.items()},
        # every kept disagreement between sources, all values with their origins (owner
        # 2026-07-24: "display all of it and only merge stuff thats identical")
        "spec_conflicts": {
            k: [_sourced_dto(v) for v in vs] for k, vs in r.spec_conflicts.items()
        },
        # the same, for the single-valued fields: both descriptions, both packages, both
        # datasheet links - whatever two sources disagreed on, with each origin
        "field_conflicts": {
            k: [_sourced_dto(v) for v in vs] for k, vs in r.field_conflicts.items()
        },
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


def _import_report_dto(report) -> dict:
    """Every row, plus the counts. The rows are the point: a summary alone ("143 added") leaves
    the owner with no way to see WHICH 26 did not, which is the half that needs their attention."""
    return {
        "counts": report.counts(),
        "items": [
            {"query": i.query, "mpn": i.mpn, "part_id": i.part_id, "status": i.status,
             "display_name": i.display_name, "category": i.category,
             "missing": list(i.missing), "error": i.error, "resolved_by": i.resolved_by,
             # "kicad-stock" = a real placeable symbol + footprint + 3D landed; "none" = the
             # record landed on identity alone. This is the column that answers "did I get the
             # FILES", which a status of "added" on its own cannot.
             "assets": i.assets}
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

    @r.post("/bulk-import")
    def bulk_import_route(request: Request, body: dict) -> dict:
        """Import a pasted list of part numbers (or a BOM CSV) into the library.

        A background job, because 169 parts is minutes of network work, and the SSE stream
        names the part it is on: a bar with no part name cannot be told from a hang.

        Runs on the READ lane and pushes each individual add onto the WRITE lane
        (`jobs.run_write`), exactly as the rescan does - so every commit stays serialized
        against every other writer while the slow network work never occupies the single write
        worker. `dry_run` reports what WOULD land and writes nothing, so an import into the
        owner's real git-backed library is previewable before it commits.
        """
        from stockroom.enrich.bulk import bulk_import, parse_bom_csv, parse_mpn_list

        ctx = request.app.state.ctx
        text = str(body.get("text", ""))
        queries = list(body.get("part_numbers") or [])
        if not queries and text:
            queries = parse_bom_csv(text) if body.get("format") == "csv" else parse_mpn_list(text)
        if not queries:
            raise ApiError(422, "no part numbers to import")
        dry_run = bool(body.get("dry_run"))
        category = str(body.get("category") or "Other")

        class _WriteLaneOps:
            """add_part on the serialized write lane. The mutation is unchanged - the same
            complete-to-add gate, the same single git Transaction - only its thread differs."""

            @staticmethod
            def add_part(staged):
                return ctx.jobs.run_write(lambda: ctx.ops.add_part(staged))

            @staticmethod
            def add_passive_part(record):
                """The passive lane: a record carrying KiCad stock symbol/footprint/3D refs.
                Same write lane, same atomic commit; only the seam differs."""
                return ctx.jobs.run_write(lambda: ctx.ops.add_passive_part(record))

        def work(progress):
            pipeline = _make_pipeline(ctx)

            def on_progress(done: int, total: int, query: str) -> None:
                if progress is None:
                    return
                progress({
                    "stage": "importing",
                    "pct": (done / total) if total else 1.0,
                    "done": done, "total": total, "query": query,
                    "message": f"importing {query} ({done + 1} of {total})",
                })

            report = bulk_import(
                # A CALLABLE, not the index object: a 166-part run lasts ~28 minutes and the
                # background sync rebuilds the index during it, closing the handle. Passing
                # `ctx.index` by value failed 37 of 166 parts on the owner's real library.
                queries,
                pipeline,
                _WriteLaneOps(),
                index=lambda: ctx.index,
                category=category,
                dry_run=dry_run,
                on_progress=on_progress,
            )
            if not dry_run and report.of("added"):
                ctx.jobs.run_write(ctx.rebuild_index)
                ctx.jobs.run_write(ctx.auto_push)
            return _import_report_dto(report)

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/digikey/quantity-pricing")
    def digikey_quantity_pricing(request: Request, body: dict) -> dict:
        """Quantity-aware official pricing for a BOM/order decision.

        DigiReel is opt-in per request: merely looking at a part never asks DigiKey to calculate
        an order service. The caller must explicitly say it is preparing an order.
        """
        from stockroom.enrich.digikey_api import DigiKeyClient

        ctx = request.app.state.ctx
        product_number = str(body.get("product_number") or "").strip()
        quantity_value = body.get("quantity")
        try:
            if isinstance(quantity_value, bool):
                raise ValueError
            quantity = int(str(quantity_value))
        except (TypeError, ValueError):
            raise ApiError(422, "quantity must be a positive integer") from None
        if not product_number or quantity < 1:
            raise ApiError(422, "product_number and a positive quantity are required")
        if not ctx.config.digikey_client_id or not ctx.config.digikey_client_secret:
            raise ApiError(409, "DigiKey Product Information credentials are not configured")
        prepare_order = body.get("prepare_order") is True

        def work(progress):
            client = DigiKeyClient(
                ctx.config.digikey_client_id,
                ctx.config.digikey_client_secret,
            )
            progress({"stage": "fetching", "pct": 0.2, "message": "reading quantity pricing"})
            pricing_payload = client.pricing_options_by_quantity(product_number, quantity)
            from stockroom.enrich.digikey_api import pricing_options_from_payload

            result = {
                "product_number": product_number,
                "quantity": quantity,
                "options": pricing_options_from_payload(pricing_payload),
                "pricing_options": pricing_payload,
                "digireel": None,
            }
            if prepare_order:
                progress({"stage": "fetching", "pct": 0.7, "message": "calculating DigiReel"})
                result["digireel"] = client.digireel_pricing(product_number, quantity)
            return result

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/digikey/taxonomy")
    def digikey_taxonomy(request: Request, body: dict | None = None) -> dict:
        """Cached canonical DigiKey manufacturers/categories for pickers and classification."""
        from stockroom.enrich.cache import TtlCache
        from stockroom.enrich.digikey_api import DigiKeyClient

        ctx = request.app.state.ctx
        if not ctx.config.digikey_client_id or not ctx.config.digikey_client_secret:
            raise ApiError(409, "DigiKey Product Information credentials are not configured")
        refresh = isinstance(body, dict) and body.get("refresh") is True

        def work(progress):
            cache = TtlCache(
                ctx.enrich_cache_dir,
                ttl=7 * 86400.0,
                prefix="digikey-taxonomy",
            )
            if not refresh and (cached := cache.get("canonical")) is not None:
                return {**cached, "cached": True}
            client = DigiKeyClient(
                ctx.config.digikey_client_id,
                ctx.config.digikey_client_secret,
            )
            progress({"stage": "fetching", "pct": 0.25, "message": "reading manufacturers"})
            manufacturers = client.manufacturers()
            progress({"stage": "fetching", "pct": 0.7, "message": "reading categories"})
            categories = client.categories()
            result = {
                "schema_version": 1,
                "manufacturers": manufacturers,
                "categories": categories,
            }
            cache.put("canonical", result)
            return {**result, "cached": False}

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/image")
    def product_image(request: Request, url: str) -> Response:
        """Proxy a pulled product photo (specs["Image"]) for the SPA's <img> fallback: a
        vendor CDN that refuses the browser's hotlink still renders, served from the disk
        cache after the first fetch. 400 for a URL the proxy refuses to touch (hostile
        input - loopback/private/plain-http); 404 when the fetch yields no real image."""
        from stockroom.enrich.image_proxy import allowed_image_url, fetch_product_image

        ctx = request.app.state.ctx
        if not allowed_image_url(url):
            raise HTTPException(status_code=400, detail="URL not allowed")
        got = fetch_product_image(url, ctx.enrich_cache_dir)
        if got is None:
            raise HTTPException(status_code=404, detail="No image at that URL")
        data, ctype = got
        return Response(
            content=data,
            media_type=ctype,
            headers={"Cache-Control": "private, max-age=86400"},
        )

    return r
