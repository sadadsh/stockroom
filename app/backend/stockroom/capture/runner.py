"""Assemble the completion engine for a live app context.

This is the ONE place that knows which sources exist and what a run costs. Keeping it here
means a route stays four lines and the numbers below sit next to the measurement that produced
them, rather than being scattered as literals across the API.

There are two lanes and no ladder between them. `run_completion` is the zero-interaction lane:
immutable evidence Stockroom already holds, over one part or the whole library, opening no
window. `run_guided_capture` is the person-driven lane: ONE selected part, provider pages the
person works, and Stockroom staging, validating, and attaching what they download.

Active CAD is deliberately stricter than catalogue discovery.  A converted LCSC/EasyEDA
KiCad trio is not a dual-EDA source set and its authoring trust is not established merely
because the distributor identity matched.  It therefore cannot be registered as an active
completion source.  Verified local evidence and provider captures may publish only an exact
same-download KiCad + native Altium + STEP set.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from stockroom.capture.complete import (
    complete_library,
    iter_incomplete,
)
from stockroom.capture.digikey_models import default_digikey_models_ids
from stockroom.capture.intent import PersonCaptureIntent, person_capture_intent
from stockroom.capture.pacing import CircuitBreaker
from stockroom.capture.trace import install_capture_log, trace
from stockroom.text import counted

# Five parts in a row all blocked is the catalogue having closed the door, not a burst edge.
_BREAKER_THRESHOLD = 5
_DURABLE_CAPTURE_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_DURABLE_CAPTURE_REPORT_MAX_BYTES = 4 * 1024 * 1024


def _trace_provider_routing(*, vendor, provider_keys) -> None:
    """Say WHICH provider surfaces this run will open, before any page opens.

    This is the first question a failed run raises and the one the report could never answer: the
    owner saw "no complete CAD package" with no way to tell an absent provider from one that was
    never visited. Wrapped whole: describing a route may never break one.
    """

    try:
        from stockroom.capture.vendors import get_adapter

        selected = list(provider_keys)
        trace(
            "capture.route.order",
            mode="user-driven",
            preferred=str(vendor or ""),
            selected=selected,
        )
        try:
            registered = _vendor_chain(vendor)
        except Exception:  # noqa: BLE001 - an unknown preference is the caller's error to raise
            registered = list(_VENDOR_CHAIN)
        for key in dict.fromkeys([*selected, *registered]):
            adapter = get_adapter(key)
            if adapter is None:
                trace(
                    "capture.route.provider",
                    provider=key,
                    included=False,
                    why="no implemented capture adapter",
                )
                continue
            trace(
                "capture.route.provider",
                provider=key,
                label=adapter.capability.label,
                included=key in selected,
                formats=sorted(adapter.capability.supported_formats),
            )
    except Exception:  # noqa: BLE001 - the routing trace is never a routing decision
        pass


def _convert_ul_altium_package(inputs, expected_manufacturer: str, expected_mpn: str):
    """Lazy bridge from capture to the Windows-only Altium conversion capability."""

    from stockroom.altium.ul_import import convert_ul_altium_package

    return convert_ul_altium_package(
        inputs,
        expected_manufacturer=expected_manufacturer,
        expected_mpn=expected_mpn,
    )


def _verified_source(
    ctx,
    *,
    evidence_store=None,
    run_write=None,
    preserve_active_pair: bool = False,
):
    """Build the immutable local-evidence source without importing app mutation at module load."""

    from stockroom.cad_materialization import materialize_kicad, materialize_pair
    from stockroom.capture.projection import verify_installed_projection
    from stockroom.capture.verified_cache import VerifiedEvidenceSource
    from stockroom.evidence import EvidenceStore
    from stockroom.model.part import PartRecord

    def require_part_record(record: object) -> PartRecord:
        if not isinstance(record, PartRecord):
            raise TypeError("verified evidence materialization requires a PartRecord")
        return record

    store = evidence_store or EvidenceStore(_capture_evidence_root(ctx))
    return VerifiedEvidenceSource(
        store,
        materialize_kicad=lambda record, resolved: materialize_kicad(
            ctx,
            require_part_record(record),
            resolved,
        ),
        materialize_pair=lambda record, kicad, altium: materialize_pair(
            ctx,
            require_part_record(record),
            kicad,
            altium,
            evidence_store=store,
        ),
        run_write=run_write,
        preserve_active_pair=preserve_active_pair,
        projection_verifier=lambda record, resolved, *, validation_reports=None: verify_installed_projection(
            ctx.profile.library,
            record,
            resolved,
            validation_reports=validation_reports,
        ),
    )


def build_sources(
    ctx,
    *,
    run_write=None,
    paced: bool = True,
    evidence_store=None,
    preserve_active_pair: bool = False,
):
    """Return only sources capable of publishing one coherent dual-EDA set.

    ``paced`` remains in the public signature for callers that select batch or
    single-part execution.  It no longer changes the local source list: provider
    pacing belongs to each managed browser adapter, while partial catalogue CAD
    is retained as candidate evidence rather than projected into the library.
    """

    del paced
    verified = _verified_source(
        ctx,
        evidence_store=evidence_store,
        run_write=run_write,
        preserve_active_pair=preserve_active_pair,
    )
    return [verified]


def coverage(ctx) -> dict:
    """What the library still needs, answered from the RECORDS ON DISK.

    This is the owner's central question -- *"is my library complete"* -- and until now it
    could only be answered by a script outside the app. It reads the parts directory rather
    than the derived index for the same reason the Altium emitter does: the index is rebuilt
    in the background, and a coverage number that disagrees with the files is a number that
    lies.

    The action totals are reported separately. `needs_files` counts parts the zero-interaction
    verified-evidence lane can improve, `needs_assistance` counts parts whose gaps overlap a
    provider a PERSON can work through, and `unsourced` counts parts with a real gap that neither
    lane can fill. The first two may overlap: a part can gain KiCad from retained evidence and
    still need a person to fetch a native-Altium export.
    """
    from stockroom.capture.complete import completion_needs
    from stockroom.capture.requirements import Requirement
    from stockroom.capture.vendors import get_adapter
    from stockroom.capture.verified_cache import record_completion_evidence
    from stockroom.evidence import EvidenceStore

    evidence_store = EvidenceStore(_capture_evidence_root(ctx))
    direct_sources = build_sources(
        ctx,
        paced=False,
        evidence_store=evidence_store,
    )
    can_provide = set()
    for source in direct_sources:
        can_provide |= set(source.provides())
    # Every provider surface is person-driven, so none of them belongs in the zero-interaction
    # lane. Listing them as assisted is the honest answer to "can anything still help this part".
    assisted_source_keys: list[str] = []
    assisted_can_provide = set()
    for key in _vendor_chain(None):
        adapter = get_adapter(key)
        if adapter is None:
            continue
        assisted_source_keys.append(key)
        pins = set(adapter.capability.supported_formats)
        if "kicad" in pins:
            assisted_can_provide |= {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}
        if "model" in pins:
            assisted_can_provide.add(Requirement.KICAD_MODEL)
        if "altium" in pins:
            assisted_can_provide |= {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}

    total = 0
    complete = 0
    needs_files = 0
    needs_assistance = 0
    unsourced = 0
    by_requirement: dict[str, int] = {}
    for path in sorted(ctx.profile.library.parts_dir.glob("*.json")):
        total += 1
        try:
            record = ctx.ops.load_record(path.stem)
        except Exception:  # noqa: BLE001 - a corrupt record is counted, never fatal
            continue
        from stockroom.capture.projection import verify_installed_projection

        evidence = record_completion_evidence(
            evidence_store,
            record,
            projection_verifier=lambda current, resolved, *, validation_reports=None: verify_installed_projection(
                ctx.profile.library,
                current,
                resolved,
                validation_reports=validation_reports,
            ),
        )
        needs = completion_needs(record, evidence)
        if not needs:
            complete += 1
            continue
        for need in needs:
            by_requirement[need.value] = by_requirement.get(need.value, 0) + 1
        automatic_overlap = set(needs) & can_provide
        assisted_overlap = set(needs) & assisted_can_provide
        if automatic_overlap:
            needs_files += 1
        if assisted_overlap:
            needs_assistance += 1
        if not automatic_overlap and not assisted_overlap:
            unsourced += 1
    return {
        "total": total,
        "complete": complete,
        "needs_files": needs_files,
        "needs_assistance": needs_assistance,
        "unsourced": unsourced,
        "by_requirement": dict(sorted(by_requirement.items())),
        "sources": [s.key for s in direct_sources],
        "can_provide": sorted(r.value for r in can_provide),
        "assisted_sources": assisted_source_keys,
        "assisted_can_provide": sorted(r.value for r in assisted_can_provide),
    }


def run_completion(ctx, *, progress=None, should_stop=None, part_ids=None, limit=None) -> dict:
    """Complete what verified local evidence alone can complete, for one part or the library.

    There is no library-wide automatic provider lane any more: every provider surface is worked
    by a PERSON, one part at a time, through `run_guided_capture`. What remains here is the
    zero-interaction lane - immutable evidence Stockroom already holds - so a bulk pass still
    fills every gap it can without opening a single window.

    `part_ids` narrows the run to a chosen set; omitted, the worklist is DERIVED from the library,
    which is what makes a stopped run resumable by simply running it again.
    """

    from stockroom.capture.projection import verify_installed_projection
    from stockroom.capture.verified_cache import record_completion_evidence
    from stockroom.evidence import EvidenceStore

    trace(
        "capture.run.start",
        mode="verified-evidence",
        parts=(len(list(part_ids)) if isinstance(part_ids, (list, tuple)) else "derived"),
        limit=limit,
        log=install_capture_log(),
    )
    evidence_store = EvidenceStore(_capture_evidence_root(ctx))

    def completion_evidence_resolver(record):
        return record_completion_evidence(
            evidence_store,
            record,
            projection_verifier=lambda current, resolved, *, validation_reports=None: verify_installed_projection(
                ctx.profile.library,
                current,
                resolved,
                validation_reports=validation_reports,
            ),
        )

    sources = build_sources(
        ctx,
        run_write=ctx.jobs.run_write,
        paced=False,
        evidence_store=evidence_store,
    )
    load_record = ctx.ops.load_record
    if part_ids is None:
        work = iter_incomplete(
            ctx.profile.library.parts_dir,
            load_record=load_record,
            sources=sources,
            evidence_resolver=completion_evidence_resolver,
        )
        total = None
    else:
        work = list(part_ids)
        total = len(work)
    if limit is not None:
        work = _take(work, limit)
        total = min(total, limit) if total is not None else None
    report = complete_library(
        work,
        load_record=load_record,
        sources=sources,
        on_progress=progress,
        should_stop=should_stop,
        total=total,
        breaker=CircuitBreaker(threshold=_BREAKER_THRESHOLD),
        evidence_resolver=completion_evidence_resolver,
    )
    _trace_run_verdict("verified-evidence", report)
    if report.of("completed", "improved"):
        ctx.jobs.run_write(ctx.rebuild_index)
        ctx.jobs.run_write(ctx.auto_push)
    return report.to_dict()


def run_guided_capture(
    ctx,
    *,
    part_ids=None,
    vendor=None,
    progress=None,
    should_stop=None,
    limit=None,
    capture_id: str | None = None,
) -> dict:
    """Collect CAD from provider surfaces a PERSON works, one selected part at a time.

    There is exactly one capture mode. Stockroom resolves a safe provider URL, hosts the provider
    page in its own window, shows what the person needs to select, and stages, validates, and
    attaches whatever they download. It never navigates within the provider page, clicks a
    control, fills a form, chooses a format, signs in, accepts a licence, or answers a security
    check.

    Provider surfaces are opened only when EXACTLY ONE part is selected, because that is the only
    shape a person can stand in front of. A broader run - a filtered list, or the derived
    library-wide worklist - is the zero-interaction verified-evidence lane and opens no window.
    A preferred ``vendor`` narrows one selected part to that one provider surface; without it
    every registered provider is offered in turn.
    """

    if part_ids is not None and isinstance(part_ids, (str, bytes)):
        raise ValueError("part_ids must be a sequence of exact part ids")
    from threading import Event

    workflow_cancelled = Event()
    # What the PERSON says about the capture in front of them. It is published under the one
    # selected part below (see `capture/intent.py`) and reaches this run through the SAME polled
    # predicates cancellation already uses, because that is the channel that demonstrably reaches
    # a running person-driven window. A verified-evidence pass opens no such window, so its intent
    # is simply never published and nothing can signal it.
    person_intent = PersonCaptureIntent()
    selected_parts = list(part_ids) if part_ids is not None else None
    exact_part_id: str | None = None
    if selected_parts is not None and len(selected_parts) == 1:
        candidate = selected_parts[0]
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or candidate != candidate.strip()
        ):
            raise ValueError("person-driven capture requires one exact selected part")
        exact_part_id = candidate
    if vendor is not None:
        if exact_part_id is None:
            raise ValueError("person-driven capture requires exactly one selected part")
        if not isinstance(vendor, str) or not vendor.strip():
            raise ValueError("person-driven capture requires one selected provider")
    person_driven_capture = exact_part_id is not None
    if person_driven_capture and limit is not None:
        raise ValueError(
            "person-driven capture does not accept a batch limit; select exactly one part"
        )
    if selected_parts is not None:
        part_ids = selected_parts
    trace(
        "capture.run.start",
        mode="user-driven" if person_driven_capture else "verified-evidence",
        preferred_provider=str(vendor or ""),
        parts=(len(selected_parts) if selected_parts is not None else "derived"),
        limit=limit,
        log=install_capture_log(),
    )

    def capture_should_stop() -> bool:
        # A person skipping the part is their own stop, so it travels on the existing stop
        # predicate rather than a second channel that would have to be proven to reach the
        # running capture separately.
        return (
            workflow_cancelled.is_set()
            or person_intent.part_skipped()
            or bool(should_stop and should_stop())
        )

    provider_keys = (
        ([vendor.strip().lower()] if isinstance(vendor, str) else _vendor_chain(None))
        if person_driven_capture
        else []
    )

    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.capture.projection import verify_installed_projection
    from stockroom.capture.vendors import get_adapter
    from stockroom.capture.verified_cache import record_completion_evidence
    from stockroom.evidence import EvidenceStore
    from stockroom.ingest.candidates import RetainedCandidateStore
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        return IngestPipeline(
            ctx.profile,
            ctx.repo,
            ctx.cli,
            auto_embed_altium_models=True,
        )

    evidence_store = EvidenceStore(_capture_evidence_root(ctx))
    # ONE store for the whole run: it holds the retained-candidate index in memory, so a second
    # instance built per provider would save a list that never saw the first provider's work.
    # Built only when a provider surface can actually open, so a run with nothing to capture never
    # creates the directory.
    candidate_store = (
        RetainedCandidateStore(capture_candidates_root()) if provider_keys else None
    )

    def completion_evidence_resolver(record):
        return record_completion_evidence(
            evidence_store,
            record,
            projection_verifier=lambda current, resolved, *, validation_reports=None: verify_installed_projection(
                ctx.profile.library,
                current,
                resolved,
                validation_reports=validation_reports,
            ),
        )

    if person_driven_capture:
        from stockroom.capture.evidence import exact_identity

        # Fail before constructing a provider runtime or opening a page. A search-only MPN or a
        # manufacturer-free record is not an exact collection task.
        assert exact_part_id is not None
        exact_identity(ctx.ops.load_record(exact_part_id))
        for key in provider_keys:
            if get_adapter(key) is None:
                raise ValueError(f"no network capture adapter for provider {key!r}")

    # The visible host owns provider navigation independently of application-update delivery.
    # Durable acquisition runs in an isolated copy-on-write context, so this direct capability is
    # copied with that context. Production replacement hosts retain their existing runtime port.
    provider_surface = getattr(ctx, "provider_browser_surface", None)
    if not callable(provider_surface):
        update_runtime = getattr(ctx, "update_convergence", None)
        provider_surface = getattr(update_runtime, "provider_browser_surface", None)
    if not callable(provider_surface):
        provider_surface = None

    # ONE store for the whole run, and one chance to refresh it from the person's own browser
    # history before any source is built. It carries the opaque DigiKey models id learned from the
    # person's own navigation; opt-in and default off, and when it is off this is a dictionary
    # lookup and nothing more. See `capture/models_history.py`.
    models_ids = default_digikey_models_ids() if "digikey" in provider_keys else None
    if models_ids is not None:
        from stockroom.capture.models_history import learn_models_ids_for_library

        learn_models_ids_for_library(ctx, store=models_ids)

    def make_guided_source(key: str):
        return GuidedCaptureSource(
            make_pipeline,
            vendor=key,
            download_root=_capture_downloads(ctx, key),
            # Both the direct and DigiKey-aggregated Ultra Librarian routes can deliver legacy
            # P-CAD/script packages when native Altium libraries are unavailable. Inject the
            # content-recognizing converter at the provider-surface boundary: it returns ``None``
            # for unrelated archives. Identity and coherent-pair validation remain downstream.
            convert_altium=(
                _convert_ul_altium_package
                if key in {"digikey", "ultralibrarian"}
                else None
            ),
            # One selected part is collected exhaustively: every registered author route is
            # offered, and an extra complete set is retained as a variant rather than silently
            # replacing the active pair.
            collect_variants=True,
            preserve_active_pair=True,
            close_after_supply=True,
            run_write=ctx.jobs.run_write,
            now_iso=_utc_now_iso,
            evidence_store=evidence_store,
            candidate_store=candidate_store,
            projection_verifier=lambda record, resolved, *, validation_reports=None: verify_installed_projection(
                ctx.profile.library,
                record,
                resolved,
                validation_reports=validation_reports,
            ),
            user_cancelled=capture_should_stop,
            # "No more is coming from this page", consumed by whichever route is open when the
            # person says it. Without this a person-driven route could only end on cancel, on
            # ~25 s of quiet after a file landed, or on the timeout - five times over for
            # DigiKey's five author routes.
            user_finished=person_intent.take_route_finish,
            cancel_workflow=workflow_cancelled.set,
            # DigiKey only, because DigiKey is the only surface with a per-part models page and a
            # provider tab to land on. It carries the opaque id learned from the person's own
            # navigation so their SECOND visit to a part skips the search they already did.
            models_ids=models_ids if key == "digikey" else None,
            # Configured Product Information V4 credentials make DigiKey's exact ProductDetails
            # and Media response authoritative. Do not silently replace a missing exact route
            # with a provider-wide search page; surface the missing route to the operator.
            strict_catalog_urls=bool(
                getattr(ctx.config, "digikey_client_id", "")
                and getattr(ctx.config, "digikey_client_secret", "")
            ),
            provider_surface=provider_surface,
            publish_active_route=person_intent.set_active_route,
            clear_active_route=person_intent.clear_active_route,
            take_selected_files=person_intent.take_selected_files,
        )

    guided_sources = [make_guided_source(key) for key in provider_keys]
    _trace_provider_routing(vendor=vendor, provider_keys=provider_keys)
    # Verified local evidence is the zero-interaction first lane. If it fills the remaining
    # requirements, GuidedCaptureSource is never asked and no provider window opens.
    sources = [
        *build_sources(
            ctx,
            run_write=ctx.jobs.run_write,
            paced=False,
            evidence_store=evidence_store,
            preserve_active_pair=person_driven_capture,
        ),
        *guided_sources,
    ]
    load_record = ctx.ops.load_record

    if part_ids is None:
        work = iter_incomplete(
            ctx.profile.library.parts_dir,
            load_record=load_record,
            sources=sources,
            evidence_resolver=completion_evidence_resolver,
        )
        total = None
    else:
        work = list(part_ids)
        total = len(work)
    if limit is not None:
        work = _take(work, limit)
        total = min(total, limit) if total is not None else None

    try:
        # Published for exactly as long as a person could be standing in front of this capture.
        with person_capture_intent(
            exact_part_id,
            person_intent,
            capture_id=capture_id,
        ):
            report = complete_library(
                work,
                load_record=load_record,
                sources=sources,
                on_progress=progress,
                should_stop=capture_should_stop,
                total=total,
                breaker=CircuitBreaker(threshold=_BREAKER_THRESHOLD),
                collect_variants=person_driven_capture,
                exhaustive=person_driven_capture,
                evidence_resolver=completion_evidence_resolver,
            )
    finally:
        for source in guided_sources:
            source.close()

    _trace_run_verdict("user-driven" if person_driven_capture else "verified-evidence", report)
    if report.of("completed", "improved") or any(
        outcome.activated
        for item in getattr(report, "items", ())
        for outcome in item.provider_outcomes
    ):
        ctx.jobs.run_write(ctx.rebuild_index)
        ctx.jobs.run_write(ctx.auto_push)
    return report.to_dict()


def _trace_run_verdict(mode: str, report) -> None:
    """One final line per part, naming the specific reason each provider route ended on."""

    try:
        for item in getattr(report, "items", ()) or ():
            trace(
                "capture.part.verdict",
                mode=mode,
                part=getattr(item, "part_id", ""),
                mpn=getattr(item, "mpn", ""),
                status=getattr(item, "status", ""),
                satisfied=list(getattr(item, "satisfied", ()) or ()),
                remaining=list(getattr(item, "remaining", ()) or ()),
                retained=getattr(item, "retained", 0),
                error=getattr(item, "error", ""),
            )
            for outcome in getattr(item, "provider_outcomes", ()) or ():
                trace(
                    "capture.route.verdict",
                    part=getattr(item, "part_id", ""),
                    route=outcome.route_id,
                    label=outcome.label,
                    status=outcome.status,
                    attempted=outcome.attempted,
                    activated=outcome.activated,
                    retained=outcome.retained,
                    why=outcome.reason,
                )
        counts = report.counts() if hasattr(report, "counts") else {}
        trace("capture.run.finish", mode=mode, counts=sorted(f"{k}={v}" for k, v in counts.items()))
    except Exception:  # noqa: BLE001 - the verdict trace never rewrites the verdict
        pass


def _utc_now_iso() -> str:
    """Stamped by the SERVER. A timestamp a caller can set is not evidence of when a file landed."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def capture_state_root() -> Path:
    """Return Stockroom's per-machine acquisition state root.

    Browser profiles contain authenticated cookies and downloads contain
    untrusted, not-yet-attached bytes. Neither belongs beside the Git-backed
    library. An explicit override keeps tests and portable installs isolated;
    Windows uses LocalAppData because this state is machine-local and can be
    large.
    """

    override = os.environ.get("STOCKROOM_CAPTURE_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Stockroom" / "Capture"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Stockroom" / "Capture"
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / "stockroom" / "capture"


def capture_candidates_root() -> Path:
    """Return the one retained-candidate store root, a sibling of the evidence store.

    Retained candidates are provider bytes plus the validation outcome Stockroom proved about
    them: the same machine-local, not-Git-backed, potentially large class of state the evidence
    store already lives in. So it is a sibling under the single capture root rather than a second
    tree with its own discovery rules, and it is defined HERE once so a writer and a reader can
    never disagree about where it is.
    """

    return capture_state_root() / "Candidates"


def durable_capture_report_path(item_id: str) -> Path:
    """Return the machine-local report path for one durable workflow item."""

    if type(item_id) is not str or _DURABLE_CAPTURE_ITEM_ID.fullmatch(item_id) is None:
        raise ValueError("durable capture item id is not a valid opaque reference")
    root = capture_state_root() / "Durable Capture Reports"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{item_id}.json"


def write_durable_capture_report(item_id: str, report: dict) -> None:
    """Atomically retain one bounded, already-sanitized capture result."""

    from stockroom.workflow.model import canonical_json

    if type(report) is not dict:
        raise TypeError("durable capture report must be a JSON object")
    payload = canonical_json(report).encode("utf-8")
    if len(payload) > _DURABLE_CAPTURE_REPORT_MAX_BYTES:
        raise ValueError("durable capture report exceeds the bounded result size")
    path = durable_capture_report_path(item_id)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_durable_capture_report(item_id: str) -> dict | None:
    """Read a retained report without accepting oversized or non-object data."""

    path = durable_capture_report_path(item_id)
    if not path.is_file():
        return None
    payload = path.read_bytes()
    if not payload or len(payload) > _DURABLE_CAPTURE_REPORT_MAX_BYTES:
        raise ValueError("durable capture report has an invalid size")
    try:
        report = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("durable capture report is not valid UTF-8 JSON") from exc
    if type(report) is not dict:
        raise ValueError("durable capture report is not a JSON object")
    return report


def _capture_downloads(_ctx, provider_key: str) -> Path:
    """Where captured files land before attachment, outside every Git checkout.

    ``ctx`` remains in the signature so all capture-path helpers share one call
    shape; the location is intentionally independent of the selected library.
    """
    from stockroom.capture.browser import provider_profile_dir

    root = provider_profile_dir(
        capture_state_root() / "Downloads",
        provider_key,
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _capture_evidence_root(_ctx) -> Path:
    """Machine-local immutable provider evidence, outside the Git library."""
    root = capture_state_root() / "Evidence"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _take(iterable, n: int):
    """islice that keeps the source lazy -- a limited run over a 10,000-part library must not
    walk all 10,000 first."""
    for i, item in enumerate(iterable):
        if i >= n:
            return
        yield item


# The executable fallback chain. DigiKey leads because one exact product page exposes distinct
# Ultra Librarian, SnapMagic, and TraceParts author routes and Stockroom preserves each route's
# provenance independently. Direct Ultra Librarian stays next (the preferred authored library),
# followed by SnapMagic and the SamacSys availability fallback. Exact identity, native readback,
# cross-EDA equivalence, and immutable evidence gate every attachment regardless of surface. Every
# entry is person-driven: the order is the order a person is offered these surfaces in, and no
# entry runs without one.
_VENDOR_CHAIN = ("digikey", "ultralibrarian", "snapmagic", "samacsys")


def _vendor_chain(vendor) -> list[str]:
    """Normalise `vendor` to an ordered list of adapter keys.

    None means the whole fallback chain. One key is a preferred starting provider, not an
    exclusive provider: every other implemented provider remains available as fallback. An
    explicit list is honored in order. Unknown providers fail honestly instead of silently
    running Ultra Librarian under a DigiKey or SamacSys label.
    """
    from stockroom.capture.vendors import get_adapter

    if vendor is None:
        wanted = list(_VENDOR_CHAIN)
    elif isinstance(vendor, str):
        if get_adapter(vendor) is None:
            raise ValueError(f"no network capture adapter for provider {vendor!r}")
        wanted = [vendor, *(key for key in _VENDOR_CHAIN if key != vendor)]
    else:
        wanted = list(vendor)
        unknown = [key for key in wanted if get_adapter(key) is None]
        if unknown:
            raise ValueError(
                f"no network capture adapter for {counted(len(unknown), 'provider')}: "
                + ", ".join(map(repr, unknown))
            )
    keys = list(dict.fromkeys(wanted))
    if not keys:
        raise ValueError("network capture requires at least one implemented provider")
    return keys
