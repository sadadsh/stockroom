"""Read surface over the derived index plus full detail from the source JSON.
Every list/search/facet read is served from the SQLite index for instant response
at thousands of parts (spec section 2.2); part detail loads the canonical record."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from stockroom.api.errors import ApiError
from stockroom.api.jobs import JobStatus
from stockroom.api.schemas import (
    CadPreferredSourceBody,
    EditFieldBody,
    FacetsDTO,
    MoveBody,
    ParametricFacetsDTO,
    PartSummary,
    PreferredSourceBody,
    ProviderCoverageBody,
    SearchRow,
    SetSpecsBody,
    SpecificationOverrideBody,
)
from stockroom.capture.runner import capture_candidates_root, capture_state_root
from stockroom.dossier import component_dossier
from stockroom.dossier.cad_preference import (
    MixedCadSourceRefused,
    UnknownCadAsset,
    UnofferedCadSource,
)
from stockroom.dossier.decisions import UnknownSpecification, UnpinnableSource
from stockroom.dossier.documents import find_document
from stockroom.evidence import EvidenceStore
from stockroom.ingest.candidates import RetainedCandidateStore
from stockroom.ingest.passive_add import (
    PassiveAddError,
    PassiveNeedsInputError,
    build_passive_record,
)
from stockroom.model.part import PartRecord
from stockroom.model.part_id import is_valid_part_id
from stockroom.mutation.transaction import Transaction
from stockroom.provider_coverage import provider_coverage, set_user_assertion
from stockroom.verify.record_diff import extract_symbol_node, field_diff
from stockroom.workflow import IntakeIdentity

# How deep the per-part timeline reads. A part rarely accrues this many commits;
# the same cap governs history and the diff rev-validation so the two agree on what
# is reachable.
_HISTORY_MAX = 100
_PERSON_DRIVEN_CAPTURE_INSTRUCTION = (
    "Stockroom checks retained evidence first, then opens the exact provider page inside the "
    "app and names every file it needs. You work the provider page - search, sign-in, formats, "
    "licence, security check, and the download itself. Stockroom intercepts, validates, and "
    "attaches only a complete coherent set, or you can select files you already downloaded."
)
_COMPLETION_MAX_BATCH = 1000
_COMPLETION_BODY_FIELDS = frozenset({"part_ids", "limit", "idempotency_key"})
_CAPTURE_BODY_FIELDS = frozenset(
    {"part_ids", "limit", "idempotency_key", "mode", "vendor", "background", "edas"}
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


# The one spelling that predates the library-relative convention: a BARE filename, which has
# always meant "under `datasheets/`". The projection states that convention for the legacy
# `datasheet` slot, but a typed document is stored verbatim and can still carry the short form,
# so it is accepted as a FALLBACK - checked under the same root, never outside it - and nothing
# else is.
_LEGACY_DOCUMENT_DIR = "datasheets"


def _library_document_file(library_root, stored_path: str):
    """The real file one recorded document path names, or None when it names nothing safe.

    The path is RECORD data, never request data - the caller names a document id and the record
    supplies this string - but it is still refused rather than trusted. A record can be wrong, or
    hand-edited, or written by a build that had a bug, and a projection is not a permission
    check. Absolute paths, traversal segments and drive letters are rejected before any resolve,
    and the resolved result is required to stay inside the library root, so a symlink pointing
    out of the library fails the same test as `..` does.
    """
    relative = PurePosixPath(str(stored_path or "").replace("\\", "/"))
    if (
        not relative.parts
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or ":" in relative.parts[0]
    ):
        return None
    root = Path(library_root).resolve()

    def _under_root(candidate: Path) -> Path | None:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
        return resolved

    inside = _under_root(root.joinpath(*relative.parts))
    if inside is not None and inside.is_file():
        return inside
    if len(relative.parts) == 1:
        return _under_root(root / _LEGACY_DOCUMENT_DIR / relative.parts[0])
    return inside


def _coverage(record: PartRecord) -> dict:
    """Provider coverage for one record, including what the machine-local stores hold.

    Both stores are opened HERE and handed to the projection, which never opens a path itself.
    The retained-candidate store is the same one guided capture writes a completed provider
    package to, so `downloaded` and `validated` name packages Stockroom is actually holding.
    """
    return provider_coverage(
        record,
        evidence=EvidenceStore((capture_state_root() / "Evidence").resolve()),
        candidates=RetainedCandidateStore(capture_candidates_root()).candidates_for(record.id),
    )


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


def _projection_verifier(library):
    from stockroom.capture.projection import verify_installed_projection

    return lambda record, resolved, *, validation_reports=None: verify_installed_projection(
        library,
        record,
        resolved,
        validation_reports=validation_reports,
    )


def _needs_durable_completion(
    record: PartRecord,
    *,
    library,
    evidence_store=None,
) -> bool:
    from stockroom.capture.verified_cache import record_completion_evidence

    evidence = record_completion_evidence(
        evidence_store or _completion_evidence_store(),
        record,
        projection_verifier=_projection_verifier(library),
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
        if not _needs_durable_completion(
            record,
            library=ctx.profile.library,
            evidence_store=evidence_store,
        ):
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
) -> tuple[list[str] | None, int, bool, str, str | None, bool, tuple[str, ...], str | None]:
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

    from stockroom.capture.requirements import requirements_for_edas

    raw_edas = payload.get("edas", ["kicad", "altium"])
    if type(raw_edas) is not list:
        raise ValueError("edas must be a non-empty list of registered EDA keys")
    edas = tuple(raw_edas)
    requirements_for_edas(edas)

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
        edas,
        header_key if header_key is not None else body_key,
    )


def _capture_identities(
    records: list[PartRecord],
    *,
    library,
    mode: str,
    vendor: str | None,
    background: bool,
    edas: tuple[str, ...],
) -> list[IntakeIdentity]:
    from stockroom.capture.complete import completion_needs
    from stockroom.capture.requirements import requirements_for_edas
    from stockroom.capture.verified_cache import record_completion_evidence

    evidence_store = _completion_evidence_store()
    requested_requirements = requirements_for_edas(edas)
    selected_requirements = set(requested_requirements)
    identities: list[IntakeIdentity] = []
    for record in records:
        if not record.mpn.strip():
            raise ApiError(
                422,
                f"Part {record.id!r} needs an MPN before durable capture can start.",
            )
        evidence = record_completion_evidence(
            evidence_store,
            record,
            projection_verifier=_projection_verifier(library),
        )
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
                            "requested_requirements": [
                                requirement.value for requirement in requested_requirements
                            ],
                            "initial_needs": [
                                requirement.value
                                for requirement in completion_needs(record, evidence)
                                if requirement in selected_requirements
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
    requested_requirements = capture.get("requested_requirements")
    if (
        mode not in _CAPTURE_MODES
        or (vendor is not None and type(vendor) is not str)
        or type(background) is not bool
        or type(initial_needs) is not list
        or any(
            type(requirement) is not str or requirement not in _CAPTURE_REQUIREMENTS
            for requirement in initial_needs
        )
        or (
            requested_requirements is not None
            and (
                type(requested_requirements) is not list
                or not requested_requirements
                or any(
                    type(requirement) is not str
                    or requirement not in _CAPTURE_REQUIREMENTS
                    for requirement in requested_requirements
                )
            )
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
        "requested_requirements": requested_requirements,
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
        """The raw canonical record. Kept for compatibility and diagnostics; the opened
        component reads the normalized dossier projection below instead."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        return ctx.ops.load_record(part_id).to_dict()

    def _dossier(request: Request, part_id: str) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        record = ctx.ops.load_record(part_id)
        # The reading clock is passed IN so the projection stays a pure function; it is the one
        # thing offer freshness cannot answer without, and reading it inside would make the
        # whole dossier untestable.
        return component_dossier(
            record,
            coverage=_coverage(record),
            now=datetime.now(UTC).isoformat(),
        )

    @r.get("/parts/{part_id}/dossier")
    def part_dossier(request: Request, part_id: str) -> dict:
        """The opened component, already decided: identity, quality, key specifications,
        category-aware specification groups, CAD assets and their source coverage, supply,
        distributor offers, typed documents, related parts with their reasons, provenance,
        revisions and diagnostics. See `stockroom.dossier`."""
        return _dossier(request, part_id)

    @r.get("/parts/{part_id}/workspace")
    def part_workspace(request: Request, part_id: str) -> dict:
        """The dossier, under the route's historical name.

        The same document as `/dossier`, not a second projection: a client pinned to this path
        must never receive a different shape from the one beside it.
        """
        return _dossier(request, part_id)

    # -- reviewed decisions about one specification ---------------------------
    #
    # Every one of these answers with the WHOLE recomputed dossier rather than the field it
    # touched. That is deliberate: the reader replaces its state wholesale and can never drift by
    # merging a partial response into a document whose completeness, conflict counts, attention
    # list, provenance ledger and revision timeline all moved because of the same edit.

    def _decided(request: Request, part_id: str, apply) -> dict:
        """Run one decision and answer with the recomputed dossier.

        The engine's refusals are translated here and nowhere else: an unknown field is a 404
        because the address names a specification that does not exist, and a source that never
        answered for the field is a 422 because the request was well-formed and wrong.
        """
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        try:
            apply(ctx)
        except (UnknownSpecification, UnknownCadAsset) as exc:
            raise ApiError(404, str(exc)) from exc
        except (UnpinnableSource, UnofferedCadSource, MixedCadSourceRefused) as exc:
            raise ApiError(422, str(exc)) from exc
        ctx.rebuild_index()
        ctx.auto_push()  # a library write auto-pushes to git (non-fatal without a token)
        return _dossier(request, part_id)

    @r.put("/parts/{part_id}/specifications/{key}/override")
    def set_specification_override(
        request: Request, part_id: str, key: str, body: SpecificationOverrideBody
    ) -> dict:
        """Put a reviewed value at the top of one specification's precedence order.

        Nothing is discarded: every source candidate the field carried is still carried, the
        override is added above them, and the disagreement is reported as `resolved` rather than
        erased. The override also records the sourced answer it displaced, so the row can say
        what it overrode and clearing it is a real return to that answer.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.set_specification_override(
                part_id,
                key,
                body.value,
                reviewed_by="user",
                reviewed_at=datetime.now(UTC).isoformat(),
                note=body.note,
                verified=body.verified,
            ),
        )

    @r.delete("/parts/{part_id}/specifications/{key}/override")
    def clear_specification_override(request: Request, part_id: str, key: str) -> dict:
        """Withdraw the reviewed value, returning the field to its sources.

        Clearing a field that carries no override is a success, not a 404: the end state asked
        for is already true, and failing would make the action unusable to any caller that
        cannot know the current state before asking.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.clear_specification_override(part_id, key),
        )

    @r.put("/parts/{part_id}/specifications/{key}/preferred-source")
    def set_specification_preferred_source(
        request: Request, part_id: str, key: str, body: PreferredSourceBody
    ) -> dict:
        """Pin one specification to one source's answer.

        The pin follows the source rather than copying its value, so refreshing that source
        moves the field with it. A source that offered nothing for this field is refused.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.set_specification_preferred_source(
                part_id,
                key,
                body.source_id,
                reviewed_by="user",
                reviewed_at=datetime.now(UTC).isoformat(),
            ),
        )

    @r.delete("/parts/{part_id}/specifications/{key}/preferred-source")
    def clear_specification_preferred_source(
        request: Request, part_id: str, key: str
    ) -> dict:
        """Return one specification to computed precedence. Idempotent, like clearing an
        override."""
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.clear_specification_preferred_source(part_id, key),
        )

    # -- the preferred CAD source ---------------------------------------------
    #
    # The one column-level fact the CAD column always STATED and never let anybody set. These
    # answer with the whole recomputed dossier for the same reason the specification writes do:
    # a preferred source moves the three asset modules, the coverage comparison, the quality
    # summary and the revision timeline together, and a reader that merged a partial response
    # would be holding a document whose parts disagree.
    #
    # What a change would REPLACE is not computed here and is not reported afterwards. It is
    # published on the dossier itself (`cadAssets.preference.options`), planned by the same
    # function these writes refuse with - so the confirmation a person approves and the decision
    # the record makes cannot describe different outcomes.

    @r.put("/parts/{part_id}/cad/preferred-source")
    def set_cad_preferred_source(
        request: Request, part_id: str, body: CadPreferredSourceBody
    ) -> dict:
        """Prefer one provider for this component's whole CAD set.

        Refused (422) when that provider does not supply all three artifacts, in the coverage
        vocabulary the comparison screen already speaks. Stockroom takes a component's CAD from
        one provider's coherent download, so a set source that cannot answer for one of the
        three is not a partial success - it is a preference the resolver could never honour.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.set_cad_preferred_source(
                part_id,
                body.provider,
                coverage=_coverage,
                reviewed_by="user",
                reviewed_at=datetime.now(UTC).isoformat(),
            ),
        )

    @r.delete("/parts/{part_id}/cad/preferred-source")
    def clear_cad_preferred_source(request: Request, part_id: str) -> dict:
        """Return the whole set to the providers that actually supplied the files.

        Idempotent, like clearing a specification override: the end state asked for is already
        true when nothing was pinned, and failing would make the action unusable to a caller
        that cannot know the current state before asking.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.clear_cad_preferred_source(part_id),
        )

    @r.put("/parts/{part_id}/cad/{asset}/preferred-source")
    def set_cad_asset_preferred_source(
        request: Request, part_id: str, asset: str, body: CadPreferredSourceBody
    ) -> dict:
        """Prefer one provider for ONE asset, when that leaves the set coherent.

        Two refusals, and they are different sentences. An asset kind this component does not
        have is a 404, because the address names something that does not exist. A provider that
        does not supply the artifact, or a pin that would leave two providers in force across
        the three assets, is a 422: the request was well formed and the answer is no.

        The second refusal is the product rule, not a storage limitation. A mixed set cannot be
        indexed from one evidence manifest, so accepting the pin would only move the failure to
        the moment the files are resolved - with the preference already written and a person
        already believing it took.
        """
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.set_cad_asset_preferred_source(
                part_id,
                asset,
                body.provider,
                coverage=_coverage,
                reviewed_by="user",
                reviewed_at=datetime.now(UTC).isoformat(),
            ),
        )

    @r.delete("/parts/{part_id}/cad/{asset}/preferred-source")
    def clear_cad_asset_preferred_source(request: Request, part_id: str, asset: str) -> dict:
        """Withdraw one asset's own pin, leaving the whole-set preference standing. Idempotent."""
        return _decided(
            request,
            part_id,
            lambda ctx: ctx.ops.clear_cad_asset_preferred_source(part_id, asset),
        )

    @r.get("/parts/{part_id}/documents/{document_id}/file")
    def part_document_file(request: Request, part_id: str, document_id: str) -> FileResponse:
        """The bytes of one document this part holds.

        This is NOT a file read primitive and must never become one. The caller names a document
        id; the path comes from the record's own entry for that id and from nowhere else, so
        there is no caller-supplied path to join and nothing to traverse with. A resolved path
        that leaves the library root is refused even so, because the record itself could be
        wrong and a projection is not a permission check.

        Three absences are three different answers, and all of them are 404 rather than a stack
        trace: the id names no document this part references, the document is a link with no
        stored copy (the caller should open the URL), or the copy we recorded is gone from disk.
        """
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        document = find_document(ctx.ops.load_record(part_id), document_id)
        if document is None:
            raise FileNotFoundError(f"part {part_id} references no document {document_id}")
        if not document["localPath"]:
            raise FileNotFoundError(
                f"{document['title']} is a referenced link with no stored copy; open its "
                "source page instead"
            )
        path = _library_document_file(ctx.profile.library.root, document["localPath"])
        if path is None or not path.is_file():
            raise FileNotFoundError(
                f"the stored copy of {document['title']} is no longer in the library"
            )
        media_type = (
            mimetypes.guess_type(path.name)[0]
            or document["mimeType"]
            or "application/octet-stream"
        )
        return FileResponse(
            path,
            media_type=media_type,
            filename=path.name,
            # Inline, because the point of this route is a viewer inside the app rather than a
            # download the reader then has to find again.
            content_disposition_type="inline",
        )

    @r.get("/parts/{part_id}/providers")
    def part_providers(request: Request, part_id: str) -> dict:
        """Which provider can supply everything for this part, and how to reach each one."""
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        return _coverage(ctx.ops.load_record(part_id))

    @r.post("/parts/{part_id}/providers")
    def set_part_provider_coverage(
        request: Request, part_id: str, body: ProviderCoverageBody
    ) -> dict:
        """Record what a person knows about one provider's coverage of this part.

        The claim is persisted on the record and attributed to them. It cannot displace a
        `downloaded` or `validated` status - that is enforced in `provider_coverage`, where the
        grid is built, rather than here, so no second writer can route around it.
        """
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        record = ctx.ops.load_record(part_id)
        try:
            set_user_assertion(
                record,
                provider=body.provider,
                artifact=body.artifact,
                status=body.status,
                noted_at=datetime.now(UTC).isoformat(),
                note=body.note,
            )
        except (KeyError, ValueError) as exc:
            raise ApiError(422, str(exc)) from exc
        path = ctx.ops.lib.parts_dir / f"{part_id}.json"
        with Transaction(ctx.repo) as txn:
            path.write_text(record.dumps(), encoding="utf-8")
            txn.track(path)
            txn.commit(
                f"Record provider coverage for {part_id}: {body.provider}/{body.artifact}"
            )
        ctx.rebuild_index()
        ctx.auto_push()
        return _coverage(record)

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

    def _shell(ctx):
        """The native shell bridge, or an honest refusal.

        Absent on a host that owns no native window (a source run behind a browser, a test
        harness). The three Manage items that need it are hidden rather than disabled, so this
        never has to explain itself twice.
        """

        shell = getattr(ctx, "native_shell", None)
        if shell is None:
            raise ApiError(409, "This Stockroom host cannot reach the file browser.")
        return shell

    @r.get("/parts/{part_id}/shell")
    def part_shell(request: Request, part_id: str) -> dict:
        """What Manage > Export Component... / Open In... / Reveal Component Files... may offer.

        One request answers all three, because all three are decided by the same three facts:
        whether this host owns a native window, which formats this component really has files
        for, and which EDA applications this machine really has. Everything absent here is an
        item the menu does not draw.
        """

        from stockroom.component_shell import (
            available_export_formats,
            component_directory,
        )

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        shell = getattr(ctx, "native_shell", None)
        if shell is None:
            return {
                "supported": False,
                "component_directory": False,
                "export_formats": [],
                "eda_applications": [],
            }
        record = ctx.ops.load_record(part_id)
        try:
            directory = component_directory(ctx.profile.library.root, part_id)
            has_directory = directory.is_dir()
        except Exception:  # noqa: BLE001 - an unresolvable directory is simply not offered
            has_directory = False
        try:
            applications = list(shell.detected_eda_applications())
        except Exception:  # noqa: BLE001 - a host that cannot answer offers nothing
            applications = []
        return {
            "supported": True,
            "component_directory": has_directory,
            "export_formats": list(available_export_formats(ctx.profile.library, record)),
            "eda_applications": applications,
        }

    @r.post("/parts/{part_id}/reveal")
    def reveal_part_files(request: Request, part_id: str) -> dict:
        """Open the OS file browser at this component's own directory.

        The path is resolved HERE, from the active library root and the part id. No caller
        supplies one, which is the whole reason this route takes no body: an endpoint that
        reveals a path it was handed is a way to start Explorer on anything.
        """

        from stockroom.component_shell import ComponentShellError, component_directory

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        shell = _shell(ctx)
        library_root = Path(ctx.profile.library.root).resolve(strict=False)
        try:
            directory = component_directory(library_root, part_id)
        except ComponentShellError as exc:
            raise ApiError(400, str(exc)) from exc
        if not directory.is_dir():
            raise ApiError(409, "This component has no files in the library yet.")
        try:
            shell.reveal_component_directory(str(library_root), str(directory))
        except Exception as exc:  # noqa: BLE001 - host errors become one actionable verdict
            raise ApiError(409, "The file browser could not be opened.") from exc
        return {"part_id": part_id, "revealed": True}

    @r.post("/parts/{part_id}/export")
    def export_part(request: Request, part_id: str, body: dict | None = None) -> dict:
        """Write this component's CAD set for one format to its machine-local export folder."""

        from stockroom.component_shell import (
            EXPORT_FORMATS,
            ComponentShellError,
            export_component,
        )

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        payload = {} if body is None else body
        unexpected = sorted(str(key) for key in payload if key != "format")
        if unexpected:
            raise ValueError("unknown export fields: " + ", ".join(unexpected))
        export_format = payload.get("format")
        if export_format not in EXPORT_FORMATS:
            raise ValueError("format must be one of: " + ", ".join(EXPORT_FORMATS))
        record = ctx.ops.load_record(part_id)
        try:
            exported = export_component(ctx.profile.library, record, export_format)
        except ComponentShellError as exc:
            raise ApiError(409, str(exc)) from exc
        return {
            "part_id": part_id,
            "format": exported.format,
            "file_count": len(exported.files),
            "file_names": [item.name for item in exported.files],
        }

    @r.post("/parts/{part_id}/open-in")
    def open_part_in(request: Request, part_id: str, body: dict | None = None) -> dict:
        """Export this component and open the result in a detected EDA application.

        The application is named by its stable id and resolved to a binary inside the window
        host; the file is this backend's own export path. Neither crosses from the web layer.
        """

        from stockroom.component_shell import (
            EXPORT_FORMATS,
            ComponentShellError,
            export_component,
            export_root,
        )

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        shell = _shell(ctx)
        payload = {} if body is None else body
        unexpected = sorted(
            str(key) for key in payload if key not in {"application_id", "format"}
        )
        if unexpected:
            raise ValueError("unknown open fields: " + ", ".join(unexpected))
        application_id = payload.get("application_id")
        if type(application_id) is not str or not application_id:
            raise ValueError("application_id is required")
        known = {row["id"] for row in shell.detected_eda_applications()}
        if application_id not in known:
            raise ApiError(409, "That application is not installed on this machine.")
        export_format = payload.get("format", "kicad")
        if export_format not in EXPORT_FORMATS:
            raise ValueError("format must be one of: " + ", ".join(EXPORT_FORMATS))
        record = ctx.ops.load_record(part_id)
        try:
            exported = export_component(ctx.profile.library, record, export_format)
        except ComponentShellError as exc:
            raise ApiError(409, str(exc)) from exc
        try:
            shell.open_component_file(
                application_id,
                str(export_root()),
                str(exported.primary_file),
            )
        except Exception as exc:  # noqa: BLE001 - host errors become one actionable verdict
            raise ApiError(409, "That application could not be started.") from exc
        return {
            "part_id": part_id,
            "application_id": application_id,
            "format": exported.format,
            "opened": True,
        }

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
            projection_verifier=_projection_verifier(ctx.profile.library),
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
                        f"{_PERSON_DRIVEN_CAPTURE_INSTRUCTION} {implemented_capture[s.key].instruction}"
                        if s.key in implemented_capture
                        else s.instruction
                    ),
                    # True when Stockroom implements person-driven capture for this surface:
                    # it can open the exact page, name the required files, and attach what the
                    # person downloads. Every implemented provider is person-driven.
                    "capture_available": s.key in implemented_capture,
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

        The central question about a library, and it used to be answerable only by running a
        script by hand -- which made it a missing feature rather than a tool. Read-only and
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
        from stockroom.capture.requirements import requirements_for_edas
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
            edas,
            idempotency_key,
        ) = _capture_command(request, body)
        if vendor is not None and get_adapter(vendor) is None:
            raise ValueError(f"no network capture adapter for provider {vendor!r}")

        # There is ONE capture mode: a person works the provider page. The legacy `mode` field
        # is still accepted so existing callers do not 500, and every value means the same run.
        person_driven_providers = mode != "automatic" or vendor is not None
        if person_driven_providers:
            if part_ids is None or len(part_ids) != 1:
                raise ValueError("person-driven capture requires exactly one selected part")
            if limit_supplied:
                raise ValueError(
                    "person-driven capture does not accept a batch limit; select exactly one part"
                )
            if background:
                raise ValueError("person-driven capture requires a visible provider page")
        records = (
            [_current_completion_record(ctx, part_id) for part_id in part_ids]
            if part_ids is not None
            else None
        )
        if person_driven_providers:
            from stockroom.capture.evidence import exact_identity

            assert records is not None
            try:
                exact_identity(records[0])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "person-driven capture requires one exact manufacturer and MPN"
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
                    library=ctx.profile.library,
                    mode=mode,
                    vendor=vendor,
                    background=background,
                    edas=edas,
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
                requested_requirements=requirements_for_edas(edas),
                progress=progress,
                should_stop=should_stop,
                limit=None if person_driven_providers else limit,
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

    @r.post("/parts/{part_id}/files")
    def add_part_files(request: Request, part_id: str, body: dict | None = None) -> dict:
        """Process user-selected CAD files without inventing a provider capture task.

        The selected component is the destination. The entire selection is inspected together so
        split symbol, footprint, model, and native Altium files can form one coherent package;
        irrelevant siblings are reported and ignored, and the response is canonical readback of
        what remains.
        """

        from pathlib import Path

        from stockroom.ingest.manual_files import import_manual_cad_files

        if not is_valid_part_id(part_id):
            raise ValueError(f"invalid part identifier: {part_id!r}")
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        payload = {} if body is None else body
        unexpected = sorted(str(key) for key in payload if key != "paths")
        if unexpected:
            raise ValueError("unknown file-intake fields: " + ", ".join(unexpected))
        raw_paths = payload.get("paths")
        if (
            type(raw_paths) is not list
            or not 1 <= len(raw_paths) <= 100
            or any(type(path) is not str or not path.strip() for path in raw_paths)
        ):
            raise ValueError("paths must contain between 1 and 100 selected files")
        try:
            paths = tuple(Path(path).resolve(strict=True) for path in raw_paths)
        except (OSError, RuntimeError) as exc:
            raise ValueError("a selected file is no longer available") from exc
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ValueError("every selected path must be a real file")

        result = ctx.jobs.run_write(lambda: import_manual_cad_files(ctx, part_id, paths))
        if result["attached"]:
            ctx.jobs.run_write(ctx.rebuild_index)
            ctx.jobs.run_write(ctx.auto_push)
        if result["complete"]:
            surface = getattr(ctx, "provider_browser_surface", None)
            owner = getattr(surface, "__self__", surface)
            close = getattr(owner, "close_active_provider_browser", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    # The library mutation is already durable. A stale or closing UI surface must
                    # not turn successful file intake into a false error for the person using it.
                    pass
        return result

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

    @r.post("/capture/batches/{batch_id}/provider/show")
    def show_capture_provider(request: Request, batch_id: str) -> dict:
        """Reveal the one provider route already owned by this durable capture."""

        from stockroom.capture.intent import active_person_capture

        if _OPAQUE_WORKFLOW_REFERENCE.fullmatch(batch_id) is None:
            raise ApiError(400, "batch_id is not a valid opaque workflow identifier")
        ctx = request.app.state.ctx
        coordinator = ctx.workflow_coordinator
        if coordinator is None:
            raise ApiError(503, "The durable workflow coordinator is not mounted.")
        coordinator.get_batch(batch_id)
        items = coordinator.list_items(batch_id)
        if len(items) != 1:
            raise ApiError(409, "Guided capture requires one durable workflow item.")
        item = items[0]
        projection = _capture_item_projection(item)
        route = active_person_capture(item.id, part_id=projection["part_id"])

        surface = getattr(ctx, "provider_browser_surface", None)
        owner = getattr(surface, "__self__", surface)
        show = getattr(owner, "show_active_provider_browser", None)
        if not callable(show):
            raise ApiError(409, "This Stockroom host cannot restore the provider page.")
        try:
            show()
        except Exception as exc:  # noqa: BLE001 - host errors become one actionable verdict
            raise ApiError(409, "The active provider page could not be shown.") from exc
        return {
            "workflow_batch_id": batch_id,
            "part_id": projection["part_id"],
            "visible": True,
            "active_route": route is not None,
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
                    "instruction": (
                        f"{_PERSON_DRIVEN_CAPTURE_INSTRUCTION} {a.capability.instruction}"
                    ),
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
