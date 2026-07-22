"""Read surface over the derived index plus full detail from the source JSON.
Every list/search/facet read is served from the SQLite index for instant response
at thousands of parts (spec section 2.2); part detail loads the canonical record."""

from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, Query, Request, Response

from stockroom.api.errors import ApiError
from stockroom.api.jobs import JobStatus
from stockroom.api.schemas import (
    EditFieldBody,
    FacetsDTO,
    MoveBody,
    ParametricFacetsDTO,
    PartSummary,
    SearchRow,
    SetSpecsBody,
)
from stockroom.ingest.passive_add import (
    PassiveAddError,
    PassiveNeedsInputError,
    build_passive_record,
)
from stockroom.verify.record_diff import extract_symbol_node, field_diff

# How deep the per-part timeline reads. A part rarely accrues this many commits;
# the same cap governs history and the diff rev-validation so the two agree on what
# is reachable.
_HISTORY_MAX = 100


def _preferred_cad_vendor(config) -> str:
    """Which CAD-source vendor the guided window opens, from the saved logins: SnapEDA when the
    user has a SnapEDA login and no Ultra Librarian one, Ultra Librarian otherwise. Both offer
    KiCad + Altium behind a control the guided window can drive; picking by the saved login means
    a SnapEDA user is signed in and a UL user is signed in, with UL the zero-config default (its
    page is reachable even without a login)."""
    has_ul = bool(getattr(config, "ul_username", "") or getattr(config, "ul_password", ""))
    has_snap = bool(getattr(config, "snapeda_username", "") or getattr(config, "snapeda_password", ""))
    return "snapeda" if (has_snap and not has_ul) else "ultralibrarian"

# Single-flight guard for POST /rescan: two concurrent rescans would double the API quota
# AND clobber each other's rescan-state.json (each engine saves its whole in-memory dict,
# last-writer-wins), so a second POST while one is QUEUED/RUNNING must return the SAME
# in-flight job rather than submit a new one. One lock per process is correct here - there
# is one rescan job slot per app instance (tracked on request.app.state).
_rescan_lock = threading.Lock()


def _part_json_path(ctx, part_id: str):
    return ctx.profile.library.parts_dir / f"{part_id}.json"


def _record_at(ctx, rev: str, part_id: str) -> dict | None:
    """The part's canonical JSON as a dict at `rev`, or None when the part did not
    exist there (an empty `rev` means the earliest side of a diff)."""
    if not rev:
        return None
    text = ctx.repo.show_file(rev, _part_json_path(ctx, part_id))
    return json.loads(text) if text else None


def _symbol_node_at(ctx, rev: str, rec: dict | None) -> str | None:
    """This part's `(symbol ...)` block as it stood at `rev`, isolated from the shared
    category lib so a diff compares only this part's geometry. The category and symbol
    name are read from the record AT that rev (both can change over time)."""
    if not rec or not rev:
        return None
    sym = rec.get("symbol") or {}
    name, category = sym.get("name"), rec.get("category")
    if not name or not category:
        return None
    text = ctx.repo.show_file(rev, ctx.profile.library.symbol_lib_path(category))
    return extract_symbol_node(text, name) if text else None


def _footprint_text_at(ctx, rev: str, rec: dict | None) -> str | None:
    """This part's footprint file text at `rev` (footprints are per-part files, so no
    isolation is needed), or None when absent."""
    if not rec or not rev:
        return None
    fp = rec.get("footprint") or {}
    name, category = fp.get("name"), rec.get("category")
    if not name or not category:
        return None
    fp_file = ctx.profile.library.footprint_lib_path(category) / f"{name}.kicad_mod"
    return ctx.repo.show_file(rev, fp_file)


def _mouser_link_resolver(ctx):
    """A lazy MPN -> stored-Mouser-product-link resolver for the keyless scrape adapter (owner
    directive: the user provides the distributor link, so we scrape the part's OWN Mouser
    `Purchase.url`, never a guessed search). The map is built from the library records on first
    use and cached, so callers that never scrape Mouser (e.g. the cad-source route) never pay the
    record scan. MPNs are unique per library, so keying by normalized MPN is unambiguous."""
    from stockroom.enrich.schema import normalize_mpn

    cache: dict[str, str] = {}
    state = {"built": False}

    def resolve(mpn: str) -> str | None:
        if not state["built"]:
            for row in ctx.index.search(""):
                try:
                    rec = ctx.ops.load_record(row.id)
                except Exception:  # noqa: BLE001 - a bad record must not break the whole resolver
                    continue
                for p in rec.purchase:
                    if (p.vendor or "").lower() == "mouser" and p.url:
                        cache[normalize_mpn(rec.mpn)] = p.url
                        break
            state["built"] = True
        return cache.get(normalize_mpn(mpn))

    return resolve


def build_refresh_adapters(ctx) -> list:
    """The enabled distributor adapters, each tagged with its vendor label so a refresh maps each
    result onto its own Purchase row, in the owner's sourcing order: MOUSER PRIMARY (the keyless
    crawler over a part's stored Mouser link), the MOUSER API as a FALLBACK when the crawler
    errors/blocks, then the DIGIKEY API (owner directive 2026-07-19). One Mouser adapter drives
    both tiers; with no rendered-DOM fetcher it degrades to API-only. A separate module-level
    function so a rescan can be tested without live creds."""
    from stockroom.enrich.mouser import MouserAdapter
    from stockroom.enrich.mouser_scrape import MouserScrapeAdapter

    adapters: list = []
    api_fallback = MouserAdapter(api_key=ctx.config.mouser_api_key) if ctx.config.mouser_api_key else None
    if api_fallback is not None:
        api_fallback.vendor = "Mouser"
    mouser = MouserScrapeAdapter(
        getattr(ctx, "rendered_dom_fetcher", None),
        url_for=_mouser_link_resolver(ctx),
        api_fallback=api_fallback,
    )
    mouser.vendor = "Mouser"
    if mouser.enabled:  # the crawler (fetcher + Camoufox) OR the API fallback is available
        adapters.append(mouser)
    if getattr(ctx.config, "digikey_client_id", "") and getattr(ctx.config, "digikey_client_secret", ""):
        from stockroom.enrich.digikey_api import DigiKeyAdapter

        a = DigiKeyAdapter(ctx.config.digikey_client_id, ctx.config.digikey_client_secret)
        a.vendor = "DigiKey"
        adapters.append(a)
    return adapters


def library_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/library", dependencies=[Depends(require_token)])

    @r.get("/parts")
    def list_parts(
        request: Request,
        q: str = "",
        category: str | None = None,
        complete_only: bool = False,
        spec: list[str] = Query(default=[]),
    ) -> dict:
        """The parts list, scoped by text/category/completeness in the derived index, then -
        for the modular parametric search - narrowed by any ``spec`` constraints
        (``<key>:<value>`` or ``<key>:<min>~<max>``, repeatable). The spec filter loads each
        candidate's record (bounded: the parametric rail is category-scoped) and keeps those
        whose spec bag satisfies every constraint, reusing the SAME normalization the facets
        are built from so a checkbox never disagrees with the list it produces."""
        from stockroom.store.parametric import matches_spec_filters, parse_spec_filters

        ctx = request.app.state.ctx
        rows = ctx.index.search(query=q, category=category, complete_only=complete_only)
        constraints = parse_spec_filters(spec)
        if constraints:
            rows = [
                row for row in rows
                if matches_spec_filters(ctx.ops.load_record(row.id), constraints)
            ]
        return {"parts": [PartSummary.from_row(row).model_dump() for row in rows],
                "count": len(rows)}

    @r.get("/search")
    def search(
        request: Request,
        q: str = "",
        category: str | None = None,
        complete_only: bool = False,
        spec: list[str] = Query(default=[]),
    ) -> dict:
        """RICH search rows for the modular results table: the same index scope + spec filter as
        /parts, but each surviving row is joined to its loaded record so the row carries the part's
        spec bag and a flattened sourcing summary (stock, unit price). The table picks its columns
        from those specs on the frontend, so the endpoint never hardcodes a per-category column
        set. Bounded like the facets endpoint (the parametric rail is category-scoped), so loading a
        record per result row is affordable."""
        from stockroom.store.parametric import matches_spec_filters, parse_spec_filters

        ctx = request.app.state.ctx
        rows = ctx.index.search(query=q, category=category, complete_only=complete_only)
        constraints = parse_spec_filters(spec)
        out = []
        for row in rows:
            record = ctx.ops.load_record(row.id)
            if constraints and not matches_spec_filters(record, constraints):
                continue
            out.append(SearchRow.from_row_and_record(row, record).model_dump())
        return {"parts": out, "count": len(out)}

    @r.get("/facets")
    def facets(request: Request) -> dict:
        ctx = request.app.state.ctx
        return FacetsDTO.from_facets(ctx.index.facets()).model_dump()

    @r.get("/facets/parametric")
    def parametric_facets(
        request: Request,
        category: str | None = None,
        q: str = "",
        complete_only: bool = False,
        spec: list[str] = Query(default=[]),
    ) -> dict:
        """Facets GENERATED from the parts' free-form spec bags (never a hardcoded
        parameter list) for the modular Mouser-style search. Each spec key present across
        the (optionally category/query/complete-scoped) parts becomes one facet: a
        mostly-numeric key -> a range (min/max, unit), any other -> the top-N distinct
        values with counts. The live rail selections (``spec``, same tokens as /parts) are
        applied so the counts narrow as the user picks - each facet excludes its OWN key so it
        still offers its other values. A category that grows a brand-new spec key surfaces it
        with zero code change. Scoping reuses the derived index; specs load from the records."""
        from stockroom.store.parametric import aggregate_parametric, parse_spec_filters

        ctx = request.app.state.ctx
        rows = ctx.index.search(query=q, category=category, complete_only=complete_only)
        records = (ctx.ops.load_record(row.id) for row in rows)
        agg = aggregate_parametric(records, category=category, constraints=parse_spec_filters(spec))
        return ParametricFacetsDTO.from_aggregate(agg).model_dump()

    @r.post("/bom-match")
    def bom_match(request: Request, body: dict) -> dict:
        """Match a pasted BOM (an MPN list or a BOM CSV) against the library: per
        line, the part that already exists (and whether it is complete) or an
        honest miss. Pure index reads, so it is synchronous and offline."""
        from stockroom.enrich.bulk import parse_bom_csv, parse_mpn_list

        ctx = request.app.state.ctx
        mpns = parse_bom_csv(body["csv"]) if "csv" in body else parse_mpn_list(body.get("text", ""))
        items = []
        in_library = 0
        for mpn in mpns:
            rows = ctx.index.find_by_mpn(mpn)
            if rows:
                in_library += 1
                row = rows[0]
                items.append({
                    "mpn": mpn, "part_id": row.id, "display_name": row.display_name,
                    "is_complete": row.is_complete, "missing": list(row.missing),
                    "matches": len(rows),
                })
            else:
                items.append({
                    "mpn": mpn, "part_id": None, "display_name": "",
                    "is_complete": False, "missing": [], "matches": 0,
                })
        return {"items": items, "in_library": in_library, "total": len(items)}

    def _build_passive(body: dict):
        """Build a passive from the request body. Manual kind/package/value/tolerance
        (the pick-your-package fallback for an MPN no decoder knows) are passed
        through; a genuinely bad input raises PassiveAddError (-> 422) and an
        undecodable MPN with no manual pick raises PassiveNeedsInputError, which the
        preview surfaces as a needs_input status and the add rejects as 422."""
        return build_passive_record(
            body.get("input", ""),
            kind=(body.get("kind") or None),
            package=(body.get("package") or None),
            value=(body.get("value") or None),
            tolerance=(body.get("tolerance") or None),
            category=(body.get("category") or None),
            manufacturer=(body.get("manufacturer") or None),
            datasheet_url=(body.get("datasheet_url") or None),
            purchase_part_number=(body.get("purchase_part_number") or None),
            specs=(body.get("specs") or None),
            price_breaks=(body.get("price_breaks") or None),
            stock=body.get("stock"),
        )

    @r.post("/passive/preview")
    def passive_preview(request: Request, body: dict) -> dict:
        """Preview a file-less passive add from an MPN or a Mouser URL WITHOUT
        committing. When the MPN decodes (or the manual pickers are filled) the body
        is {status: "ok", record, gaps, stock_present}. When the MPN cannot be decoded
        and no kind/package was picked, the body is {status: "needs_input", ...} with
        the cleaned MPN, any manufacturer read from the URL, a best-effort kind guess,
        and the package options - the signal for the UI to reveal the pickers, not an
        error. Offline and synchronous."""
        try:
            build = _build_passive(body)
        except PassiveNeedsInputError as exc:
            return {
                "status": "needs_input",
                "mpn": exc.mpn,
                "manufacturer": exc.manufacturer,
                "suggested_kind": exc.suggested_kind,
                "packages": exc.packages,
                "message": str(exc),
            }
        except PassiveAddError as exc:
            # A genuinely bad input (empty, non-Mouser URL) is the caller's problem.
            raise ApiError(422, str(exc)) from exc
        return {
            "status": "ok",
            "record": build.record.to_dict(),
            "gaps": build.gaps,
            "stock_present": build.stock_present,
        }

    @r.post("/passive")
    def passive_add(request: Request, body: dict) -> dict:
        """Add a passive with NO dropped files: build the record (KiCad stock symbol/
        footprint/3D references) and commit it through the complete-to-add gate, then
        rebuild the index and auto-push. 422 if the input is not addable (undecodable
        with no manual pick, bad input) or the passport is incomplete (missing
        datasheet/manufacturer/purchase)."""
        ctx = request.app.state.ctx
        try:
            build = _build_passive(body)
        except (PassiveNeedsInputError, PassiveAddError) as exc:
            raise ApiError(422, str(exc)) from exc
        record = ctx.ops.add_passive_part(build.record)  # IncompleteError -> 422
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return record.to_dict()

    @r.get("/parts/{part_id}")
    def part_detail(request: Request, part_id: str) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        return ctx.ops.load_record(part_id).to_dict()

    @r.patch("/parts/{part_id}")
    def edit_field(request: Request, part_id: str, body: EditFieldBody) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.edit_field(part_id, body.field, body.value)
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return rec.to_dict()

    @r.post("/parts/{part_id}/specs")
    def set_specs(request: Request, part_id: str, body: SetSpecsBody) -> dict:
        # Persist canonical spec data (e.g. an enriched pinout) onto the record so a
        # viewer reads the source of truth. The typed body means a malformed specs
        # container is a 422, not an opaque 500. Specs are not indexed, but the record
        # write goes through the same rebuild path as every other mutation.
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.set_specs(part_id, body.specs, overwrite=body.overwrite)
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return rec.to_dict()

    @r.post("/parts/{part_id}/refresh")
    def refresh_part(request: Request, part_id: str) -> dict:
        """Refresh one part's volatile procurement data (price/stock/lifecycle/lead/dist P/N) from
        the free distributor APIs (Mouser + DigiKey) - the API lane, no anti-bot. A write-lane
        background job (spec section 8): the record is committed through a git Transaction, so it
        runs on the serialized write pool. The terminal `result` event carries the updated record."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")

        def work(progress):
            from datetime import datetime, timezone

            from stockroom.enrich.refresh import refresh_via_adapters

            record = ctx.ops.load_record(part_id)
            progress({"pct": 10, "message": f"querying distributor APIs for {record.mpn}"})
            per_vendor = refresh_via_adapters(record.mpn, build_refresh_adapters(ctx))
            now_iso = datetime.now(timezone.utc).isoformat()
            updated = ctx.ops.refresh_procurement(part_id, per_vendor, now_iso)
            ctx.rebuild_index()
            ctx.auto_push()
            return updated.to_dict()

        return {"job_id": ctx.jobs.submit(work, write=True)}

    @r.get("/parts/{part_id}/cad-source")
    def part_cad_source(request: Request, part_id: str) -> dict:
        ctx = request.app.state.ctx
        row = ctx.index.get(part_id)
        if row is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        from stockroom.capture.requirements import capture_needs

        record = ctx.ops.load_record(part_id)
        needs = [req.value for req in capture_needs(record)]
        # Primary source: an Ultra Librarian / SnapEDA page (both KiCad + Altium
        # downloads behind a real control the guided window can click). Which one is picked from
        # the user's saved vendor login (SnapEDA if that is the only one set, else Ultra Librarian).
        from stockroom.enrich.asset_source import resolve_asset_page

        page = resolve_asset_page(record.mpn, vendor=_preferred_cad_vendor(ctx.config))
        if page is not None:
            return {"url": page.url, "mpn": record.mpn, "vendor": page.vendor, "needs": needs}
        # Fallback: open the DigiKey product page.
        from stockroom.enrich.cad_source import resolve_digikey_cad_source

        digikey = next((a for a in build_refresh_adapters(ctx)
                        if getattr(a, "vendor", "") == "DigiKey"), None)
        url = resolve_digikey_cad_source(record.mpn, digikey) if digikey is not None else None
        return {"url": url, "mpn": record.mpn, "vendor": "DigiKey", "needs": needs}

    @r.post("/rescan")
    def rescan_library(request: Request, force: bool = False) -> dict:
        ctx = request.app.state.ctx

        def work(progress):
            from stockroom.enrich.rescan import RescanEngine

            # the endpoint builds the adapters (via the patchable build_refresh_adapters) and
            # INJECTS them, so the engine has no api dependency.
            return RescanEngine(ctx, adapters=build_refresh_adapters(ctx)).run(progress, force=force)

        # Single-flight: check-and-submit happens under one lock so two concurrent POSTs can
        # never both submit a rescan job.
        with _rescan_lock:
            existing = getattr(request.app.state, "rescan_job_id", "")
            if existing:
                try:
                    job = ctx.jobs.get(existing)
                except KeyError:
                    job = None
                if job is not None and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    return {"job_id": existing, "already_running": True}
            # READ lane: the engine is network-I/O-bound and self-serializes its commits via
            # run_write, so it must NOT occupy the single write worker for the whole run.
            job_id = ctx.jobs.submit(work, write=False)
            request.app.state.rescan_job_id = job_id
            return {"job_id": job_id}

    @r.get("/rescan/state")
    def rescan_state(request: Request) -> dict:
        ctx = request.app.state.ctx
        from stockroom.enrich.rescan_state import RescanState

        parts = RescanState(ctx.enrich_cache_dir / "rescan-state.json").entries()
        counts: dict[str, int] = {}
        for entry in parts.values():
            counts[entry.get("outcome", "")] = counts.get(entry.get("outcome", ""), 0) + 1
        return {"parts": parts, "counts": counts}

    @r.post("/parts/{part_id}/symbol")
    def attach_symbol(request: Request, part_id: str, body: dict) -> dict:
        """Attach (or repoint) a symbol REFERENCE on an existing part, tagged with its EDA
        tool ("kicad" default; "altium" later). Reference-only (a lib_id, no file copied) -
        the "attach an asset after adding the part" path. 422 if lib/name is missing."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        lib, name = (body.get("lib") or "").strip(), (body.get("name") or "").strip()
        if not name:
            raise ApiError(422, "a symbol reference needs a name")
        rec = ctx.ops.attach_symbol(part_id, lib, name, tool=(body.get("tool") or "kicad").strip())
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return rec.to_dict()

    @r.post("/parts/{part_id}/footprint")
    def attach_footprint(request: Request, part_id: str, body: dict) -> dict:
        """Attach (or repoint) a footprint REFERENCE on an existing part, tagged with its EDA
        tool. Reference-only (lib_id, no file copied). 422 if lib/name is missing."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        lib, name = (body.get("lib") or "").strip(), (body.get("name") or "").strip()
        if not name:
            raise ApiError(422, "a footprint reference needs a name")
        rec = ctx.ops.attach_footprint(part_id, lib, name, tool=(body.get("tool") or "kicad").strip())
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return rec.to_dict()

    @r.get("/parts/{part_id}/history")
    def part_history(request: Request, part_id: str) -> dict:
        # The per-part timeline: every commit that touched this part's canonical JSON,
        # newest first. The JSON is a stable path across the part's whole life (category
        # is a field, not a directory), so it is the correct, noise-free anchor. Read
        # straight from git; an uncommitted part honestly reports an empty timeline.
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        commits = ctx.repo.log_paths([_part_json_path(ctx, part_id)], max_count=_HISTORY_MAX)
        return {
            "commits": [
                {"sha": c.sha, "subject": c.subject, "author": c.author, "iso_date": c.iso_date}
                for c in commits
            ],
            "count": len(commits),
        }

    @r.get("/parts/{part_id}/diff")
    def part_diff(request: Request, part_id: str, b: str, a: str = "") -> dict:
        # A structured field-level diff of the part's JSON between two revisions, read
        # from git blobs with no checkout, plus which asset kinds changed so the UI can
        # offer an old/new SVG overlay. `a` empty means the earliest side (the part did
        # not exist), so a first commit reads as every field added. Both revs must lie
        # in this part's own history (a 400, never a blind blob read of an arbitrary rev).
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        known = {
            c.sha
            for c in ctx.repo.log_paths([_part_json_path(ctx, part_id)], max_count=_HISTORY_MAX)
        }
        if b not in known:
            raise ValueError(f"unknown revision for this part: {b}")
        if a and a not in known:
            raise ValueError(f"unknown revision for this part: {a}")
        before = _record_at(ctx, a, part_id)
        after = _record_at(ctx, b, part_id)
        fields = [c.to_dict() for c in field_diff(before, after)]
        assets = {
            "symbol": _symbol_node_at(ctx, a, before) != _symbol_node_at(ctx, b, after),
            "footprint": _footprint_text_at(ctx, a, before) != _footprint_text_at(ctx, b, after),
            "model": any(f["key"].startswith("model.") for f in fields),
            "datasheet": any(f["key"].startswith("datasheet.") for f in fields),
        }
        return {"a": a, "b": b, "fields": fields, "assets": assets}

    @r.post("/parts/{part_id}/move")
    def move_category(request: Request, part_id: str, body: MoveBody) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.move_category(part_id, body.category)
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return rec.to_dict()

    @r.delete("/parts/{part_id}", status_code=204)
    def delete_part(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        ctx.ops.delete_part(part_id)
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return Response(status_code=204)

    return r
