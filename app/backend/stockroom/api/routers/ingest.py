"""Ingest as a background job with SSE progress plus a synchronous, gate-enforcing
commit (spec sections 2.2, 5, 6). Inspect runs off the request path (unpacking a
zip and running kicad-cli is well over 100ms); commit is synchronous because it is
one atomic transaction whose result (added or rejected-with-missing) the caller
needs immediately. The complete-to-add gate lives in add_part, unchanged."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from stockroom.api.jobs import to_sse
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


_KNOWN_VENDOR_HOSTS = {"lcsc": "LCSC", "mouser": "Mouser", "digikey": "DigiKey"}


def vendor_from_url(url: str) -> str:
    """A display vendor for a pasted purchase link: the known distributors by
    name, any other shop by its host, and a non-URL as a manual entry."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return "manual"
    for token, name in _KNOWN_VENDOR_HOSTS.items():
        if token in host:
            return name
    return host.removeprefix("www.")


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
    )


def _attach_local_datasheet(ctx, candidate: StagingCandidate, path: Path, notes: list[str]) -> None:
    """Copy a user-picked PDF under the app's datasheet store and attach it to the
    candidate. Refusals are stated in notes, never silent: a non-PDF or unreadable
    file leaves the candidate untouched. The stored name carries a content hash so
    two staged parts with the same normalized identity never clobber each other."""
    import hashlib

    from stockroom.enrich.datasheet import looks_like_pdf
    from stockroom.enrich.schema import normalize_mpn

    try:
        with open(path, "rb") as fh:
            head = fh.read(5)
    except OSError:
        notes.append(f"Could not read the datasheet file: {path.name}")
        return
    if not looks_like_pdf(head):
        notes.append(f"{path.name} is not a PDF, so it was not attached")
        return
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    dest_dir = Path(ctx.enrich_cache_dir) / "datasheets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    key = normalize_mpn(
        candidate.mpn or candidate.entry_name or candidate.display_name or path.stem
    )
    dst = dest_dir / f"{key}-{digest.hexdigest()[:8]}.pdf"
    shutil.copyfile(path, dst)
    candidate.datasheet_path = dst


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

    @r.post("/ingest/enrich")
    def enrich_candidate_route(request: Request, body: dict) -> dict:
        """Fill a staged candidate: apply the explicit links the user pasted (a
        datasheet URL or local PDF, a purchase URL), read identity from the stored
        datasheet (the primary source), then run the enrichment pipeline over what
        is still blank. A job: the datasheet fetch and the scrape are network-bound."""
        ctx = request.app.state.ctx
        dto = body.get("candidate") or {}
        datasheet_url = str(body.get("datasheet_url") or "").strip()
        purchase_url = str(body.get("purchase_url") or "").strip()
        datasheet_file = str(body.get("datasheet_file") or "").strip()

        def work(progress):
            from stockroom.enrich.bulk import _missing_for

            candidate = dto_to_candidate(dto)
            before = {
                "mpn": candidate.mpn,
                "manufacturer": candidate.manufacturer,
                "description": candidate.description,
                "datasheet": candidate.datasheet_path,
                "purchase": list(candidate.purchase),
            }
            notes: list[str] = []
            pipeline = _make_enrich_pipeline(ctx)
            if purchase_url:
                # explicit user input wins over anything scraped later
                candidate.purchase = [
                    Purchase(vendor=vendor_from_url(purchase_url), url=purchase_url)
                ]
            if datasheet_file:
                progress({"pct": 10, "message": "attaching the datasheet"})
                _attach_local_datasheet(ctx, candidate, Path(datasheet_file), notes)
            if datasheet_url:
                progress({"pct": 20, "message": "fetching the datasheet"})
                stored = pipeline.fetch_and_store_datasheet(
                    candidate, datasheet_url, force=True
                )
                if stored is None:
                    notes.append("The datasheet link did not yield a PDF")
                else:
                    # record the source only for a fetch that actually succeeded
                    if candidate.provenance is None:
                        candidate.provenance = Provenance(source="manual")
                    if not candidate.provenance.source_url:
                        candidate.provenance.source_url = datasheet_url
            if candidate.datasheet_path is not None:
                progress({"pct": 45, "message": "reading the datasheet"})
                pipeline.datasheet_fill(candidate)
            progress({"pct": 60, "message": "enriching what is still blank"})
            pipeline.enrich_candidate(candidate)
            filled = [
                name
                for name, prior in before.items()
                if not prior
                and {
                    "mpn": candidate.mpn,
                    "manufacturer": candidate.manufacturer,
                    "description": candidate.description,
                    "datasheet": candidate.datasheet_path,
                    "purchase": candidate.purchase,
                }[name]
            ]
            return {
                "candidate": candidate_to_dto(candidate),
                "filled": filled,
                "notes": notes,
                "missing": _missing_for(candidate),
            }

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/ingest/commit")
    def commit(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body)
        record = pipeline.commit(candidate)  # IncompleteError -> 422 via the handler
        ctx.rebuild_index()
        ctx.auto_push()  # adding a part auto-pushes it to git so collaborators get it on next launch
        return record.to_dict()

    @r.post("/parts/{part_id}/assets/inspect")
    def inspect_assets_for_part(request: Request, part_id: str, body: dict) -> dict:
        """Unpack a downloaded CAD ZIP for an EXISTING part (the owner's DigiKey-CAD
        flow, spec section 5). Same read-lane job + candidate DTO as /ingest/inspect;
        the only difference is the caller already knows the target part_id, so this
        checks it exists up front instead of discovering it only at commit time.
        Deliberately does NOT call pipeline.cleanup() here (same as /ingest/inspect):
        a candidate's symbol/footprint/model paths point INTO the pipeline's owned
        tempdir and a fresh pipeline instance handles the follow-up commit call, so
        cleaning up here would delete the very files that commit still needs."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        paths = [Path(p) for p in (body.get("paths") or [])]

        def work(progress):
            progress({"pct": 5, "message": "unpacking"})
            pipeline = _make_pipeline(ctx)
            cands = pipeline.inspect(inputs=paths)
            progress({"pct": 90, "message": "staged"})
            return [candidate_to_dto(c) for c in cands]

        return {"job_id": ctx.jobs.submit(work)}  # read lane (no git)

    @r.post("/parts/{part_id}/assets/commit")
    def commit_assets_for_part(request: Request, part_id: str, body: dict) -> dict:
        """Attach the reviewed candidate's symbol/footprint/3D onto the existing part,
        synchronously (one atomic Transaction whose added-or-rejected result the caller
        needs immediately, same reasoning as /ingest/commit)."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body)
        record = pipeline.attach_assets(part_id, candidate)
        ctx.rebuild_index()
        ctx.auto_push()  # attaching assets changes the part, so push it like any other mutation
        return record.to_dict()

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

    return r
