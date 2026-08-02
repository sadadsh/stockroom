"""Read surface over the derived index plus full detail from the source JSON.
Every list/search/facet read is served from the SQLite index for instant response
at thousands of parts (spec section 2.2); part detail loads the canonical record."""

from __future__ import annotations

import json
import re
import threading
from types import MappingProxyType

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
from stockroom.model.part import PartRecord
from stockroom.model.part_id import is_valid_part_id
from stockroom.verify.record_diff import extract_symbol_node, field_diff
from stockroom.workflow import IntakeIdentity

# How deep the per-part timeline reads. A part rarely accrues this many commits;
# the same cap governs history and the diff rev-validation so the two agree on what
# is reachable.
_HISTORY_MAX = 100
_AUTOMATIC_CAPTURE_INSTRUCTION = (
    "Stockroom checks retained evidence and automatic sources first. If a provider needs "
    "you, Stockroom opens the exact result inside the app, chooses the required formats, and "
    "names any remaining files. Clear a provider security check only if one appears, then start "
    "the offered downloads or select files you already downloaded; Stockroom intercepts, "
    "validates, and attaches only a complete coherent set."
)
_COMPLETION_MAX_BATCH = 1000
_COMPLETION_BODY_FIELDS = frozenset({"part_ids", "limit", "idempotency_key"})
_CAPTURE_BODY_FIELDS = frozenset(
    {"part_ids", "limit", "idempotency_key", "mode", "vendor", "background"}
)
_CAPTURE_MODES = frozenset({"automatic", "assisted", "finish-first", "collect-all"})
_CAPTURE_REQUIREMENTS = frozenset(
    {
        "kicad_symbol",
        "kicad_footprint",
        "kicad_model",
        "altium_symbol",
        "altium_footprint",
    }
)
_OPAQUE_WORKFLOW_REFERENCE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z",
    re.ASCII,
)
# One durable batch may hold a thousand parts, and every group below is a LIST of rows rather
# than a count, so each group is bounded and reports its own true total beside it. A surface can
# then say "12 of 340" honestly instead of receiving a response sized by the library.
_WORKLIST_MAX_ROWS = 200


def _completion_request(
    request: Request,
    body: dict | None,
) -> tuple[list[str] | None, int, str | None]:
    """Validate the completion command without coercing caller mistakes."""

    payload = {} if body is None else body
    unexpected = sorted(str(key) for key in payload if key not in _COMPLETION_BODY_FIELDS)
    if unexpected:
        raise ValueError("unknown completion fields: " + ", ".join(unexpected))

    raw_part_ids = payload.get("part_ids")
    if raw_part_ids is None:
        part_ids = None
    elif type(raw_part_ids) is not list or not raw_part_ids:
        raise ValueError("part_ids must be a non-empty list of part identifiers")
    else:
        part_ids = []
        for raw_part_id in raw_part_ids:
            if type(raw_part_id) is not str or raw_part_id != raw_part_id.strip():
                raise ValueError("part_ids must contain exact non-empty strings")
            if not is_valid_part_id(raw_part_id):
                raise ValueError(f"invalid part identifier: {raw_part_id!r}")
            part_ids.append(raw_part_id)
        if len(part_ids) > _COMPLETION_MAX_BATCH:
            raise ValueError(f"part_ids must contain at most {_COMPLETION_MAX_BATCH} identifiers")
        if len(set(part_ids)) != len(part_ids):
            raise ValueError("part_ids must not contain duplicates")

    raw_limit = payload.get("limit")
    if raw_limit is None:
        limit = _COMPLETION_MAX_BATCH
    elif type(raw_limit) is not int or not 1 <= raw_limit <= _COMPLETION_MAX_BATCH:
        raise ValueError(f"limit must be an integer between 1 and {_COMPLETION_MAX_BATCH}")
    else:
        limit = raw_limit

    body_key = payload.get("idempotency_key")
    if body_key is not None and (type(body_key) is not str or not body_key.strip()):
        raise ValueError("idempotency_key must be a non-empty string")
    header_key = request.headers.get("Idempotency-Key")
    if header_key is not None and not header_key.strip():
        raise ValueError("Idempotency-Key must not be blank")
    if body_key is not None and header_key is not None and body_key != header_key:
        raise ValueError("body and header idempotency keys must match")
    idempotency_key = header_key if header_key is not None else body_key
    return part_ids, limit, idempotency_key


def _current_completion_record(ctx, part_id: str) -> PartRecord:
    """Load one exact current source record after the path-safe ID gate."""

    path = ctx.profile.library.parts_dir / f"{part_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no such part: {part_id}")
    try:
        record = ctx.ops.load_record(part_id)
    except FileNotFoundError:
        raise FileNotFoundError(f"no such part: {part_id}") from None
    if record.id != part_id:
        raise ApiError(
            409,
            f"Part file {part_id!r} declares a different record id {record.id!r}.",
        )
    return record


def _completion_evidence_store():
    """The machine-local immutable evidence authority shared by completion reads."""

    from stockroom.capture.runner import capture_state_root
    from stockroom.evidence import EvidenceStore

    return EvidenceStore((capture_state_root() / "Evidence").resolve())


def _needs_durable_completion(record: PartRecord, *, evidence_store=None) -> bool:
    from stockroom.capture.verified_cache import record_completion_evidence

    evidence = record_completion_evidence(
        evidence_store or _completion_evidence_store(),
        record,
    )
    return (
        bool(record.missing_fields())
        or any(record.missing_assets_by_tool().values())
        or evidence.state == "unverified"
    )


def _durable_completion_records(
    ctx,
    part_ids: list[str] | None,
    limit: int,
) -> list[PartRecord]:
    """Resolve the exact bounded intake from current canonical JSON records."""

    if part_ids is not None:
        # Validate every requested ID before applying a preview limit.  A typo
        # outside the selected prefix must not be hidden by silent truncation.
        requested = [_current_completion_record(ctx, part_id) for part_id in part_ids]
        return requested[:limit]

    records: list[PartRecord] = []
    evidence_store = _completion_evidence_store()
    for path in sorted(ctx.profile.library.parts_dir.glob("*.json")):
        part_id = path.stem
        if not is_valid_part_id(part_id):
            raise ApiError(409, f"Part file has an invalid identifier: {part_id!r}.")
        record = _current_completion_record(ctx, part_id)
        if not _needs_durable_completion(record, evidence_store=evidence_store):
            continue
        records.append(record)
        if len(records) == limit:
            break
    return records


def _completion_identities(records: list[PartRecord]) -> list[IntakeIdentity]:
    identities: list[IntakeIdentity] = []
    for record in records:
        if not record.mpn.strip():
            raise ApiError(
                422,
                f"Part {record.id!r} needs an MPN before durable completion can start.",
            )
        identities.append(
            IntakeIdentity(
                manufacturer=record.manufacturer,
                mpn=record.mpn,
                payload=MappingProxyType({"part_id": record.id}),
            )
        )
    return identities


def _capture_command(
    request: Request,
    body: dict | None,
) -> tuple[list[str] | None, int, bool, str, str | None, bool, str | None]:
    """Validate the guided-capture command without permissive coercion."""

    payload = {} if body is None else body
    unexpected = sorted(str(key) for key in payload if key not in _CAPTURE_BODY_FIELDS)
    if unexpected:
        raise ValueError("unknown capture fields: " + ", ".join(unexpected))

    raw_part_ids = payload.get("part_ids")
    if raw_part_ids is None:
        part_ids = None
    elif type(raw_part_ids) is not list or not raw_part_ids:
        raise ValueError("part_ids must be a non-empty list of part identifiers")
    else:
        part_ids = []
        for raw_part_id in raw_part_ids:
            if (
                type(raw_part_id) is not str
                or raw_part_id != raw_part_id.strip()
                or not is_valid_part_id(raw_part_id)
            ):
                raise ValueError("part_ids must contain exact canonical part identifiers")
            part_ids.append(raw_part_id)
        if len(part_ids) > _COMPLETION_MAX_BATCH:
            raise ValueError(f"part_ids must contain at most {_COMPLETION_MAX_BATCH} identifiers")
        if len(set(part_ids)) != len(part_ids):
            raise ValueError("part_ids must not contain duplicates")

    limit_supplied = payload.get("limit") is not None
    raw_limit = payload.get("limit")
    if raw_limit is None:
        limit = _COMPLETION_MAX_BATCH
    elif type(raw_limit) is not int or not 1 <= raw_limit <= _COMPLETION_MAX_BATCH:
        raise ValueError(f"limit must be an integer between 1 and {_COMPLETION_MAX_BATCH}")
    else:
        limit = raw_limit

    mode = payload.get("mode", "automatic")
    if mode not in _CAPTURE_MODES:
        raise ValueError(
            "capture mode must be 'automatic', 'assisted', 'finish-first', or 'collect-all'"
        )
    background = payload.get("background", False)
    if type(background) is not bool:
        raise ValueError("background must be a boolean")

    requested_vendor = payload.get("vendor")
    vendor = (
        requested_vendor.strip().lower()
        if isinstance(requested_vendor, str) and requested_vendor.strip()
        else None
    )
    if requested_vendor is not None and vendor is None:
        raise ValueError("vendor must be a non-empty provider key")

    body_key = payload.get("idempotency_key")
    if body_key is not None and (type(body_key) is not str or not body_key.strip()):
        raise ValueError("idempotency_key must be a non-empty string")
    header_key = request.headers.get("Idempotency-Key")
    if header_key is not None and not header_key.strip():
        raise ValueError("Idempotency-Key must not be blank")
    if body_key is not None and header_key is not None and body_key != header_key:
        raise ValueError("body and header idempotency keys must match")
    return (
        part_ids,
        limit,
        limit_supplied,
        mode,
        vendor,
        background,
        header_key if header_key is not None else body_key,
    )


def _capture_identities(
    records: list[PartRecord],
    *,
    mode: str,
    vendor: str | None,
    background: bool,
) -> list[IntakeIdentity]:
    from stockroom.capture.complete import completion_needs
    from stockroom.capture.verified_cache import record_completion_evidence

    evidence_store = _completion_evidence_store()
    identities: list[IntakeIdentity] = []
    for record in records:
        if not record.mpn.strip():
            raise ApiError(
                422,
                f"Part {record.id!r} needs an MPN before durable capture can start.",
            )
        evidence = record_completion_evidence(evidence_store, record)
        identities.append(
            IntakeIdentity(
                manufacturer=record.manufacturer,
                mpn=record.mpn,
                payload=MappingProxyType(
                    {
                        "part_id": record.id,
                        "workflow_kind": "guided_capture",
                        "capture": {
                            "mode": mode,
                            "vendor": vendor,
                            "background": background,
                            "initial_needs": [
                                requirement.value
                                for requirement in completion_needs(record, evidence)
                            ],
                        },
                    }
                ),
            )
        )
    return identities


def _capture_item_projection(item) -> dict:
    payload = item.payload
    if not isinstance(payload, dict) or payload.get("workflow_kind") != "guided_capture":
        raise ApiError(404, "No guided capture owns this workflow batch.")
    part_id = payload.get("part_id")
    capture = payload.get("capture")
    if type(part_id) is not str or not is_valid_part_id(part_id) or not isinstance(capture, dict):
        raise ApiError(409, "The durable capture request is corrupt.")
    mode = capture.get("mode")
    vendor = capture.get("vendor")
    background = capture.get("background")
    initial_needs = capture.get("initial_needs")
    if (
        mode not in _CAPTURE_MODES
        or (vendor is not None and type(vendor) is not str)
        or type(background) is not bool
        or type(initial_needs) is not list
        or any(
            type(requirement) is not str or requirement not in _CAPTURE_REQUIREMENTS
            for requirement in initial_needs
        )
    ):
        raise ApiError(409, "The durable capture request is corrupt.")
    return {
        "workflow_item_id": item.id,
        "part_id": part_id,
        "mode": mode,
        "vendor": vendor,
        "background": background,
        "initial_needs": initial_needs,
    }


def _worklist_text(value: object) -> str:
    """Exactly the string a report carried, or nothing. Never a coerced repr."""

    return value if type(value) is str else ""


def _worklist_requirements(value: object) -> list[str]:
    """The requirement keys a report row named, filtered to the ones this API speaks."""

    if type(value) is not list:
        return []
    return [
        requirement
        for requirement in value
        if type(requirement) is str and requirement in _CAPTURE_REQUIREMENTS
    ]


def _reported_completion_row(report: object, part_id: str) -> dict | None:
    """The one completion row a retained durable report holds for this exact part.

    The report is produced by a ONE-part run inside copy-on-write staging, whose record id is
    derived from the canonical MPN and can therefore differ from the library id. Match the id
    first, and fall back to a single-row report rather than dropping a result that plainly
    belongs to this item.
    """

    if not isinstance(report, dict):
        return None
    rows = report.get("items")
    if type(rows) is not list:
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    for row in rows:
        if row.get("part_id") == part_id:
            return row
    return rows[0] if len(rows) == 1 else None


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
    # Parse through PartRecord: a blob from git history may predate the per-EDA cutover, and
    # from_dict folds those legacy flat fields into the per-tool map. Reading rec["symbol"]
    # here returns None for EVERY post-cutover record, so the timeline would silently report
    # "no symbol change" forever -- no error, just a permanently wrong answer.
    parsed = PartRecord.from_dict(rec)
    sym = parsed.assets_for("kicad").symbol
    name, category = (sym.name if sym else None), parsed.category
    if not name or not category:
        return None
    text = ctx.repo.show_file(rev, ctx.profile.library.symbol_lib_path(category))
    return extract_symbol_node(text, name) if text else None


def _footprint_text_at(ctx, rev: str, rec: dict | None) -> str | None:
    """This part's footprint file text at `rev` (footprints are per-part files, so no
    isolation is needed), or None when absent."""
    if not rec or not rev:
        return None
    parsed = PartRecord.from_dict(rec)
    fp = parsed.assets_for("kicad").footprint
    name, category = (fp.name if fp else None), parsed.category
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
    api_fallback = (
        MouserAdapter(api_key=ctx.config.mouser_api_key) if ctx.config.mouser_api_key else None
    )
    if api_fallback is not None:
        setattr(api_fallback, "vendor", "Mouser")
    mouser = MouserScrapeAdapter(
        getattr(ctx, "rendered_dom_fetcher", None),
        url_for=_mouser_link_resolver(ctx),
        api_fallback=api_fallback,
    )
    mouser.vendor = "Mouser"
    if mouser.enabled:  # the crawler (fetcher + Camoufox) OR the API fallback is available
        adapters.append(mouser)
    if getattr(ctx.config, "digikey_client_id", "") and getattr(
        ctx.config, "digikey_client_secret", ""
    ):
        from stockroom.enrich.digikey_api import DigiKeyAdapter

        a = DigiKeyAdapter(ctx.config.digikey_client_id, ctx.config.digikey_client_secret)
        setattr(a, "vendor", "DigiKey")
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
                row
                for row in rows
                if matches_spec_filters(ctx.ops.load_record(row.id), constraints)
            ]
        return {
            "parts": [PartSummary.from_row(row).model_dump() for row in rows],
            "count": len(rows),
        }

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
            catalog=(body.get("catalog") or None),
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
        from stockroom.capture.complete import completion_needs
        from stockroom.capture.verified_cache import record_completion_evidence

        record = ctx.ops.load_record(part_id)
        completion_evidence = record_completion_evidence(
            _completion_evidence_store(),
            record,
        )
        needs = [req.value for req in completion_needs(record, completion_evidence)]
        # EVERY vendor the owner named, in their trust order, not just the one that aggregates.
        # Owner, 2026-07-27: *"yes rebuild guided capture, digikey UL snapmagic and samacsys"*.
        # DigiKey leads only because its product page gathers the other three in one place, which
        # is fewer clicks when the part is stocked there; it is flagged `aggregator` so a surface
        # can say so rather than imply a fourth model library. `resolve_cad_sources` percent-encodes
        # the MPN for each vendor, and a part with no MPN resolves to NOTHING rather than to four
        # searches for the empty string.
        from stockroom.enrich.cad_sources import resolve_cad_sources

        digikey = next(
            (a for a in build_refresh_adapters(ctx) if getattr(a, "vendor", "") == "DigiKey"), None
        )
        # If a previous capture for this exact part ended on DigiKey's models page, its link
        # becomes that page - the CAD surface itself, with no search and no scroll. Unknown for a
        # part nobody has opened yet, and then the link is exactly what it was before.
        from stockroom.capture.digikey_models import default_digikey_models_ids

        try:
            models_id = default_digikey_models_ids().get(
                manufacturer=record.manufacturer,
                mpn=record.mpn,
            )
        except Exception:  # noqa: BLE001 - an unreadable hint costs a search, never the response
            models_id = ""
        sources = resolve_cad_sources(
            record.mpn,
            digikey,
            digikey_models_id=models_id,
            digikey_catalog=record.catalog.get("digikey"),
        )
        from stockroom.capture.vendors import all_adapters

        implemented_capture = {
            adapter.capability.key: adapter.capability for adapter in all_adapters()
        }
        # Which providers can finish a part with nobody watching, on THIS machine right now.
        # `capture_available` is true for every implemented adapter, so it cannot tell a surface
        # which one to reach for first; without this a chooser defaults to the head of the trust
        # order, which is the aggregator whose controls stay person-driven.
        from stockroom.capture.runner import _machine_access_allowed

        unattended = {
            key
            for key, capability in implemented_capture.items()
            if capability.browser_access == "machine_allowed"
            and _machine_access_allowed(key, config=ctx.config)
        }
        first = sources[0] if sources else None
        return {
            "mpn": record.mpn,
            "needs": needs,
            "completion_evidence": completion_evidence.to_dict(),
            "sources": [
                {
                    "key": s.key,
                    "label": s.label,
                    "url": s.url,
                    "tools": list(s.tools),
                    "aggregator": s.aggregator,
                    "instruction": (
                        f"{_AUTOMATIC_CAPTURE_INSTRUCTION} {implemented_capture[s.key].instruction}"
                        if s.key in implemented_capture
                        else s.instruction
                    ),
                    "capture_available": s.key in implemented_capture,
                    "unattended_capture": s.key in unattended,
                }
                for s in sources
            ],
            # The first source, flattened. Kept because the capture store opens ONE page and this
            # is the default it opens; it is the same object as `sources[0]`, never a second answer.
            "url": first.url if first else None,
            "vendor": first.label if first else "",
        }

    @r.get("/lfs")
    def get_library_lfs(request: Request) -> dict:
        # Where this library's binary payloads are stored. Read-only and NETWORK-FREE: locking is
        # the only part that needs the remote, and it is probed separately.
        ctx = request.app.state.ctx
        return ctx.ops.lfs_status()

    @r.post("/lfs")
    def adopt_library_lfs(request: Request) -> dict:
        # Route the binary payloads through git-lfs, as ONE hygiene commit that writes the rules
        # AND wires the filter (attributes alone are inert). Does not convert existing history:
        # that needs a rewrite plus a force-push, which this project forbids. A dirty/staged tree
        # or a hand-broken managed block -> 400; git-lfs missing -> 500 with its own reason.
        ctx = request.app.state.ctx
        result = ctx.ops.lfs_adopt()
        ctx.auto_push()
        return result

    @r.get("/hygiene")
    def get_library_hygiene(request: Request) -> dict:
        # What syncing the LIBRARY's workspace hygiene would change. The library holds assets for
        # every registered EDA tool, so it takes the union of their rules. Read-only, no git.
        ctx = request.app.state.ctx
        return ctx.ops.hygiene_read()

    @r.post("/hygiene")
    def sync_library_hygiene(request: Request) -> dict:
        # Write the rules AND untrack the per-user files, as ONE commit on the library repo. Both
        # halves are required: an ignore rule has no effect on a file git already tracks, and a peer
        # cloning the library is exactly who inherits a committed `fp-info-cache`.
        ctx = request.app.state.ctx
        return ctx.ops.hygiene_apply()

    @r.post("/rescan")
    def rescan_library(request: Request, force: bool = False) -> dict:
        ctx = request.app.state.ctx

        def work(progress):
            from stockroom.enrich.rescan import RescanEngine

            # the endpoint builds the adapters (via the patchable build_refresh_adapters) and
            # INJECTS them, so the engine has no api dependency.
            return RescanEngine(ctx, adapters=build_refresh_adapters(ctx)).run(
                progress, force=force
            )

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
    def attach_symbol(_request: Request, part_id: str, _body: dict) -> dict:
        """Reject the retired reference-only, single-tool activation lane."""

        del part_id
        raise ApiError(
            422,
            (
                "single-tool symbol attachment is disabled; use network collection so KiCad, "
                "Altium, and STEP activate atomically from one verified evidence set"
            ),
        )

    @r.post("/parts/{part_id}/footprint")
    def attach_footprint(_request: Request, part_id: str, _body: dict) -> dict:
        """Reject the retired reference-only, single-tool activation lane."""

        del part_id
        raise ApiError(
            422,
            (
                "single-tool footprint attachment is disabled; use network collection so "
                "KiCad, Altium, and STEP activate atomically from one verified evidence set"
            ),
        )

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
            # Any tool's 3D model: the record keys these as `eda.<tool>.model.*`, so this
            # stays correct when a second tool grows its own model slot.
            "model": any(f["key"].startswith("eda.") and ".model." in f["key"] for f in fields),
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

    @r.delete("/parts/{part_id}/assets/{kind}")
    def detach_asset(request: Request, part_id: str, kind: str) -> dict:
        """Remove ONE element from a part (symbol / footprint / model / datasheet /
        altium_symbol / altium_footprint): the file goes, the ref nulls, one scoped
        commit. Unknown id -> 404; a kind the part does not carry -> 400 (loud, never
        a silent no-op)."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        record = ctx.ops.detach_asset(part_id, kind)
        ctx.rebuild_index()
        ctx.auto_push()
        return record.to_dict()

    @r.delete("/parts/{part_id}", status_code=204)
    def delete_part(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        ctx.ops.delete_part(part_id)
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return Response(status_code=204)

    @r.post("/parts/{part_id}/undo-delete")
    def undo_delete_part(request: Request, part_id: str) -> dict:
        """Restore one exact Stockroom deletion through Git's non-destructive revert."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is not None:
            raise ValueError(f"{part_id} already exists; there is no deletion to undo")
        record = ctx.ops.restore_deleted_part(part_id)
        ctx.rebuild_index()
        ctx.auto_push()
        return record.to_dict()

    @r.get("/completion")
    def completion_coverage(request: Request) -> dict:
        """Is my library complete, and what is missing?

        The owner's central question, and until now it lived in a script only Claude could
        run -- which by the owner's own standing rule (*"everything u do manually the app
        should do by itself"*) made it a missing feature rather than a tool. Read-only and
        network-free: it counts the records on disk.
        """
        from stockroom.capture.runner import coverage

        return coverage(request.app.state.ctx)

    @r.post("/completion/run")
    def completion_run(request: Request, body: dict | None = None) -> dict:
        """Submit completion to the durable owner, or use the bounded dev fallback.

        A mounted coordinator is authoritative: this route persists exactly one
        durable intake request and returns before stage execution.  It never
        launches the process-local job runner in that mode.  Standalone source
        development keeps the former cancellable runner, capped to the same
        one-thousand-item batch boundary.
        """
        from stockroom.capture.runner import run_completion

        ctx = request.app.state.ctx
        part_ids, limit, idempotency_key = _completion_request(request, body)
        coordinator = ctx.workflow_coordinator
        if coordinator is not None:
            records = _durable_completion_records(ctx, part_ids, limit)
            if not records:
                raise ApiError(409, "No current parts need completion.")
            batch = coordinator.submit_batch(
                _completion_identities(records),
                idempotency_key=idempotency_key,
            )
            return {
                "workflow_batch_id": batch.id,
                "event_cursor": 0,
            }

        if idempotency_key is not None:
            raise ApiError(
                503,
                "Idempotent completion requires the durable workflow coordinator.",
            )
        if part_ids is not None:
            # The legacy job used to turn an unknown ID into a delayed SSE
            # failure. Resolve all requested IDs now so the command response is
            # deterministic and cannot launch work for a partial bad request.
            for part_id in part_ids:
                _current_completion_record(ctx, part_id)

        def work(progress, should_stop):
            return run_completion(
                ctx,
                progress=progress,
                should_stop=should_stop,
                part_ids=part_ids,
                limit=limit,
            )

        return {"job_id": ctx.jobs.submit_cancellable(work)}

    @r.post("/capture/run")
    def capture_run(request: Request, body: dict | None = None) -> dict:
        """Submit guided capture to the durable owner, with a standalone dev fallback.

        The mounted coordinator owns the whole completion graph: exact identity,
        metadata, datasheet, shared KiCad/Altium/STEP acquisition, validation, and
        atomic publication. The process-local job exists only when source
        development deliberately runs without that authority.
        """
        from stockroom.capture.runner import run_guided_capture
        from stockroom.capture.vendors import get_adapter

        ctx = request.app.state.ctx
        (
            part_ids,
            limit,
            limit_supplied,
            mode,
            vendor,
            background,
            idempotency_key,
        ) = _capture_command(request, body)
        if vendor is not None and get_adapter(vendor) is None:
            raise ValueError(f"no network capture adapter for provider {vendor!r}")

        if mode == "assisted":
            if part_ids is None or len(part_ids) != 1:
                raise ValueError("assisted capture requires exactly one selected part")
            if vendor is None:
                raise ValueError("assisted capture requires one selected provider")
            if limit_supplied:
                raise ValueError(
                    "assisted capture does not accept a batch limit; select exactly one part"
                )
            adapter = get_adapter(vendor)
            if (
                background
                and adapter is not None
                and adapter.capability.browser_access == "user_driven"
            ):
                raise ValueError(
                    f"{adapter.capability.label} requires a visible person-driven provider page"
                )
        if mode in {"finish-first", "collect-all"}:
            if part_ids is None or len(part_ids) != 1:
                raise ValueError(f"{mode} capture requires exactly one selected part")
            if limit_supplied:
                raise ValueError(
                    f"{mode} capture does not accept a batch limit; select exactly one part"
                )
            if background:
                raise ValueError(f"{mode} capture requires visible sequential provider handoffs")
        records = (
            [_current_completion_record(ctx, part_id) for part_id in part_ids]
            if part_ids is not None
            else None
        )
        if mode in {"finish-first", "collect-all"}:
            from stockroom.capture.evidence import exact_identity

            assert records is not None
            try:
                exact_identity(records[0])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{mode} capture requires one exact manufacturer and MPN"
                ) from exc

        coordinator = ctx.workflow_coordinator
        if coordinator is not None:
            selected = (
                records[:limit]
                if records is not None
                else _durable_completion_records(ctx, None, limit)
            )
            if not selected:
                raise ApiError(409, "No current parts need completion.")
            batch = coordinator.submit_batch(
                _capture_identities(
                    selected,
                    mode=mode,
                    vendor=vendor,
                    background=background,
                ),
                idempotency_key=idempotency_key,
            )
            items = coordinator.list_items(batch.id)
            response = {
                "workflow_batch_id": batch.id,
                "event_cursor": 0,
            }
            if len(items) == 1:
                response["workflow_item_id"] = items[0].id
            return response

        if idempotency_key is not None:
            raise ApiError(
                503,
                "Idempotent capture requires the durable workflow coordinator.",
            )

        def work(progress, should_stop):
            return run_guided_capture(
                ctx,
                part_ids=part_ids,
                vendor=vendor,
                progress=progress,
                should_stop=should_stop,
                limit=limit,
                headless=background,
                operator_authorized=mode == "assisted",
                finish_first=mode == "finish-first",
                collect_all=mode == "collect-all",
            )

        return {"job_id": ctx.jobs.submit_cancellable(work)}

    @r.post("/capture/parts/{part_id}/intent")
    def capture_person_intent(part_id: str, body: dict | None = None) -> dict:
        """Record what the PERSON decided about the person-driven capture in front of them.

        De-automation removed the provider HUD, so the Finish and Skip buttons that used to sit on
        the provider page have nowhere to live except Stockroom's own window. This is the route
        those buttons reach: `finish-route` says no more files are coming from the page in front of
        the person, and `skip-part` stops that component's remaining provider routes.

        NOTHING HERE TOUCHES A PROVIDER PAGE. The body is one word describing the person's own
        intent; `capture/intent.py` hands it to the running capture through the same polled
        predicates cancellation already uses.

        A signal naming a component with no running capture is refused rather than remembered,
        because a remembered one would silently end the next run the person started.
        """

        from stockroom.capture.intent import (
            PERSON_CAPTURE_ACTIONS,
            PersonCaptureIntentError,
            signal_person_capture,
        )

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        payload = {} if body is None else body
        expected = {"action", "workflow_item_id"}
        unexpected = sorted(str(key) for key in payload if key not in expected)
        if unexpected:
            raise ValueError("unknown capture intent fields: " + ", ".join(unexpected))
        action = payload.get("action")
        if action not in PERSON_CAPTURE_ACTIONS:
            raise ValueError("action must be 'finish-route' or 'skip-part'")
        workflow_item_id = payload.get("workflow_item_id")
        if (
            type(workflow_item_id) is not str
            or _OPAQUE_WORKFLOW_REFERENCE.fullmatch(workflow_item_id) is None
        ):
            raise ValueError("workflow_item_id must name the exact running capture")
        try:
            signal_person_capture(part_id, action, capture_id=workflow_item_id)
        except PersonCaptureIntentError as exc:
            raise ApiError(409, str(exc)) from exc
        return {
            "part_id": part_id,
            "workflow_item_id": workflow_item_id,
            "action": action,
            "accepted": True,
        }

    @r.post("/capture/parts/{part_id}/selected-files")
    def capture_selected_files(request: Request, part_id: str, body: dict | None = None) -> dict:
        """Queue native-picker files for the exact durable provider task that validates them."""

        from pathlib import Path

        from stockroom.capture.intent import (
            PersonCaptureIntentError,
            queue_person_capture_files,
        )

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        payload = {} if body is None else body
        expected = {
            "paths",
            "vendor",
            "detail_url",
            "route_token",
            "workflow_item_id",
        }
        unexpected = sorted(str(key) for key in payload if key not in expected)
        if unexpected:
            raise ValueError("unknown selected-file fields: " + ", ".join(unexpected))
        workflow_item_id = payload.get("workflow_item_id")
        if (
            type(workflow_item_id) is not str
            or _OPAQUE_WORKFLOW_REFERENCE.fullmatch(workflow_item_id) is None
        ):
            raise ValueError("workflow_item_id must name the exact running capture")
        raw_paths = payload.get("paths")
        if (
            type(raw_paths) is not list
            or not 1 <= len(raw_paths) <= 20
            or any(type(path) is not str or not path.strip() for path in raw_paths)
        ):
            raise ValueError("paths must contain between 1 and 20 selected files")
        try:
            paths = tuple(Path(path).resolve(strict=True) for path in raw_paths)
        except (OSError, RuntimeError) as exc:
            raise ValueError("a selected file is no longer available") from exc
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ValueError("every selected path must be a real file")
        vendor = payload.get("vendor")
        detail_url = payload.get("detail_url")
        route_token = payload.get("route_token")
        if type(vendor) is not str or not vendor.strip():
            raise ValueError("vendor must name the active provider")
        if type(detail_url) is not str or not detail_url.strip():
            raise ValueError("detail_url must name the active exact provider page")
        if type(route_token) is not str or not route_token.strip():
            raise ValueError("route_token must name the exact active provider route")
        try:
            queue_person_capture_files(
                workflow_item_id,
                part_id=part_id,
                vendor=vendor.strip().lower(),
                detail_url=detail_url.strip(),
                route_token=route_token.strip(),
                paths=paths,
            )
        except PersonCaptureIntentError as exc:
            raise ApiError(409, str(exc)) from exc
        return {
            "part_id": part_id,
            "workflow_item_id": workflow_item_id,
            "accepted": True,
            "queued_files": len(paths),
        }

    @r.get("/capture/batches/{batch_id}")
    def capture_batch(request: Request, batch_id: str) -> dict:
        """Project one durable guided-capture request, its handoff guidance, and its report.

        `handoff` carries the ordered required-file checklist and provider instructions shown beside
        the embedded provider surface. Provider security choices remain person-owned while task-
        bound downloads and selected-file recovery remain Stockroom-owned. It is null until the
        running chain names one exact provider route.
        """

        from stockroom.capture.handoff import handoff_guidance
        from stockroom.capture.intent import active_person_capture
        from stockroom.capture.runner import read_durable_capture_report

        if _OPAQUE_WORKFLOW_REFERENCE.fullmatch(batch_id) is None:
            raise ApiError(400, "batch_id is not a valid opaque workflow identifier")
        coordinator = request.app.state.ctx.workflow_coordinator
        if coordinator is None:
            raise ApiError(503, "The durable workflow coordinator is not mounted.")
        coordinator.get_batch(batch_id)
        items = coordinator.list_items(batch_id)
        if len(items) != 1:
            raise ApiError(409, "Guided capture requires one durable workflow item.")
        item = items[0]
        projection = _capture_item_projection(item)
        try:
            report = read_durable_capture_report(item.id)
        except ValueError as exc:
            raise ApiError(409, str(exc)) from exc
        vendor = projection["vendor"]
        handoff = (
            handoff_guidance(
                vendor,
                needs=projection["initial_needs"],
                manufacturer=str(getattr(item, "manufacturer", "") or ""),
                mpn=str(getattr(item, "mpn", "") or ""),
            )
            if vendor
            else None
        )
        return {
            "workflow_batch_id": batch_id,
            **projection,
            "active_route": active_person_capture(
                item.id,
                part_id=projection["part_id"],
            ),
            "handoff": handoff,
            "report": report,
        }

    @r.get("/capture/batches/{batch_id}/worklist")
    def capture_batch_worklist(request: Request, batch_id: str) -> dict:
        """Split one library-wide capture batch into what finished alone and what needs a person.

        The owner wants one button that does everything it is allowed to do. Most of that
        distance is reachable, and this route reports the rest HONESTLY rather than pretending
        the gap does not exist: every `worklist` row is one provider route the run itself
        terminated as `requires-human`, carrying that route's own reason ("no Ultra Librarian
        sign-in is saved...", "does not offer Altium Designer (Native) for this exact part").
        The frontend turns each row into one trip to that provider for that part; it never
        drives the provider page, which is exactly what those terms forbid.

        Nothing here is inferred. A part whose report has not landed is `pending_items`, a
        finished part no route can currently help is `stalled` (a different fact from needing a
        person), and a report this API cannot read is named in `unreadable` rather than silently
        dropped. Read-only: it projects retained machine-local reports and the durable item list.
        """

        from stockroom.capture.complete import sanitize_provider_reason
        from stockroom.capture.runner import read_durable_capture_report

        if _OPAQUE_WORKFLOW_REFERENCE.fullmatch(batch_id) is None:
            raise ApiError(400, "batch_id is not a valid opaque workflow identifier")
        coordinator = request.app.state.ctx.workflow_coordinator
        if coordinator is None:
            raise ApiError(503, "The durable workflow coordinator is not mounted.")
        coordinator.get_batch(batch_id)
        items = coordinator.list_items(batch_id)
        unattended: list[dict] = []
        stalled: list[dict] = []
        worklist: list[dict] = []
        unreadable: list[str] = []
        unattended_total = 0
        stalled_total = 0
        worklist_total = 0
        pending = 0
        for item in items:
            projection = _capture_item_projection(item)
            part_id = projection["part_id"]
            try:
                report = read_durable_capture_report(item.id)
            except ValueError:
                unreadable.append(part_id)
                continue
            if report is None:
                pending += 1
                continue
            row = _reported_completion_row(report, part_id)
            if row is None:
                unreadable.append(part_id)
                continue
            mpn = _worklist_text(row.get("mpn"))
            display_name = _worklist_text(row.get("display_name"))
            status = _worklist_text(row.get("status"))
            raw_remaining = row.get("remaining")
            # An EMPTY `remaining` is a real answer, so it is never widened back to the needs the
            # item started with; only a missing list falls back to what the request recorded.
            remaining = (
                _worklist_requirements(raw_remaining)
                if type(raw_remaining) is list
                else list(projection["initial_needs"])
            )
            outcomes = row.get("provider_outcomes")
            human_routes: list[dict] = []
            for outcome in outcomes if type(outcomes) is list else []:
                if not isinstance(outcome, dict) or outcome.get("status") != "requires-human":
                    continue
                provider_key = _worklist_text(outcome.get("provider_key"))
                route_id = _worklist_text(outcome.get("route_id"))
                if not provider_key or not route_id:
                    continue
                human_routes.append(
                    {
                        "part_id": part_id,
                        "mpn": mpn,
                        "display_name": display_name,
                        "route_id": route_id,
                        "provider_key": provider_key,
                        "label": _worklist_text(outcome.get("label")) or provider_key,
                        "status": "requires-human",
                        # Re-sanitized on the way out. It was sanitized when the outcome was
                        # built, and a retained file is still a file: a bounded, single-line,
                        # secret-free reason is a property of this response, not of its input.
                        "reason": sanitize_provider_reason(outcome.get("reason")),
                        "remaining": remaining,
                    }
                )
            if human_routes:
                # Get Files is component-scoped and exhausts every eligible route. One row per
                # provider would make the same part run repeatedly and mark every sibling row as
                # active at once. Keep one actionable component row and summarize its additional
                # person-owned routes inside that row.
                primary = human_routes[0]
                if len(human_routes) > 1:
                    combined_label = " + ".join(
                        dict.fromkeys(route["label"] for route in human_routes)
                    )
                    combined_reason = sanitize_provider_reason(
                        "; ".join(
                            f"{route['label']}: {route['reason']}" for route in human_routes
                        )
                    )
                    primary["label"] = combined_label
                    primary["reason"] = combined_reason
                worklist_total += 1
                if len(worklist) < _WORKLIST_MAX_ROWS:
                    worklist.append(primary)
                continue
            if status in {"completed", "already-complete"}:
                unattended_total += 1
                if len(unattended) < _WORKLIST_MAX_ROWS:
                    unattended.append(
                        {
                            "part_id": part_id,
                            "mpn": mpn,
                            "display_name": display_name,
                            "status": status,
                            "remaining": remaining,
                        }
                    )
                continue
            notes = row.get("notes")
            stalled_total += 1
            if len(stalled) < _WORKLIST_MAX_ROWS:
                stalled.append(
                    {
                        "part_id": part_id,
                        "mpn": mpn,
                        "display_name": display_name,
                        "status": status,
                        "reason": sanitize_provider_reason(
                            _worklist_text(row.get("error"))
                            or "; ".join(
                                _worklist_text(note)
                                for note in (notes if type(notes) is list else [])
                                if _worklist_text(note)
                            )
                        ),
                        "remaining": remaining,
                    }
                )
        return {
            "workflow_batch_id": batch_id,
            "total_items": len(items),
            "pending_items": pending,
            "worklist": worklist,
            # Added so a rolling frontend can distinguish this component-scoped projection from
            # older releases whose identical field names counted provider routes.
            "worklist_unit": "components",
            "worklist_total": worklist_total,
            "unattended": unattended,
            "unattended_total": unattended_total,
            "stalled": stalled,
            "stalled_total": stalled_total,
            "unreadable": unreadable,
        }

    @r.get("/capture/vendors")
    def capture_vendors() -> dict:
        """Providers Stockroom can drive and safely capture downloads from.

        Driven off the adapter registry rather than a hand-kept list, so a surface can never offer
        a provider that has no capture/evidence implementation behind it.
        """
        from stockroom.capture.vendors import all_adapters

        return {
            "vendors": [
                {
                    "key": a.capability.key,
                    "label": a.capability.label,
                    "tools": list(a.capability.tools),
                    "needs_login": a.capability.needs_login,
                    "aggregator": a.capability.aggregator,
                    "instruction": (f"{_AUTOMATIC_CAPTURE_INSTRUCTION} {a.capability.instruction}"),
                    "one_download_for_all_formats": not a.capability.formats_exclusive,
                }
                for a in all_adapters()
            ]
        }

    @r.get("/cad")
    def cad_inventory(request: Request) -> dict:
        """What CAD this library holds, and how much of it this app could remove.

        Read-only. `dry_run` on the clear route answers the same question by doing the real walk,
        and this exists so the surface can state the number BEFORE offering a destructive action
        rather than after.
        """
        return request.app.state.ctx.ops.clear_cad_assets(dry_run=True)

    @r.post("/cad/clear")
    def cad_clear(request: Request, body: dict | None = None) -> dict:
        """Remove every CAD asset this library holds, files and references, in ONE commit.

        Owner, 2026-07-27: *"remove all the current cad files before guided capture"* -- the point
        is to start the trusted-capture pass from nothing, because what is there came from sources
        they have since ruled out.

        DESTRUCTIVE, so: `dry_run` defaults to TRUE. A caller has to ask for the write explicitly,
        and the dry run returns the identical report. KiCad-stock references (`Device:R`) are
        counted and LEFT: they name no file this app owns, and clearing them would empty a passive
        permanently.
        """
        ctx = request.app.state.ctx
        dry_run = bool((body or {}).get("dry_run", True))

        def work(progress):
            progress({"pct": 5, "message": "finding the CAD this library holds"})
            report = ctx.ops.clear_cad_assets(dry_run=dry_run)
            if not dry_run and report["cleared"]:
                ctx.rebuild_index()
                ctx.auto_push()
            return report

        return {"job_id": ctx.jobs.submit(work, write=not dry_run)}

    @r.get("/derivation")
    def derivation(request: Request) -> dict:
        """Which derivation ruleset this library's parts carry, and how many are behind.

        Read-only, network-free, and answered from the index in one grouped query. The point of
        surfacing it at all: a rules change (a new naming scheme, a cleaned-up description) makes
        every stored derived block stale, and the owner needs to SEE that rather than discover it
        as parts that read differently on two machines.
        """
        from stockroom.mutation.library_ops import derivation_status

        return derivation_status(request.app.state.ctx.index)

    @r.post("/derivation/rebuild")
    def derivation_rebuild(request: Request, body: dict | None = None) -> dict:
        """Recompute every part's derived block from its stored evidence. One atomic commit.

        Credential-free by construction (it reads `sourced/`, never a distributor), so it works
        on a fresh clone that has never been given API keys. `dry_run` reports the same numbers
        and writes nothing -- anything that acts across a whole library gets a dry run first.
        """
        ctx = request.app.state.ctx
        payload = body or {}
        dry_run = bool(payload.get("dry_run"))
        scheme = str(payload.get("scheme") or "")

        def work(progress):
            from datetime import datetime, timezone

            def on_part(done: int, total: int, part_id: str) -> None:
                progress(
                    {
                        "pct": int(done * 100 / total) if total else 100,
                        "message": f"re-deriving {part_id}",
                    }
                )

            report = ctx.ops.rederive_library(
                now_iso=datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                scheme=scheme,
                dry_run=dry_run,
                progress=on_part,
            )
            if not dry_run and report["rewritten"]:
                ctx.rebuild_index()
                ctx.auto_push()
            return report

        return {"job_id": ctx.jobs.submit(work, write=not dry_run)}

    return r
