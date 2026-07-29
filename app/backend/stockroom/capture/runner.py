"""Assemble the completion engine for a live app context.

This is the ONE place that knows which sources exist, how they are paced, and what a run
costs. Keeping it here means a route stays four lines and the numbers below sit next to the
measurement that produced them, rather than being scattered as literals across the API.

**The pacing numbers are MEASURED, not chosen.** 2026-07-27, against the real catalogue:

* `--full` conversion costs roughly TWO EasyEDA API calls per part (component data, then the
  STEP model).
* A cold probe at one call every two seconds got 19 through and was blocked on the 20th, at
  t=44s. An earlier unpaced run got ~11 PARTS through before blocking. Both point at the same
  ceiling: about 20 calls per 60-second window.
* The block cleared on its own in about 60 seconds, so it is a cooldown, not a ban.

So `_PARTS_PER_WINDOW = 8` per 60s leaves headroom under a ~10-parts/minute ceiling. The
honest consequence, stated rather than buried: 10,000 parts is roughly 21 hours of wall clock.
That is exactly why the run is stoppable and why resuming is free.
"""

from __future__ import annotations

import os
from pathlib import Path

from stockroom.capture.access_policy import (
    machine_access_authorized,
    machine_access_policy,
)
from stockroom.capture.complete import complete_library, iter_incomplete
from stockroom.capture.pacing import (
    CircuitBreaker,
    DurableSlidingWindowLimiter,
    PacedSource,
)
from stockroom.capture.sources import LcscSource
from stockroom.enrich.ratelimit import SlidingWindowLimiter
from stockroom.text import counted

# See the module docstring: 8 parts x ~2 calls = ~16 calls per 60s, under the measured ~20.
_PARTS_PER_WINDOW = 8
_WINDOW_SECONDS = 60.0
# Two retries at 15s then 30s spans the ~60s cooldown without pinning a worker for minutes.
_RETRIES = 2
_RETRY_BACKOFF = 15.0
# Five parts in a row all blocked is the catalogue having closed the door, not a burst edge.
_BREAKER_THRESHOLD = 5


def build_sources(ctx, *, run_write=None, paced: bool = True):
    """The asset sources for this context, cheapest first.

    Order is the policy: an offline answer must always be tried before a network one, because
    at 10,000 parts the difference is hours. `paced=False` is for a single part, where the
    limiter would add a pointless wait.
    """
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        # A fresh pipeline per part: it owns its sandbox and tears it down, so a long run
        # holds one tree at a time rather than one per part.
        return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)

    from stockroom.enrich.fetch import HttpFetcher

    fetcher = HttpFetcher()

    def resolve_online(mpn: str) -> str:
        """The free, keyless jlcsearch catalogue: MPN -> LCSC part number. Only reached when
        the record itself carries no id, which is 20 of the owner's 66 file-less parts."""
        from stockroom.enrich.jlcsearch import JlcSearchClient

        hit = JlcSearchClient(fetcher).search(mpn)
        return (getattr(hit, "lcsc", "") or "") if hit is not None else ""

    def resolve_identity(lcsc_id: str):
        """LCSC C-number -> independent manufacturer + MPN evidence from its product page."""
        from stockroom.enrich.sites.lcsc import parse_lcsc_product

        url = f"https://www.lcsc.com/product-detail/{lcsc_id.upper()}.html"
        page = fetcher.get(url)
        if not 200 <= page.status < 300:
            raise RuntimeError(f"product page returned HTTP {page.status}")
        product = parse_lcsc_product(page.text)
        if product is None:
            raise RuntimeError("product page exposed no structured identity")
        return product

    lcsc = LcscSource(
        make_pipeline,
        resolve_online=resolve_online,
        resolve_identity=resolve_identity,
        run_write=run_write,
        now_iso=_utc_now_iso,
    )
    if not paced:
        return [lcsc]
    return [
        PacedSource(
            lcsc,
            limiter=SlidingWindowLimiter(_PARTS_PER_WINDOW, _WINDOW_SECONDS),
            retries=_RETRIES,
            backoff=_RETRY_BACKOFF,
        )
    ]


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
    from stockroom.capture.requirements import Requirement
    from stockroom.capture.vendors import get_adapter

    direct_sources = build_sources(ctx, paced=False)
    can_provide = set()
    for source in direct_sources:
        can_provide |= set(source.provides())
    browser_source_keys: list[str] = []
    assisted_source_keys: list[str] = []
    assisted_can_provide = set()
    automatic_browser_keys = set(_automatic_provider_keys(None))
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
        from stockroom.capture.requirements import capture_needs

        needs = capture_needs(record)
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
    simply running it again. Direct/keyless sources run before managed-browser providers, so the
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
    engine: str = "chromium",
    user_driven: bool = False,
) -> dict:
    """Complete CAD automatically, with person-controlled capture only as an explicit fallback.

    The default path performs the least-expensive work first: keyless direct catalogue retrieval,
    deterministic generators, and any provider transport with a reviewed machine-access contract.
    Commercial browser providers remain available only through the explicit assisted fallback when
    their policy requires user control; Stockroom still opens the exact page, intercepts every
    download, validates it, and attaches it. A preferred ``vendor`` changes provider order where
    policy permits machine access.

    ``user_driven=True`` is the last-resort lane for a provider gate Stockroom cannot cross. It is
    deliberately scoped to one part and one preferred provider: the person handles each provider
    page while Stockroom still owns download interception, validation, attachment, and advancing
    to another provider when the preferred one cannot close every remaining gap.
    """
    if type(user_driven) is not bool:
        raise TypeError("user_driven must be a boolean")
    from threading import Event

    workflow_cancelled = Event()

    def capture_should_stop() -> bool:
        return workflow_cancelled.is_set() or bool(should_stop and should_stop())

    if user_driven:
        if part_ids is None or isinstance(part_ids, (str, bytes)):
            raise ValueError("user-driven capture requires exactly one selected part")
        selected_parts = list(part_ids)
        if (
            len(selected_parts) != 1
            or not isinstance(selected_parts[0], str)
            or not selected_parts[0].strip()
            or selected_parts[0] != selected_parts[0].strip()
        ):
            raise ValueError("user-driven capture requires exactly one selected part")
        if not isinstance(vendor, str) or not vendor.strip():
            raise ValueError("user-driven capture requires one selected provider")
        if limit is not None:
            raise ValueError(
                "user-driven capture does not accept a batch limit; select exactly one part"
            )
        part_ids = selected_parts
        # The selected provider is first, not exclusive. "Try Another Provider" in Stockroom's
        # browser HUD can therefore end the current page and advance within this same resumable
        # job instead of making the person return to the app and start another capture.
        provider_keys = _vendor_chain(vendor.strip().lower())
    else:
        # Automatic mode may construct only transports with a reviewed machine-access contract.
        # Other browser providers are exposed through the explicit assisted route after permitted
        # automatic sources have exhausted.
        provider_keys = _automatic_provider_keys(vendor)

    from stockroom.capture.browser import SharedPlaywrightRuntime
    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.evidence import EvidenceStore
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)

    evidence_store = EvidenceStore(_capture_evidence_root(ctx))
    playwright_runtime = (
        SharedPlaywrightRuntime() if provider_keys and engine != "camoufox" else None
    )

    def make_guided_source(key: str):
        from stockroom.capture.vendors import get_adapter

        adapter = get_adapter(key)
        if adapter is None:
            raise ValueError(f"no network capture adapter for provider {key!r}")
        policy = machine_access_policy(key) if not user_driven else None
        if not user_driven and (policy is None or policy.max_concurrency != 1):
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
            engine=engine,
            # The Altium seam, which already existed and was already atomic but which guided capture
            # never called - so a vendor shipping real .SchLib/.PcbLib had them downloaded and
            # dropped. Passed in rather than imported so capture/ stays clear of the mutation layer.
            attach_altium=ctx.ops.attach_altium_assets,
            # Credentials are supplied only to providers whose reviewed policy explicitly permits
            # machine access. User-driven providers retain their session in the isolated profile
            # without Stockroom impersonating provider-side choices.
            credentials=None if user_driven else _saved_credentials,
            run_write=ctx.jobs.run_write,
            now_iso=_utc_now_iso,
            evidence_store=evidence_store,
            playwright_runtime=playwright_runtime,
            user_driven=user_driven,
            user_cancelled=capture_should_stop,
            cancel_workflow=workflow_cancelled.set,
            rate_limiter=rate_limiter,
            # Re-load the non-secret authorization flag and kill switches immediately before
            # every provider attempt. Revocation therefore stops an already-constructed run.
            machine_access_check=(
                (lambda provider_key=key: machine_access_authorized(provider_key))
                if policy is not None
                else None
            ),
        )

    guided_sources = [make_guided_source(key) for key in provider_keys]
    # Direct/keyless acquisition is the zero-interaction first lane. If it fills the remaining
    # KiCad requirements, GuidedCaptureSource is never asked and no browser window opens.
    sources = (
        guided_sources
        if user_driven
        else [
            *build_sources(ctx, run_write=ctx.jobs.run_write, paced=False),
            *guided_sources,
        ]
    )
    load_record = ctx.ops.load_record

    if part_ids is None:
        work = iter_incomplete(
            ctx.profile.library.parts_dir, load_record=load_record, sources=sources
        )
        total = None
    else:
        work = list(part_ids)
        total = len(work)
    if limit is not None:
        work = _take(work, limit)
        total = min(total, limit) if total is not None else None

    try:
        report = complete_library(
            work,
            load_record=load_record,
            sources=sources,
            on_progress=progress,
            should_stop=capture_should_stop,
            total=total,
            breaker=CircuitBreaker(threshold=_BREAKER_THRESHOLD),
        )
    finally:
        for source in guided_sources:
            source.close()
        if playwright_runtime is not None:
            playwright_runtime.close()

    if report.of("completed", "improved"):
        ctx.jobs.run_write(ctx.rebuild_index)
        ctx.jobs.run_write(ctx.auto_push)
    return report.to_dict()


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


# The vendor chain, in trust order. Ultra Librarian's manufacturer-verified/source-built assets and
# current native Altium export are preferred; SnapMagic is the availability fallback. Exact identity, native
# readback, cross-EDA equivalence, and immutable evidence still gate every attachment regardless of
# source. A caller can explicitly prefer another provider for one run without changing this default.
_VENDOR_CHAIN = ("ultralibrarian", "snapmagic")


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


def _automatic_provider_keys(vendor) -> list[str]:
    """Reviewed adapters whose per-machine authorization is active right now."""

    from stockroom.capture.vendors import get_adapter

    return [
        key
        for key in _vendor_chain(vendor)
        if (
            (adapter := get_adapter(key)) is not None
            and adapter.capability.browser_access == "machine_allowed"
            and machine_access_authorized(key)
        )
    ]
