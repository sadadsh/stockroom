"""Assemble the completion engine for a live app context.

This is the ONE place that knows which sources exist, how they are paced, and what a run
costs. Keeping it here means a route stays four lines and the numbers below sit next to the
measurement that produced them, rather than being scattered as literals across the API.

Active CAD is deliberately stricter than catalogue discovery.  A converted LCSC/EasyEDA
KiCad trio is not a dual-EDA source set and its authoring trust is not established merely
because the distributor identity matched.  It therefore cannot be registered as an active
completion source.  Verified local evidence and managed providers may publish only an exact
same-download KiCad + native Altium + STEP set.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from stockroom.capture.access_policy import (
    machine_access_authorized,
    machine_access_decision,
    machine_access_policy,
)
from stockroom.capture.complete import (
    ProviderOutcome,
    SourceOutcome,
    complete_library,
    iter_incomplete,
)
from stockroom.capture.digikey_models import default_digikey_models_ids
from stockroom.capture.intent import PersonCaptureIntent, person_capture_intent
from stockroom.capture.pacing import (
    CircuitBreaker,
    DurableSlidingWindowLimiter,
)
from stockroom.capture.trace import install_capture_log, trace
from stockroom.text import counted

# Five parts in a row all blocked is the catalogue having closed the door, not a burst edge.
_BREAKER_THRESHOLD = 5
_DURABLE_CAPTURE_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_DURABLE_CAPTURE_REPORT_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProviderRoutePlan:
    """One deterministic provider surface and CAD-author route."""

    provider_key: str
    author_key: str
    label: str

    @property
    def route_id(self) -> str:
        return f"{self.provider_key}:{self.author_key}"


class HumanRequiredSource:
    """Effect-free batch marker for a route that needs an explicit one-part session."""

    def __init__(
        self,
        provider_key: str,
        routes: tuple[ProviderRoutePlan, ...],
        provides,
        *,
        access_detail: str = "",
    ) -> None:
        from stockroom.capture.vendors import get_adapter

        self.key = f"{provider_key}-human-required"
        self.provider_key = provider_key
        self.author_key = provider_key
        adapter = get_adapter(provider_key)
        self.report_label = (
            routes[0].label
            if len(routes) == 1
            else adapter.capability.label
            if adapter is not None
            else provider_key
        )
        self._routes = routes
        self._provides = frozenset(provides)
        # WHY this provider was left to a person, when a reviewed exception exists and simply is
        # not active right now. Without it the report says only "needs a person-driven session",
        # which reads identically for a provider whose terms forbid automation and for one whose
        # per-machine authorization flag was never turned on.
        self._access_detail = " ".join(str(access_detail or "").split())

    def provides(self):
        return self._provides

    def provider_route_ids(self) -> tuple[str, ...]:
        return tuple(route.route_id for route in self._routes)

    def supply(self, _record) -> SourceOutcome:
        reason = (
            "requires an explicit one-part Collect All Sources session; automatic batch capture "
            "did not open a person-driven provider window"
        )
        if self._access_detail:
            reason = f"{reason} ({self._access_detail})"
        trace(
            "capture.route.deferred",
            provider=self.provider_key,
            label=self.report_label,
            routes=[route.route_id for route in self._routes],
            why=reason,
        )
        return SourceOutcome(
            skipped=reason,
            provider_outcomes=tuple(
                ProviderOutcome(
                    route_id=route.route_id,
                    provider_key=route.provider_key,
                    author_key=route.author_key,
                    label=route.label,
                    status="requires-human",
                    attempted=False,
                    reason=reason,
                )
                for route in self._routes
            ),
        )


def _provider_route_plan(provider_key: str) -> tuple[ProviderRoutePlan, ...]:
    """Expand an aggregator into stable author routes without opening a browser."""

    from stockroom.capture.vendors import get_adapter

    adapter = get_adapter(provider_key)
    if adapter is None:
        raise ValueError(f"no network capture adapter for provider {provider_key!r}")
    route_factory = getattr(adapter, "capture_routes", None)
    routes = tuple(route_factory()) if callable(route_factory) else (adapter,)
    planned: list[ProviderRoutePlan] = []
    seen: set[str] = set()
    for route in routes:
        author_key = (
            str(getattr(route, "evidence_provider_key", "") or provider_key).strip().casefold()
        )
        plan = ProviderRoutePlan(
            provider_key=provider_key,
            author_key=author_key,
            label=route.capability.label,
        )
        if plan.route_id in seen:
            raise ValueError(f"provider route plan repeats {plan.route_id!r}")
        seen.add(plan.route_id)
        planned.append(plan)
    if not planned:
        raise ValueError(f"provider {provider_key!r} has no implemented author route")
    return tuple(planned)


def _machine_access_detail(provider_key: str, *, config=None) -> str:
    """The sentence explaining a withheld machine-access exception, or "" when none applies.

    A provider with no reviewed exception at all is not "unauthorized" - person-driven IS its
    normal contract - so that case adds nothing and stays blank.
    """

    try:
        decision = machine_access_decision(provider_key, config=config)
    except Exception:  # noqa: BLE001 - an undescribable decision simply adds no detail
        return ""
    if decision.authorized or decision.signal == "no-reviewed-policy":
        return ""
    return decision.detail


def _trace_provider_routing(
    *,
    mode: str,
    vendor,
    config,
    provider_keys,
    automatic_provider_keys,
    deferred_keys,
) -> None:
    """Say WHY every registered provider is in, out, or deferred, before any page opens.

    This is the first question a failed run raises and the one the report could never answer: the
    owner saw "no complete CAD package" with no way to tell an unauthorized provider from an
    absent one. Every fact logged here is already a decision input elsewhere in this module, so
    the trace cannot disagree with the run. Wrapped whole: describing a route may never break one.
    """

    try:
        from stockroom.capture.vendors import get_adapter

        automatic = set(automatic_provider_keys)
        selected = list(provider_keys)
        deferred = set(deferred_keys)
        trace(
            "capture.route.order",
            mode=mode,
            preferred=str(vendor or ""),
            selected=selected,
            automatic=sorted(automatic),
            deferred=sorted(deferred),
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
            decision = machine_access_decision(key, config=config)
            included = key in selected
            if included and key in automatic:
                lane = "automatic"
            elif included:
                lane = "explicit-provider"
            elif key in deferred:
                lane = "deferred-to-person"
            else:
                lane = "excluded"
            trace(
                "capture.route.provider",
                provider=key,
                label=adapter.capability.label,
                included=included,
                lane=lane,
                browser_access=adapter.capability.browser_access,
                operator_automation=adapter.capability.operator_automation,
                machine_access=decision.authorized,
                access_signal=decision.signal,
                access_why=decision.detail,
                exception_code=decision.exception_code,
                formats=sorted(adapter.capability.supported_formats),
                engine=adapter.capability.browser_engine,
            )
    except Exception:  # noqa: BLE001 - the routing trace is never a routing decision
        pass


def _provider_requirements(provider_key: str):
    """Requirements exposed by the registered provider's accepted format set."""

    from stockroom.capture.requirements import Requirement
    from stockroom.capture.vendors import get_adapter

    adapter = get_adapter(provider_key)
    if adapter is None:
        return frozenset()
    formats = set(adapter.capability.supported_formats)
    requirements: set[Requirement] = set()
    if "kicad" in formats:
        requirements |= {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}
    if "model" in formats:
        requirements.add(Requirement.KICAD_MODEL)
    if "altium" in formats:
        requirements |= {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}
    return frozenset(requirements)


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

    The action totals are reported separately. `needs_files` counts parts an automatic source can
    improve, `needs_assistance` counts parts whose gaps overlap a managed user-driven provider,
    and `unsourced` counts parts with a real gap that neither lane can fill. The first two may
    overlap: a part can gain KiCad automatically and still need an assisted native-Altium export.
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
    browser_source_keys: list[str] = []
    assisted_source_keys: list[str] = []
    assisted_can_provide = set()
    # Lightweight coverage callers and isolated audit fixtures do not necessarily own the
    # desktop MachineConfig.  Absence must mean the public/default authorization policy, not an
    # AttributeError that prevents an empty library from reporting coverage at all.
    automatic_browser_keys = set(
        _automatic_provider_keys(None, config=getattr(ctx, "config", None))
    )
    for key in _vendor_chain(None):
        adapter = get_adapter(key)
        if adapter is None:
            continue
        if key in automatic_browser_keys:
            browser_source_keys.append(key)
            destination = can_provide
        else:
            assisted_source_keys.append(key)
            destination = assisted_can_provide
        pins = set(adapter.capability.supported_formats)
        if "kicad" in pins:
            destination |= {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}
        if "model" in pins:
            destination.add(Requirement.KICAD_MODEL)
        if "altium" in pins:
            destination |= {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}

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
        "sources": [s.key for s in direct_sources] + browser_source_keys,
        "can_provide": sorted(r.value for r in can_provide),
        "assisted_sources": assisted_source_keys,
        "assisted_can_provide": sorted(r.value for r in assisted_can_provide),
    }


def run_completion(ctx, *, progress=None, should_stop=None, part_ids=None, limit=None) -> dict:
    """Run the same automatic acquisition ladder for one part or the whole library.

    `part_ids` narrows the run to a chosen set (one part, or a filtered list); omitted, the
    worklist is DERIVED from the library, which is what makes a stopped run resumable by
    simply running it again. Verified local evidence runs before managed-browser providers, so the
    bulk surface and Complete Part cannot disagree about which gaps are fillable.
    """
    return run_guided_capture(
        ctx,
        part_ids=part_ids,
        progress=progress,
        should_stop=should_stop,
        limit=limit,
        user_driven=False,
    )


def run_guided_capture(
    ctx,
    *,
    part_ids=None,
    vendor=None,
    progress=None,
    should_stop=None,
    limit=None,
    headless: bool = False,
    engine: str = "",
    user_driven: bool = False,
    operator_authorized: bool = False,
    finish_first: bool = False,
    collect_all: bool = False,
    capture_id: str | None = None,
    allow_standalone_browser: bool = False,
) -> dict:
    """Complete CAD automatically, with person-controlled capture only as an explicit fallback.

    The default path performs the least-expensive work first: verified local evidence, then any
    provider transport with a reviewed machine-access contract.
    Commercial browser providers remain available only through the explicit assisted fallback when
    their policy requires user control; Stockroom still opens the exact page, intercepts every
    download, validates it, and attaches it. A preferred ``vendor`` changes provider order where
    policy permits machine access.

    ``operator_authorized=True`` is the normal explicit-provider lane. One selected part and one
    selected provider authorize Stockroom to use saved login state and operate ordinary export
    controls for that job only. CAPTCHA, MFA, passkeys, and security checks still stop for the
    person. ``user_driven=True`` retains the raw browser fallback for a provider whose ordinary
    controls have no implemented adapter.
    """
    if (
        type(user_driven) is not bool
        or type(operator_authorized) is not bool
        or type(finish_first) is not bool
        or type(collect_all) is not bool
        or type(allow_standalone_browser) is not bool
    ):
        raise TypeError("capture authorization flags must be booleans")
    if user_driven and operator_authorized:
        raise ValueError("capture cannot be both user-driven and operator-authorized automation")
    if finish_first and collect_all:
        raise ValueError("finish-first and collect-all are mutually exclusive")
    sequential_providers = finish_first or collect_all
    if sequential_providers and (user_driven or operator_authorized):
        raise ValueError("sequential capture owns its provider authorization plan")
    if sequential_providers and headless:
        raise ValueError("sequential capture requires visible provider handoffs")
    from threading import Event

    workflow_cancelled = Event()
    # What the PERSON says about the capture in front of them. It is published under the one
    # selected part below (see `capture/intent.py`) and reaches this run through the SAME polled
    # predicates cancellation already uses, because that is the channel that demonstrably reaches
    # a running person-driven window. A library-wide automatic pass opens no such window, so its
    # intent is simply never published and nothing can signal it.
    person_intent = PersonCaptureIntent()
    explicit_provider_capture = user_driven or operator_authorized
    exact_part_id: str | None = None
    capture_mode = (
        "collect-all"
        if collect_all
        else "finish-first"
        if finish_first
        else "assisted"
        if operator_authorized
        else "user-driven"
        if user_driven
        else "automatic"
    )
    trace(
        "capture.run.start",
        mode=capture_mode,
        preferred_provider=str(vendor or ""),
        parts=(len(list(part_ids)) if isinstance(part_ids, (list, tuple)) else "derived"),
        limit=limit,
        headless=headless,
        engine=engine or "capability-default",
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

    if explicit_provider_capture or sequential_providers:
        if part_ids is None or isinstance(part_ids, (str, bytes)):
            scope = "sequential capture" if sequential_providers else "explicit provider capture"
            raise ValueError(f"{scope} requires exactly one selected part")
        selected_parts = list(part_ids)
        if (
            len(selected_parts) != 1
            or not isinstance(selected_parts[0], str)
            or not selected_parts[0].strip()
            or selected_parts[0] != selected_parts[0].strip()
        ):
            scope = "sequential capture" if sequential_providers else "explicit provider capture"
            raise ValueError(f"{scope} requires exactly one selected part")
        if not sequential_providers and (not isinstance(vendor, str) or not vendor.strip()):
            raise ValueError("explicit provider capture requires one selected provider")
        if limit is not None:
            scope = "sequential capture" if sequential_providers else "explicit provider capture"
            raise ValueError(f"{scope} does not accept a batch limit; select exactly one part")
        part_ids = selected_parts
        exact_part_id = selected_parts[0]
        if sequential_providers:
            # Preference reorders one lane; it never removes a registered provider.
            provider_order = _vendor_chain(vendor)
            automatic_provider_keys = _automatic_provider_keys(
                vendor,
                config=ctx.config,
            )
            provider_keys = _automation_first_order(
                provider_order,
                automatic_provider_keys,
            )
            if finish_first:
                # Normal completion is one-provider ownership, not a silent source mixer. The
                # first eligible provider gets the attempt; another provider is an explicit next
                # action. Collect-all deliberately retains the exhaustive chain.
                provider_keys = (
                    [vendor.strip().lower()]
                    if isinstance(vendor, str) and vendor.strip()
                    else provider_keys[:1]
                )
                automatic_provider_keys = [
                    key for key in automatic_provider_keys if key in provider_keys
                ]
        else:
            # One click authorizes ordinary controls on exactly the provider the person selected.
            # It is not standing permission to operate a different commercial account or a batch.
            assert isinstance(vendor, str)
            provider_keys = [vendor.strip().lower()]
            automatic_provider_keys = []
    else:
        # Automatic mode may construct only transports with a reviewed machine-access contract.
        # Other browser providers are exposed through the explicit assisted route after permitted
        # automatic sources have exhausted.
        provider_keys = _automatic_provider_keys(vendor, config=ctx.config)
        automatic_provider_keys = list(provider_keys)

    from stockroom.capture.browser import SharedPlaywrightRuntime
    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.capture.projection import verify_installed_projection
    from stockroom.capture.vendors import get_adapter
    from stockroom.capture.verified_cache import record_completion_evidence
    from stockroom.evidence import EvidenceStore
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        return IngestPipeline(
            ctx.profile,
            ctx.repo,
            ctx.cli,
            auto_embed_altium_models=True,
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

    if sequential_providers:
        from stockroom.capture.evidence import exact_identity

        # Fail before constructing a provider runtime or opening a page. A search-only MPN or a
        # manufacturer-free record is not an exact collection task.
        assert exact_part_id is not None
        exact_identity(ctx.ops.load_record(exact_part_id))

    provider_engines = {}
    for key in provider_keys:
        adapter = get_adapter(key)
        provider_engines[key] = engine or (
            adapter.capability.browser_engine if adapter is not None else "chromium"
        )
    playwright_runtime = (
        SharedPlaywrightRuntime()
        if any(selected not in {"camoufox", "cloak"} for selected in provider_engines.values())
        else None
    )

    automatic_provider_set = set(automatic_provider_keys)
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
    # history before any source is built. Person-driven capture opens the owner's real browser and
    # hands the window back to them, so `final_url` no longer teaches Stockroom anything and this
    # is the only remaining way a NEW id is ever learned. Opt-in and default off; when it is off
    # this is a dictionary lookup and nothing more. See `capture/models_history.py`.
    models_ids = default_digikey_models_ids() if "digikey" in provider_keys else None
    if models_ids is not None:
        from stockroom.capture.models_history import learn_models_ids_for_library

        learn_models_ids_for_library(ctx, store=models_ids)

    def make_guided_source(key: str):
        from stockroom.capture.vendors import get_adapter

        adapter = get_adapter(key)
        if adapter is None:
            raise ValueError(f"no network capture adapter for provider {key!r}")
        automatic_source = key in automatic_provider_set
        if sequential_providers:
            source_user_driven = not automatic_source and not adapter.capability.operator_automation
            source_operator_authorized = not automatic_source and not source_user_driven
        else:
            source_user_driven = user_driven or (
                operator_authorized and not adapter.capability.operator_automation
            )
            source_operator_authorized = operator_authorized and not source_user_driven
        policy = machine_access_policy(key) if automatic_source else None
        if automatic_source and (policy is None or policy.max_concurrency != 1):
            raise ValueError(
                f"{key} automatic capture lacks an enforceable serial machine-access policy"
            )
        rate_limiter = (
            DurableSlidingWindowLimiter(
                _capture_rate_ledger(ctx, key),
                policy.starts_per_window,
                policy.window_seconds,
            )
            if policy is not None
            else None
        )
        return GuidedCaptureSource(
            make_pipeline,
            vendor=key,
            download_root=_capture_downloads(ctx, key),
            profile_dir=_capture_profile(ctx, key),
            headless=headless,
            # Stockroom's version-pinned Playwright Chromium owns the normal path. An installed
            # user browser is not part of the product contract and cannot silently change the
            # automation version underneath a provider adapter. Camoufox and branded channels
            # remain explicit provider-specific experiments, never the default.
            engine=provider_engines[key],
            # Both the direct and DigiKey-aggregated Ultra Librarian paths can deliver legacy
            # P-CAD/script packages when native Altium libraries are unavailable. Inject the
            # content-recognizing converter at the provider-surface boundary: it returns ``None``
            # for unrelated archives, so a person-selected UL package can still be recovered if
            # the assisted DigiKey surface advanced to another author route before the picker
            # returned. Identity and coherent-pair validation remain downstream and unchanged.
            convert_altium=(
                _convert_ul_altium_package
                if key in {"digikey", "ultralibrarian"}
                else None
            ),
            collect_variants=explicit_provider_capture or collect_all,
            preserve_active_pair=collect_all,
            close_after_supply=sequential_providers,
            single_provider_attempt=finish_first,
            # Credentials are supplied only to providers whose reviewed policy explicitly permits
            # machine access. User-driven providers retain their session in the isolated profile
            # without Stockroom impersonating provider-side choices.
            credentials=None if source_user_driven else _saved_credentials,
            run_write=ctx.jobs.run_write,
            now_iso=_utc_now_iso,
            evidence_store=evidence_store,
            projection_verifier=lambda record, resolved, *, validation_reports=None: verify_installed_projection(
                ctx.profile.library,
                record,
                resolved,
                validation_reports=validation_reports,
            ),
            playwright_runtime=playwright_runtime,
            user_driven=source_user_driven,
            operator_authorized=source_operator_authorized,
            user_cancelled=capture_should_stop,
            # "No more is coming from this page", consumed by whichever route is open when the
            # person says it. Without this the seam existed and was never passed, so a
            # person-driven route could only end on cancel, ~25 s of quiet after a file landed,
            # or the 600 s timeout - five times over for DigiKey's five author routes.
            user_finished=person_intent.take_route_finish,
            cancel_workflow=workflow_cancelled.set,
            rate_limiter=rate_limiter,
            # Re-load the non-secret authorization flag and kill switches immediately before
            # every provider attempt. Revocation therefore stops an already-constructed run.
            machine_access_check=(
                (
                    lambda provider_key=key: _machine_access_allowed(
                        provider_key,
                        config=ctx.config,
                    )
                )
                if policy is not None
                else None
            ),
            # DigiKey only, because DigiKey is the only surface with a per-part models page and a
            # provider tab to land on. It carries the opaque id learned from the person's own
            # navigation so their SECOND visit to a part skips the search they already did; every
            # other provider, and every first visit, is untouched.
            models_ids=models_ids if key == "digikey" else None,
            # Configured Product Information V4 credentials make DigiKey's exact ProductDetails
            # and Media response authoritative. Do not silently replace a missing exact route
            # with a provider-wide search page; surface the missing route to the operator.
            strict_catalog_urls=bool(
                getattr(ctx.config, "digikey_client_id", "")
                and getattr(ctx.config, "digikey_client_secret", "")
            ),
            provider_surface=provider_surface,
            allow_standalone_browser=allow_standalone_browser,
            publish_active_route=person_intent.set_active_route,
            clear_active_route=person_intent.clear_active_route,
            take_selected_files=person_intent.take_selected_files,
        )

    guided_sources = [make_guided_source(key) for key in provider_keys]
    deferred_sources = []
    deferred_keys: list[str] = []
    if not explicit_provider_capture and not sequential_providers:
        deferred_keys = [key for key in _vendor_chain(vendor) if key not in automatic_provider_set]
        deferred_sources = [
            HumanRequiredSource(
                key,
                _provider_route_plan(key),
                _provider_requirements(key),
                access_detail=_machine_access_detail(key, config=ctx.config),
            )
            for key in deferred_keys
        ]
    _trace_provider_routing(
        mode=capture_mode,
        vendor=vendor,
        config=getattr(ctx, "config", None),
        provider_keys=provider_keys,
        automatic_provider_keys=automatic_provider_keys,
        deferred_keys=deferred_keys,
    )
    # Verified local evidence is the zero-interaction first lane. If it fills the remaining
    # KiCad requirements, GuidedCaptureSource is never asked and no browser window opens.
    sources = (
        [*guided_sources]
        if explicit_provider_capture
        else [
            *build_sources(
                ctx,
                run_write=ctx.jobs.run_write,
                paced=False,
                evidence_store=evidence_store,
                preserve_active_pair=collect_all,
            ),
            *guided_sources,
            *deferred_sources,
        ]
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
                collect_variants=explicit_provider_capture or collect_all,
                exhaustive=collect_all,
                evidence_resolver=completion_evidence_resolver,
            )
    finally:
        for source in guided_sources:
            source.close()
        if playwright_runtime is not None:
            playwright_runtime.close()

    _trace_run_verdict(capture_mode, report)
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


def _capture_profile(_ctx, provider_key: str) -> Path:
    """The persistent browser profile holding vendor sign-ins.

    PER-MACHINE, and it is the permitted kind: it holds session cookies only, so it cannot change
    what the library renders the way a per-machine enrich cache can. It is what makes a 90-part
    sitting cost ONE sign-in. Every provider has an isolated profile and an explicit session lock.
    """
    from stockroom.capture.browser import provider_profile_dir

    root = provider_profile_dir(
        capture_state_root() / "Profiles",
        provider_key,
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _capture_evidence_root(_ctx) -> Path:
    """Machine-local immutable provider evidence, outside the Git library."""
    root = capture_state_root() / "Evidence"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _capture_rate_ledger(_ctx, provider_key: str) -> Path:
    """Durable provider-start ledger, separate from credentials and Git state."""

    from stockroom.capture.browser import provider_profile_dir

    root = provider_profile_dir(
        capture_state_root() / "Rate Limits",
        provider_key,
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / "Starts.json"


def _take(iterable, n: int):
    """islice that keeps the source lazy -- a limited run over a 10,000-part library must not
    walk all 10,000 first."""
    for i, item in enumerate(iterable):
        if i >= n:
            return
        yield item


# Where each vendor's saved sign-in lives in the machine config. DATA, not a branch: adding a
# vendor is adding a row here, never an `if vendor == ...` inside the capture engine.
_CREDENTIAL_FIELDS = {
    "digikey": ("digikey_username", "digikey_password"),
    "ultralibrarian": ("ul_username", "ul_password"),
    "snapmagic": ("snapeda_username", "snapeda_password"),
    "samacsys": ("samacsys_username", "samacsys_password"),
}


def _saved_credentials(vendor_key: str):
    """`(username, password)` for a vendor, or None when nothing is saved.

    Read at CALL time rather than captured at construction, so a sign-in saved in Settings takes
    effect on the next run without restarting the app. Returns None rather than a blank pair when
    either half is missing, because a half-filled credential is not a credential and the adapter
    should report "nothing saved" rather than fail an empty login.
    """
    from stockroom.store.machine_config import MachineConfig

    fields = _CREDENTIAL_FIELDS.get(vendor_key)
    if not fields:
        return None
    try:
        cfg = MachineConfig.load()
    except Exception:  # noqa: BLE001 - an unreadable config is "no credentials", never a crash
        return None
    user = (getattr(cfg, fields[0], "") or "").strip()
    secret = getattr(cfg, fields[1], "") or ""
    if not user or not secret:
        return None
    return user, secret


# The executable fallback chain. DigiKey leads because one exact product page exposes distinct
# Ultra Librarian, SnapMagic, and TraceParts author routes and Stockroom preserves each route's
# provenance independently. Direct Ultra Librarian stays next (the preferred authored library),
# followed by SnapMagic and the person-driven SamacSys availability fallback. Exact identity,
# native readback, cross-EDA equivalence, and immutable evidence gate every attachment regardless
# of surface. Machine-access policy still decides which entries may run unattended.
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


def _automatic_provider_keys(vendor, *, config=None) -> list[str]:
    """Reviewed adapters whose per-machine authorization is active right now."""

    from stockroom.capture.vendors import get_adapter

    return [
        key
        for key in _vendor_chain(vendor)
        if (
            (adapter := get_adapter(key)) is not None
            and adapter.capability.browser_access == "machine_allowed"
            and _machine_access_allowed(key, config=config)
        )
    ]


def _automation_first_order(
    provider_order,
    automatic_provider_keys,
) -> list[str]:
    """Order a collect-all run so a person is asked only after automation is exhausted.

    Collect All Sources is exhaustive -- every registered provider is visited -- so this decides
    ONLY the order, never the membership. Order is nevertheless the whole difference between a
    hands-off run and a person-driven one, because a cancelled person-driven window cancels the
    REST of the run: `guided.py::_supply_user_driven_route` calls `cancel_workflow` on cancel, and
    `guided.py::_supply_once` then skips every remaining provider. With DigiKey ahead of SnapMagic
    in `_VENDOR_CHAIN`, closing DigiKey's window therefore threw away a SnapMagic route that
    needed nobody at all.

    Three stable lanes, with the caller's preference order preserved inside each:

      1. reviewed machine-access transports, which run with no person present;
      2. providers whose ordinary export controls this one explicit selection authorizes;
      3. providers whose controls stay person-driven under their terms of use.

    Lane membership is read from capability data, never asserted here, so this cannot promote a
    provider past the access policy its adapter declares.
    """

    from stockroom.capture.vendors import get_adapter

    automatic = set(automatic_provider_keys)
    lanes: tuple[list[str], list[str], list[str]] = ([], [], [])
    for key in dict.fromkeys([*automatic_provider_keys, *provider_order]):
        if key in automatic:
            lane = 0
        else:
            adapter = get_adapter(key)
            lane = 1 if adapter is not None and adapter.capability.operator_automation else 2
        lanes[lane].append(key)
    return [*lanes[0], *lanes[1], *lanes[2]]


def _machine_access_allowed(provider_key: str, *, config=None) -> bool:
    """Call the authorization seam with live config when its contract accepts it.

    Stockroom's production authorizer accepts ``config=`` so an in-flight run sees the same
    machine state as its app context. Narrow injected authorizers may intentionally expose only
    ``(provider_key)``; inspecting the callable keeps that stable seam without catching a
    ``TypeError`` raised inside the authorization decision itself.
    """

    parameters = inspect.signature(machine_access_authorized).parameters.values()
    accepts_config = "config" in {parameter.name for parameter in parameters} or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    if config is not None and accepts_config:
        return machine_access_authorized(provider_key, config=config)
    return machine_access_authorized(provider_key)
