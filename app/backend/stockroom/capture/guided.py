"""Guided capture as an ASSET SOURCE: one component, or the whole library, same code.

Owner, 2026-07-27: *"always make the easiest workflow"*, *"i also need guided capture per
component"*, and *"i need all systems to work exactly the same on linux and windows so anything u
verify easily can be the same on windows"*.

WHY THIS IS A `Source` AND NOT A NEW SUBSYSTEM
`capture/complete.py` already owns everything hard about running over a library: a streaming
worklist derived per run (so stopping and re-running resumes for free), one record in memory, one
atomic commit per part, a circuit breaker, and an honest per-part report. Guided capture needed all
of that and none of it is vendor-specific. So this is a source that plugs into that engine, which
means:

  * **per component** is `part_ids=[one]`,
  * **the whole library** is the derived worklist,

and they are the SAME code path, so verifying one verifies the other. Writing a second "capture a
part" flow beside the existing "complete the library" flow is precisely the stray duplication that
makes a green test say nothing about what the owner experiences.

ONE BROWSER FOR THE WHOLE RUN
The session is opened lazily on the first part that needs it and closed by the runner at the end.
That matters for the workflow the owner actually has: a sitting must cost ONE sign-in, not one per
part. The persistent per-provider profile then carries that sign-in to later runs.

WHAT IT DOES NOT DO
It never operates a provider control. The person navigates within the page, picks the formats,
signs in, accepts the licence, clears the security check, and starts the download; this module
opens the exact page, names the files it needs, and stages, validates, and attaches what arrives.

It never invents a file either. If the provider offers nothing, the part is reported skipped and
left exactly as it was, because a capture that fabricates a partial answer is worse than one that
says "nothing here".
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

from stockroom.capture.browser import (
    CaptureBrowserError,
    ProviderHudSpec,
    ProviderSurfaceCapture,
)
from stockroom.capture.cad_composition import OwnedMaterialization
from stockroom.capture.complete import (
    ProviderOutcome,
    ProviderOutcomeStatus,
    SourceOutcome,
    provider_outcome_from_source,
)
from stockroom.capture.cross_eda import verify_cross_eda_component
from stockroom.capture.digikey_models import digikey_models_id, digikey_models_url
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.evidence import (
    BROWSER_CAPTURE_ADAPTER_VERSION,
    exact_identity,
    record_browser_cad_evidence,
)
from stockroom.capture.identity import (
    exact_catalog_observation_error,
    exact_observation_error,
    page_identity,
    provider_url_allowed,
    select_exact_candidate,
)
from stockroom.capture.requirements import Requirement, asset_present, capture_needs
from stockroom.capture.trace import (
    file_note,
    trace,
    trace_warning,
    url_note,
)
from stockroom.capture.vendors import (
    VendorCapability,
    formats_for,
    get_adapter,
)
from stockroom.capture.verified_cache import active_pair_is_verified
from stockroom.capture.verified_pair import resolve_verified_pair
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.asset import AssetOrigin
from stockroom.text import counted


def _account_verification_blocker(url: str) -> str:
    """Translate a provider-owned verification redirect into an honest blocked verdict."""

    parsed = urlparse(url or "")
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").rstrip("/").casefold()
    if host in {"snapeda.com", "www.snapeda.com", "snapmagic.com", "www.snapmagic.com"} and (
        path == "/profiles/verify"
    ):
        return (
            "SnapMagic requires this account's one-time phone verification before it will issue "
            "CAD files. Finish that verification in Stockroom's embedded provider tab; the saved "
            "provider session will be reused afterward."
        )
    return ""


def _captured_file_digest(item: object) -> str:
    value = getattr(item, "sha256", "")
    if (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    ):
        return value
    path = Path(getattr(item, "path", ""))
    with path.open("rb") as stream:
        return f"sha256:{hashlib.file_digest(stream, 'sha256').hexdigest()}"


_COHERENT_CAD_FORMATS = ("kicad", "model", "altium")
_CAD_AUTHOR_LABELS = {
    "ultralibrarian": "Ultra Librarian",
    "snapmagic": "SnapMagic",
    "traceparts": "TraceParts",
    "samacsys": "SamacSys",
}


def _provider_note_suffix(note: str, *, limit: int = 220) -> str:
    """Carry the drive's own account of what it could not select into the rejection reason.

    A missing native Altium row is a PROVIDER fact ("Ultra Librarian does not offer Altium
    Designer (Native) for this exact part"), but by the time the set is judged incomplete only
    Stockroom's own "missing native Altium symbol/footprint" survived. The two together are the
    difference between an owner who knows to try another provider and one who does not.
    """

    text = " ".join(str(note or "").split())
    if not text:
        return ""
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"; {text}"


def _combine_route_outcomes(
    outcomes: list[tuple[str, SourceOutcome]],
) -> SourceOutcome:
    """Merge independently captured author routes without losing partial evidence."""

    satisfied: list[Requirement] = []
    errors: list[str] = []
    skipped: list[str] = []
    blocked = False
    retained = 0
    provider_outcomes: list[ProviderOutcome] = []
    for label, outcome in outcomes:
        for requirement in outcome.satisfied:
            if requirement not in satisfied:
                satisfied.append(requirement)
        if outcome.error:
            errors.append(f"{label}: {outcome.error}")
        if outcome.skipped:
            skipped.append(f"{label}: {outcome.skipped}")
        retained += outcome.retained
        blocked = blocked or outcome.blocked
        provider_outcomes.extend(outcome.provider_outcomes)
    return SourceOutcome(
        satisfied=tuple(satisfied),
        retained=retained,
        error="; ".join(errors),
        skipped="; ".join(skipped),
        blocked=blocked,
        provider_outcomes=tuple(provider_outcomes),
    )


def _with_route_outcome(
    outcome: SourceOutcome,
    *,
    provider_key: str,
    author_key: str,
    label: str,
    attempted: bool = True,
    status: ProviderOutcomeStatus | None = None,
    reason: str | None = None,
) -> SourceOutcome:
    """Attach exactly one terminal ledger row to one independently bound author route."""

    if outcome.provider_outcomes:
        return outcome
    if status is None and outcome.blocked:
        detail = f"{outcome.error} {outcome.skipped}".casefold()
        if "cancel" in detail or "left for another provider" in detail:
            status = "cancelled"
        elif any(
            marker in detail
            for marker in (
                "sign-in",
                "sign in",
                "security",
                "captcha",
                "mfa",
                "passkey",
                "person",
                "user input",
                # `_challenge_issue`'s own wording. A Cloudflare/Turnstile interstitial IS the
                # canonical "only a person can clear this", and without its exact phrase here it
                # badged as a plain Blocked route - which reads as a Stockroom fault rather than
                # as one click the owner can make.
                "confirm you are human",
                "human check",
            )
        ):
            status = "requires-human"
        else:
            status = "blocked"
    return SourceOutcome(
        satisfied=outcome.satisfied,
        retained=outcome.retained,
        error=outcome.error,
        skipped=outcome.skipped,
        blocked=outcome.blocked,
        provider_outcomes=(
            provider_outcome_from_source(
                outcome,
                provider_key=provider_key,
                author_key=author_key,
                label=label,
                attempted=attempted,
                status=status,
                reason=reason,
            ),
        ),
    )


def _unattempted_route_outcome(
    *,
    provider_key: str,
    author_key: str,
    label: str,
    reason: str,
    status: ProviderOutcomeStatus = "not-attempted",
) -> SourceOutcome:
    base = SourceOutcome(skipped=reason)
    return _with_route_outcome(
        base,
        provider_key=provider_key,
        author_key=author_key,
        label=label,
        attempted=False,
        status=status,
        reason=reason,
    )


class _CaptureRoute(Protocol):
    capability: VendorCapability
    evidence_provider_key: str


def _capture_routes(adapter) -> tuple[_CaptureRoute, ...]:
    factory = getattr(adapter, "capture_routes", None)
    routes = tuple(factory()) if callable(factory) else (adapter,)
    return tuple(cast(_CaptureRoute, route) for route in routes)


def _author_key(provider_key: str, route) -> str:
    return (
        str(getattr(route, "evidence_provider_key", "") or provider_key)
        .strip()
        .casefold()
    )


def _provider_wide_outcome(
    adapter,
    outcome: SourceOutcome,
    *,
    attempted: bool,
    status: ProviderOutcomeStatus | None = None,
) -> SourceOutcome:
    """Ledger a pre-route provider result once for every route it prevented."""

    provider_key = adapter.capability.key
    return SourceOutcome(
        satisfied=outcome.satisfied,
        retained=outcome.retained,
        error=outcome.error,
        skipped=outcome.skipped,
        blocked=outcome.blocked,
        provider_outcomes=tuple(
            provider_outcome_from_source(
                outcome,
                provider_key=provider_key,
                author_key=_author_key(provider_key, route),
                label=route.capability.label,
                attempted=attempted,
                status=status,
            )
            for route in _capture_routes(adapter)
        ),
    )


def _receipt_binding_issue(
    landed,
    *,
    record,
    surface_key: str,
    evidence_provider_key: str,
) -> str:
    """Require every captured byte to carry the exact nonblank task and author binding."""

    expected = {
        "task_id": getattr(record, "id", ""),
        "manufacturer_key": (getattr(record, "manufacturer", "") or "").strip(),
        "mpn_canonical": (getattr(record, "mpn", "") or "").strip(),
        "surface_key": surface_key,
        "evidence_provider_key": evidence_provider_key,
    }
    if not landed:
        return "capture produced no task-bound receipt"
    for item in landed:
        for field_name, expected_value in expected.items():
            observed = getattr(item, field_name, "")
            if not expected_value or observed != expected_value:
                return (
                    "capture receipt binding mismatch for "
                    f"{field_name.replace('_', ' ')}; no file was retained or activated"
                )
    return ""


def _provider_formats(adapter, needs) -> list[str]:
    """Request one coherent bundle when a provider can supply every cross-EDA artifact.

    Evidence proves a relationship between actual bytes, not between old library references and
    one newly downloaded side. Therefore an Altium-only (or any other partial) repair through a
    complete-bundle provider downloads KiCad symbol/footprint, STEP, and native Altium from that
    SAME provider. Verification runs before any existing asset can be replaced.
    """
    selectable = set(adapter.capability.supported_formats)
    requested = [fmt for fmt in formats_for(needs) if fmt in selectable]
    if requested and set(_COHERENT_CAD_FORMATS) <= selectable:
        return list(_COHERENT_CAD_FORMATS)
    return requested


def _resolved_provider_url_issue(
    adapter,
    url: str,
    record,
    *,
    exact_catalog_route: bool = False,
) -> str:
    """Reject a resolver result before the managed browser can navigate to it."""

    provider_key = adapter.capability.key
    if not provider_url_allowed(provider_key, url):
        return (
            f"{adapter.capability.label} resolved outside its official provider origin; "
            "automatic navigation was refused."
        )
    detail = page_identity(provider_key, url)
    if detail is not None:
        error = (
            exact_catalog_observation_error(record, detail)
            if exact_catalog_route
            else exact_observation_error(record, detail)
        )
        return f"{adapter.capability.label} {error}." if error else ""
    query_name = {
        "digikey": "keywords",
        "samacsys": "term",
        "ultralibrarian": "queryText",
        "snapmagic": "q",
    }.get(provider_key)
    query = parse_qs(urlparse(url).query)
    requested_mpn = (getattr(record, "mpn", "") or "").strip().casefold()
    resolved_values = tuple(
        value.strip().casefold() for value in query.get(query_name or "", ()) if value.strip()
    )
    if requested_mpn and requested_mpn in resolved_values:
        return ""
    return (
        f"{adapter.capability.label} resolver URL did not identify the exact requested MPN; "
        "automatic navigation was refused."
    )


def _provider_hud_labels(adapter, formats: list[str]) -> tuple[str, ...]:
    """Exact provider choices the person should select for one coherent capture."""

    labels = adapter.capability.user_format_labels
    fallbacks = {
        "kicad": "KiCad symbol and footprint",
        "model": "STEP model",
        "altium": "Native Altium symbol and footprint",
    }
    return tuple(labels.get(fmt) or fallbacks[fmt] for fmt in formats)


def _provider_hud_author_route(adapter) -> str:
    """Human label for the CAD author behind the visible provider surface."""

    route = getattr(adapter, "_route", None)
    route_label = getattr(route, "label", "")
    if type(route_label) is str and route_label.strip():
        return route_label.strip()

    evidence_key = str(getattr(adapter, "evidence_provider_key", "") or "").strip().casefold()
    for family, label in _CAD_AUTHOR_LABELS.items():
        if evidence_key == family or evidence_key.endswith(f"-{family}"):
            return label
    return adapter.capability.label


# Native libraries attach directly. A `.lia` deliberately stays out of this suffix list because
# the route converter parses it and emits a verified native pair before attachment.
#
# A `.lia` is convertible by SEVERAL routes, and Altium is only one of them (owner pushed back on an
# Altium-only framing, correctly, 2026-07-27):
#   * ACCEL_ASCII is an OPEN, parsed format - `xtoolbox/pcad2kicad` implements a parser for it and
#     KiCad itself natively loads P-CAD ASCII. Nothing about reading a `.lia` is proprietary.
#   * Stockroom's pinned AltiumSharp sidecar writes `.SchLib`/`.PcbLib` without launching Altium.
#   * Altium's own Import Wizard does it natively, and this repo already drives installed Altium.
# Cheapest of all is not converting: a vendor that ships NATIVE Altium libraries needs none of this,
# and the attach path above already handles those. See the ledger's 2026-07-27 P-CAD findings.
_ALTIUM_LIBRARY_SUFFIXES = (".schlib", ".pcblib", ".intlib")


def _altium_libraries(landed) -> OwnedMaterialization | None:
    """Altium library files inside the download, unpacked with the ingest sandbox.

    Uses `unpack_inputs` rather than a second unzip: it already handles a directory, a loose file
    and a zip identically, and its `_safe_extract` refuses path traversal. A private zip reader
    here would be a second implementation of the one thing the ingest layer already does safely.

    The returned owner keeps the paths alive through synchronous attachment and then removes the
    tree explicitly. Empty and unreadable downloads leave no temporary root.
    """
    from stockroom.ingest.sandbox import unpack_inputs

    workdir = Path(tempfile.mkdtemp(prefix="sr-capture-altium-"))
    found: list[Path] = []
    try:
        for unpacked in unpack_inputs([item.path for item in landed], workdir):
            for path in sorted(unpacked.root.rglob("*")):
                if path.is_file() and path.suffix.lower() in _ALTIUM_LIBRARY_SUFFIXES:
                    found.append(path)
    except Exception:  # noqa: BLE001 - an unreadable download is the KiCad path's error to report
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
        return None
    if not found:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
        return None
    return OwnedMaterialization.adopt(workdir, tuple(found))


def _resolved_variant_files(resolved) -> dict[str, bytes]:
    """Materialization filenames bound to a reverified whole-tool variant."""

    fallbacks = {
        "symbol": "Variant.kicad_sym" if resolved.descriptor.tool == "kicad" else "Variant.SchLib",
        "footprint": (
            "Variant.kicad_mod" if resolved.descriptor.tool == "kicad" else "Variant.PcbLib"
        ),
        "model": "Variant.step",
    }
    files: dict[str, bytes] = {}
    for artifact in resolved.descriptor.artifacts:
        name = artifact.suggested_name or fallbacks[artifact.asset_kind]
        files[name] = resolved.data[artifact.asset_kind]
    if len(files) != len(resolved.data):
        raise ValueError("verified CAD variant filenames collide")
    return files


def _resolved_kicad_candidate(record, resolved, owner: OwnedMaterialization) -> StagingCandidate:
    """Build the normal ingest candidate from one reverified retained KiCad bundle."""

    paths_by_kind = {
        artifact.asset_kind: path
        for artifact, path in zip(resolved.descriptor.artifacts, owner.paths, strict=True)
    }
    symbol_path = paths_by_kind["symbol"]
    names = SymbolLib.load(symbol_path).symbol_names
    exact = [name for name in names if name == record.mpn]
    folded = [name for name in names if name.casefold() == record.mpn.casefold()]
    if len(exact) == 1:
        source_name = exact[0]
    elif len(folded) == 1:
        source_name = folded[0]
    elif len(names) == 1:
        source_name = names[0]
    else:
        raise ValueError(
            "retained KiCad evidence contains multiple symbols without one exact MPN match"
        )
    current_symbol = record.assets_for("kicad").symbol
    entry_name = (
        current_symbol.name
        if current_symbol is not None and current_symbol.name
        else record.mpn
    )
    return StagingCandidate(
        vendor=resolved.descriptor.provider,
        symbol_lib_path=symbol_path,
        symbol_name=source_name,
        footprint_variants=[paths_by_kind["footprint"]],
        model_path=paths_by_kind["model"],
        entry_name=entry_name,
        category=record.category,
        mpn=record.mpn,
        manufacturer=record.manufacturer,
    )


@dataclass
class _Session:
    """One leased provider surface and the capture that observes it.

    Nothing is attached to the page. The lease is Stockroom's own embedded provider WebView; the
    capture below only listens to its download journal, so the person's session stays exactly
    what it is - a person in a browser.
    """

    browser: ProviderSurfaceCapture
    ctx_manager: "_SessionManager"


class _SessionManager(Protocol):
    def __exit__(self, typ, value, traceback, /) -> object: ...


def _exact_catalog_url(adapter, record) -> str:
    """Return only the provider URL authorized by DigiKey's exact Media evidence.

    Product Information V4 is the discovery authority when it is configured.  Provider search
    pages are deliberately not synthesized here: a configured strict run must either use the
    exact product/provider URL DigiKey returned or stop with an actionable missing-route result.
    """

    catalog = getattr(record, "catalog", None)
    digikey = catalog.get("digikey") if isinstance(catalog, dict) else None
    if not isinstance(digikey, dict):
        return ""
    provider_key = str(getattr(getattr(adapter, "capability", None), "key", "") or "")
    if provider_key == "digikey":
        url = str(digikey.get("product_url") or "").strip()
        return url if url.startswith("https://") else ""
    from stockroom.enrich.cad_sources import catalog_provider_urls

    return catalog_provider_urls(digikey).get(provider_key, "")


class GuidedCaptureSource:
    """Capture a part's CAD files from a trusted vendor, through a real browser.

    `make_pipeline` builds an `IngestPipeline` (a fresh one per part, so a long run holds one
    sandbox at a time); `run_write` puts the git commit on the serialized write lane.
    """

    # The engine keys reports and the "can this source help?" pre-check off these. Missing
    # `provides()` made every run abort with an AttributeError AFTER opening a browser and
    # downloading a file - the work happened and nothing was attached.
    key = "guided"
    name = "guided"

    def provides(self) -> frozenset:
        """What this source can deliver: the formats a person can select on its provider page.

        A declared format still requires an implemented validation/attach seam on this side, which
        is why this reads capability data rather than assuming every provider export is ingestible.
        """
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return frozenset()
        formats = set(adapter.capability.supported_formats)
        out: set[Requirement] = set()
        if "kicad" in formats:
            out |= {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}
        if "model" in formats:
            out.add(Requirement.KICAD_MODEL)
        if "altium" in formats:
            out |= {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}
        return frozenset(out)

    def provider_route_ids(self) -> tuple[str, ...]:
        """The stable surface/author routes one exhaustive run must ledger."""

        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            raise ValueError(f"no capture adapter for vendor {self._vendor_key!r}")
        return tuple(
            f"{self._vendor_key}:{_author_key(self._vendor_key, route)}"
            for route in _capture_routes(adapter)
        )

    def __init__(
        self,
        make_pipeline,
        *,
        vendor: str = "ultralibrarian",
        download_root: Path,
        convert_altium=None,
        collect_variants: bool = False,
        preserve_active_pair: bool = False,
        close_after_supply: bool = False,
        single_provider_attempt: bool = False,
        run_write=None,
        now_iso=None,
        evidence_store=None,
        candidate_store=None,
        cross_eda_verifier=None,
        projection_verifier=None,
        user_finished: Callable[[], bool] | None = None,
        user_cancelled: Callable[[], bool] | None = None,
        cancel_workflow: Callable[[], None] | None = None,
        user_capture_timeout_s: float = 600.0,
        models_ids=None,
        strict_catalog_urls: bool = False,
        provider_surface=None,
        publish_active_route: Callable[[str, str, str], str] | None = None,
        clear_active_route: Callable[[str, str, str, str], None] | None = None,
        take_selected_files: Callable[[str, str, str, str], tuple[Path, ...]] | None = None,
        requested_requirements: frozenset[Requirement] | None = None,
    ) -> None:
        self._make_pipeline = make_pipeline
        self._vendor_key = vendor
        adapter = get_adapter(vendor)
        self._evidence_provider_key = (
            getattr(adapter, "evidence_provider_key", vendor) if adapter is not None else vendor
        )
        self.provider_key = vendor
        self.author_key = self._evidence_provider_key
        # Public, human-facing identity for completion reports. `key` must remain "guided"
        # because it names the source implementation, while two instances in one fallback chain
        # need distinct provider names so their honest decline reasons remain distinguishable.
        self.report_label = adapter.capability.label if adapter is not None else vendor
        self._download_root = Path(download_root)
        self._download_root.mkdir(parents=True, exist_ok=True)
        # Optional provider-package conversion seam. Direct and DigiKey-embedded Ultra Librarian
        # routes can deliver a recognized legacy P-CAD/script package instead of native Altium
        # libraries. The runner injects a content-recognizing converter on those provider surfaces;
        # unrelated archives return ``None`` and continue through the ordinary validation path.
        self._convert_altium = convert_altium
        # Explicit provider capture may be used after a part is already complete to retain another
        # exact provider's full dual-EDA set. It must never silently replace the active pair; the
        # pair selector owns that decision.
        self._collect_variants = collect_variants
        self._preserve_active_pair = preserve_active_pair
        self._close_after_supply = close_after_supply
        self._single_provider_attempt = single_provider_attempt
        self._run_write = run_write or (lambda fn: fn())
        self._now_iso = now_iso
        self._evidence_store = evidence_store
        # Optional, and OFF when absent. It records one retained candidate per artifact inside a
        # completed provider package so provider coverage can report bytes Stockroom actually
        # holds. It never decides an attachment; see `_retain_candidates`.
        self._candidate_store = candidate_store
        self._cross_eda_verifier = cross_eda_verifier or verify_cross_eda_component
        self._projection_verifier = projection_verifier
        self._user_finished = user_finished
        self._user_cancelled = user_cancelled
        self._cancel_workflow = cancel_workflow
        self._user_capture_timeout_s = user_capture_timeout_s
        # Optional, machine-local, and OFF when absent. It carries one opaque DigiKey models id per
        # part, learned from the person's own navigation, so a second capture can skip the search
        # they already did. Without it every capture is exactly the first-run journey.
        self._models_ids = models_ids
        self._strict_catalog_urls = bool(strict_catalog_urls)
        self._provider_surface = provider_surface
        self._publish_active_route = publish_active_route
        self._clear_active_route = clear_active_route
        self._take_selected_files = take_selected_files
        self._requested_requirements = requested_requirements
        self._session: _Session | None = None

    # -- lifecycle -------------------------------------------------------------------------

    def _ensure_session(self) -> _Session:
        """Lease the provider surface once, on the first part that actually needs it.

        Lazy on purpose: a run whose parts are all already complete must not flash a provider
        window at the owner for nothing.

        Every visible route uses the one Stockroom-owned embedded provider surface, and nothing
        is attached to it. Silently switching to an installed browser would lose the task-bound
        download broker and create two contradictory workflows.
        """
        if self._session is not None:
            return self._session
        adapter = get_adapter(self._vendor_key)
        if adapter is not None:
            # Trace what actually happens. The provider page opens in Stockroom's OWN embedded
            # surface with no driver connected to it; the only thing Stockroom reads is the
            # host's download journal, which is how the task-bound broker stays bound.
            trace(
                "capture.transport",
                provider=self._vendor_key,
                transport="stockroom-provider-surface",
                why="the person drives this route inside Stockroom's own provider surface",
                automation_attached=False,
                provider_controls_operated=False,
            )
        if self._provider_surface is None:
            raise CaptureBrowserError(
                "Stockroom's embedded provider browser is unavailable; restart or update "
                "Stockroom before collecting CAD files"
            )
        stack = ExitStack()
        try:
            provider_lease = stack.enter_context(self._provider_surface())
            browser = ProviderSurfaceCapture(
                download_dir=self._download_root,
                provider_key=self._vendor_key,
                native_surface=provider_lease,
            )
        except BaseException:
            stack.close()
            raise
        self._session = _Session(browser=browser, ctx_manager=stack)
        return self._session

    def close(self) -> None:
        """Release the provider surface. Called by the runner in a finally, so a stopped or
        failed run never leaves a window open."""
        session = self._session
        self._session = None
        if session is None:
            return
        try:
            session.ctx_manager.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass

    @contextmanager
    def _active_route(self, detail_url: str, evidence_provider_key: str):
        route_token = ""
        if self._publish_active_route is not None:
            route_token = self._publish_active_route(
                self._vendor_key,
                detail_url,
                evidence_provider_key,
            )
        try:
            yield route_token
        finally:
            if self._clear_active_route is not None:
                self._clear_active_route(
                    self._vendor_key,
                    detail_url,
                    evidence_provider_key,
                    route_token,
                )

    def attach_selected_files(
        self,
        record,
        paths: tuple[Path, ...],
        *,
        detail_url: str,
        evidence_provider_key: str | None = None,
    ) -> SourceOutcome:
        """Validate person-selected downloads through the normal capture attachment path.

        The native picker supplies only paths.  This method copies each file into the same
        task-bound broker used by browser downloads, then runs the unchanged exact-identity,
        cross-EDA, evidence, and atomic activation gates.  It is a recovery transport, not a
        weaker attachment mode.
        """

        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")
        if not paths:
            return SourceOutcome(error="no files were selected")
        manufacturer = (getattr(record, "manufacturer", "") or "").strip()
        mpn = (getattr(record, "mpn", "") or "").strip()
        if not manufacturer or not mpn:
            return SourceOutcome(error="manual recovery requires an exact manufacturer and MPN")
        author_key = evidence_provider_key or self._evidence_provider_key
        broker = DownloadBroker(
            DownloadTask(
                task_id=record.id,
                manufacturer_key=manufacturer,
                mpn_canonical=mpn,
                staging_root=self._download_root,
                surface_key=self._vendor_key,
                evidence_provider_key=author_key,
            )
        )
        try:
            receipts = tuple(
                broker.capture_local_file(
                    path,
                    source_url=detail_url,
                    transport="manual-file-picker",
                )
                for path in paths
            )
        except Exception as exc:  # noqa: BLE001 - return one honest recovery result
            return SourceOutcome(error=f"could not stage the selected files: {exc}")
        return self._attach(
            record,
            list(receipts),
            detail_url,
            detail_url=detail_url,
            evidence_provider_key=author_key,
            provider_note="files selected by the person from the active provider task",
            manual_identity_paths=tuple(receipt.path for receipt in receipts),
        )

    # -- the source contract ---------------------------------------------------------------

    def supply(self, record) -> SourceOutcome:
        """Run one part and optionally release the provider session before the next source."""

        outcome = SourceOutcome()
        try:
            try:
                outcome = self._supply_once(record)
                return outcome
            except Exception as exc:  # noqa: BLE001 - preserve a complete provider ledger
                adapter = get_adapter(self._vendor_key)
                if adapter is None:
                    return SourceOutcome(
                        error=f"{self._vendor_key}: {exc}",
                    )
                outcome = _provider_wide_outcome(
                    adapter,
                    SourceOutcome(error=f"{adapter.capability.label}: {exc}"),
                    attempted=True,
                    status="failed",
                )
                return outcome
        finally:
            if self._single_provider_attempt:
                required = set(capture_needs(record))
                if self._requested_requirements is not None:
                    required &= self._requested_requirements
                complete = bool(required) and required.issubset(set(outcome.satisfied))
                if not complete and self._session is not None:
                    retain = getattr(self._session.browser, "retain_provider_surface", None)
                    if callable(retain):
                        retain()
            if self._close_after_supply:
                self.close()

    def _decline(
        self,
        adapter,
        outcome: SourceOutcome,
        *,
        attempted: bool,
        status: ProviderOutcomeStatus,
        stage: str,
    ) -> SourceOutcome:
        """Ledger one pre-route decline AND say, in the trace, which stage produced it."""

        trace(
            "capture.part.declined",
            provider=self._vendor_key,
            stage=stage,
            status=status,
            attempted=attempted,
            why=outcome.error or outcome.skipped,
        )
        return _provider_wide_outcome(
            adapter,
            outcome,
            attempted=attempted,
            status=status,
        )

    def _supply_once(self, record) -> SourceOutcome:
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            trace_warning(
                "capture.part.declined",
                provider=self._vendor_key,
                stage="adapter",
                why="no capture adapter is registered for this provider key",
            )
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")
        routes = _capture_routes(adapter)
        trace(
            "capture.part.start",
            provider=self._vendor_key,
            label=adapter.capability.label,
            part=getattr(record, "id", ""),
            mpn=getattr(record, "mpn", ""),
            manufacturer=getattr(record, "manufacturer", ""),
            routes=[_author_key(self._vendor_key, route) for route in routes],
            collect_variants=self._collect_variants,
        )
        if self._user_cancelled and self._user_cancelled():
            return self._decline(
                adapter,
                SourceOutcome(skipped="provider capture workflow was cancelled"),
                attempted=False,
                status="cancelled",
                stage="cancelled-before-start",
            )

        manufacturer = (getattr(record, "manufacturer", "") or "").strip()
        mpn = (getattr(record, "mpn", "") or "").strip()
        if not manufacturer or not mpn:
            return self._decline(
                adapter,
                SourceOutcome(
                    error="browser acquisition requires an exact manufacturer and MPN"
                ),
                attempted=False,
                status="failed",
                stage="identity",
            )

        needs = list(capture_needs(record))
        if self._requested_requirements is not None:
            needs = [need for need in needs if need in self._requested_requirements]
        if not needs:
            if not self._collect_variants or getattr(record, "passive", False):
                return self._decline(
                    adapter,
                    SourceOutcome(
                        skipped=f"{record.mpn or record.id} needs no captured files"
                    ),
                    attempted=False,
                    status="not-attempted",
                    stage="needs",
                )
            # A selected provider is being harvested as an alternative. Ask it for its complete
            # declared set even though the active library itself has no missing requirements.
            needs = sorted(self.provides(), key=lambda requirement: requirement.value)
            if self._requested_requirements is not None:
                needs = [need for need in needs if need in self._requested_requirements]
        # Filter on the formats this provider declares a person can select and on Stockroom's
        # implemented attach seams.
        formats = _provider_formats(adapter, needs)
        trace(
            "capture.part.formats",
            provider=self._vendor_key,
            needs=[requirement.value for requirement in needs],
            provider_formats=sorted(adapter.capability.supported_formats),
            requested=list(formats),
        )
        if not formats:
            return self._decline(
                adapter,
                SourceOutcome(
                    skipped=(
                        f"{adapter.capability.label} cannot supply "
                        f"{', '.join(sorted({r.value.split('_')[0] for r in needs}))} for this part"
                    )
                ),
                attempted=False,
                status="not-attempted",
                stage="formats",
            )

        url = _exact_catalog_url(adapter, record)
        exact_catalog_route = bool(url)
        # One source instance services one component/provider run. Keep the catalog provenance on
        # that instance so route-test doubles and third-party adapter seams do not need a new call
        # signature merely to carry an internal identity proof.
        self._catalog_identity_authorized = exact_catalog_route
        if not url and not self._strict_catalog_urls:
            url = adapter.resolve_url(mpn)
        if not url:
            return self._decline(
                adapter,
                SourceOutcome(
                    skipped=(
                        f"DigiKey Media did not return an exact {adapter.capability.label} route "
                        f"for {record.id}"
                        if self._strict_catalog_urls
                        else f"no {adapter.capability.label} page for {record.id}"
                    )
                ),
                attempted=True,
                status="unavailable",
                stage="resolve-url",
            )
        resolved_url_issue = _resolved_provider_url_issue(
            adapter,
            url,
            record,
            exact_catalog_route=exact_catalog_route,
        )
        trace(
            "capture.part.url",
            provider=self._vendor_key,
            url=url_note(url),
            expected_manufacturer=manufacturer,
            expected_mpn=mpn,
            identity_gate="refused" if resolved_url_issue else "accepted",
            why=resolved_url_issue,
        )
        if resolved_url_issue:
            return self._decline(
                adapter,
                SourceOutcome(error=resolved_url_issue, blocked=True),
                attempted=True,
                status="failed",
                stage="resolved-url-identity",
            )

        session = self._ensure_session()
        outcomes: list[tuple[str, SourceOutcome]] = []
        for route_index, route in enumerate(routes):
            if self._user_cancelled is not None and self._user_cancelled():
                reason = "not attempted because the capture was cancelled"
                for later_route in routes[route_index:]:
                    outcomes.append(
                        (
                            later_route.capability.label,
                            _unattempted_route_outcome(
                                provider_key=self._vendor_key,
                                author_key=_author_key(self._vendor_key, later_route),
                                label=later_route.capability.label,
                                reason=reason,
                                status="cancelled",
                            ),
                        )
                    )
                break
            route_formats = _provider_formats(
                route,
                self.provides() if self._collect_variants else needs,
            )
            trace(
                "capture.route.start",
                provider=self._vendor_key,
                route=_author_key(self._vendor_key, route),
                label=route.capability.label,
                formats=list(route_formats),
                mode="user-driven",
                part=getattr(record, "id", ""),
            )
            if not route_formats:
                outcome = _with_route_outcome(
                    SourceOutcome(
                        skipped=(
                            f"{route.capability.label} has no accepted format for this task"
                        )
                    ),
                    provider_key=self._vendor_key,
                    author_key=_author_key(self._vendor_key, route),
                    label=route.capability.label,
                    attempted=False,
                    status="not-attempted",
                )
            else:
                raw_outcome = self._supply_user_driven_route(
                    record,
                    session,
                    route,
                    manufacturer,
                    mpn,
                    url,
                    route_formats,
                )
                outcome = _with_route_outcome(
                    raw_outcome,
                    provider_key=self._vendor_key,
                    author_key=_author_key(self._vendor_key, route),
                    label=route.capability.label,
                )
            outcomes.append((route.capability.label, outcome))
            if self._single_provider_attempt and (outcome.satisfied or outcome.retained):
                reason = (
                    f"not attempted because {route.capability.label} owns this one-provider "
                    "attempt"
                )
                for later_route in routes[route_index + 1 :]:
                    outcomes.append(
                        (
                            later_route.capability.label,
                            _unattempted_route_outcome(
                                provider_key=self._vendor_key,
                                author_key=_author_key(self._vendor_key, later_route),
                                label=later_route.capability.label,
                                reason=reason,
                            ),
                        )
                    )
                break
            if not self._collect_variants and set(needs).issubset(outcome.satisfied):
                reason = (
                    f"not attempted after {route.capability.label} completed the first "
                    "validated source set"
                )
                for later_route in routes[route_index + 1 :]:
                    outcomes.append(
                        (
                            later_route.capability.label,
                            _unattempted_route_outcome(
                                provider_key=self._vendor_key,
                                author_key=_author_key(self._vendor_key, later_route),
                                label=later_route.capability.label,
                                reason=reason,
                            ),
                        )
                    )
                break
            if outcome.blocked:
                reason = (
                    f"not attempted after {route.capability.label} blocked the provider session"
                )
                for later_route in routes[route_index + 1 :]:
                    outcomes.append(
                        (
                            later_route.capability.label,
                            _unattempted_route_outcome(
                                provider_key=self._vendor_key,
                                author_key=_author_key(
                                    self._vendor_key,
                                    later_route,
                                ),
                                label=later_route.capability.label,
                                reason=reason,
                            ),
                        )
                    )
                break
        if not outcomes:
            return SourceOutcome(
                skipped=f"{adapter.capability.label} exposed no implemented CAD-author route"
            )
        return _combine_route_outcomes(outcomes)


    def _retain_supplementary(
        self,
        record,
        landed,
        *,
        detail_url: str,
        surface_key: str,
        evidence_provider_key: str,
        require_step_model: bool = True,
        catalog_identity_authorized: bool = False,
    ) -> SourceOutcome:
        """Preserve exact route downloads without projecting an incomplete CAD bundle."""

        if self._evidence_store is None:
            return SourceOutcome(
                error=(
                    f"{evidence_provider_key} delivered supplementary files, but immutable "
                    "evidence storage is unavailable"
                )
            )
        binding_issue = _receipt_binding_issue(
            landed,
            record=record,
            surface_key=surface_key,
            evidence_provider_key=evidence_provider_key,
        )
        if binding_issue:
            return SourceOutcome(error=binding_issue)
        attributed = {
            value
            for item in landed
            if (value := getattr(item, "evidence_provider_key", ""))
        }
        if attributed != {evidence_provider_key}:
            return SourceOutcome(
                error=(
                    "supplementary capture route attribution mismatch: "
                    f"expected {evidence_provider_key!r}, received {sorted(attributed)!r}"
                )
            )
        observed = page_identity(evidence_provider_key, detail_url)
        if observed is None:
            return SourceOutcome(
                error=(
                    "the provider page does not demonstrate the requested part identity; "
                    "refusing to retain an unbound supplementary download"
                )
            )
        identity_error = (
            exact_catalog_observation_error(record, observed)
            if catalog_identity_authorized
            else exact_observation_error(record, observed)
        )
        if identity_error:
            return SourceOutcome(error=identity_error)
        if require_step_model:
            model_issue = self._supplementary_model_issue(landed)
            if model_issue:
                return SourceOutcome(error=model_issue)
        try:
            self._evidence_store.record_supplementary_artifacts(
                identity=exact_identity(record),
                surface_key=surface_key,
                provider_key=evidence_provider_key,
                adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
                receipts=tuple(landed),
            )
        except Exception as exc:  # noqa: BLE001 - never round failed retention up to delivery
            return SourceOutcome(error=f"supplementary evidence retention failed: {exc}")
        count = len(landed)
        noun = "file" if count == 1 else "files"
        return SourceOutcome(
            retained=count,
            skipped=(
                f"retained {count} exact supplementary {noun}; no incomplete CAD bundle was "
                "activated"
            ),
        )


    def _retain_incomplete_cad_set(
        self,
        record,
        landed,
        *,
        detail_url: str,
        evidence_provider_key: str,
        reason: str,
        catalog_identity_authorized: bool = False,
    ) -> SourceOutcome:
        """Preserve raw bytes while refusing a mixed or one-tool active projection."""

        trace_warning(
            "capture.attach.rejected",
            provider=self._vendor_key,
            route=evidence_provider_key,
            files=len(list(landed)),
            why=reason,
        )
        retained = self._retain_supplementary(
            record,
            landed,
            detail_url=detail_url,
            surface_key=self._vendor_key,
            evidence_provider_key=evidence_provider_key,
            require_step_model=False,
            catalog_identity_authorized=catalog_identity_authorized,
        )
        if retained.retained:
            return SourceOutcome(
                retained=retained.retained,
                skipped=f"{reason}; {retained.skipped}",
            )
        return SourceOutcome(
            error=(
                f"{reason}; {retained.error}"
                if retained.error
                else reason
            )
        )

    def _retain_candidates(self, record, landed, *, evidence_provider_key: str) -> None:
        """Retain each bound provider package as durable candidates. Never changes an attachment.

        Placed after the receipt-binding and route-attribution gates, so only bytes already proved
        to belong to THIS task and THIS route are retained, and before attachment, because "this
        provider delivered a package for this part" is true whether or not the set turns out
        complete enough to activate. Re-processing the same package is a no-op inside the store,
        so a second capture of the same download adds provenance rather than a duplicate.

        Retention is evidence for the coverage table and nothing else: a store that refuses a
        package (an unsafe archive, an unreadable path) is traced and the attachment continues
        exactly as it would have.
        """

        store = self._candidate_store
        if store is None:
            return
        for item in landed:
            try:
                store.retain_package(
                    component_id=record.id,
                    provider_id=evidence_provider_key,
                    package_path=Path(item.path),
                    source_url=str(getattr(item, "source_url", "") or ""),
                    expected_mpn=str(getattr(record, "mpn", "") or ""),
                    expected_manufacturer=str(getattr(record, "manufacturer", "") or ""),
                )
            except Exception as exc:  # noqa: BLE001 - retention never decides an attachment
                trace_warning(
                    "capture.candidates.rejected",
                    provider=self._vendor_key,
                    route=evidence_provider_key,
                    file=file_note(getattr(item, "path", "")),
                    why=str(exc),
                )

    def _supplementary_model_issue(self, landed) -> str:
        """Prove at least one delivered artifact contains a structurally valid STEP model."""

        pipeline = self._make_pipeline()
        try:
            candidates = []
            failures: list[str] = []
            for item in landed:
                try:
                    candidates.extend(pipeline.inspect(inputs=[item.path]))
                except Exception as exc:  # noqa: BLE001 - collect a useful route-level reason
                    failures.append(str(exc))
            model_paths = [
                Path(candidate.model_path)
                for candidate in candidates
                if getattr(candidate, "model_path", None) is not None
            ]
            for model_path in model_paths:
                try:
                    with model_path.open("rb") as handle:
                        prefix = handle.read(256).lstrip()
                        handle.seek(0, 2)
                        size = handle.tell()
                        handle.seek(max(0, size - 256))
                        suffix = handle.read()
                    if (
                        prefix.startswith(b"ISO-10303-21;")
                        and b"END-ISO-10303-21;" in suffix
                    ):
                        return ""
                except OSError as exc:
                    failures.append(str(exc))
            detail = f": {failures[0]}" if failures else ""
            return (
                "supplementary provider download contains no structurally valid STEP model"
                f"{detail}"
            )
        finally:
            pipeline.cleanup()


    def _route_open_url(self, adapter, manufacturer: str, mpn: str, url: str) -> str:
        """The exact page to open for one route: the author tab if it is known, else today's URL.

        DigiKey's per-part models page (`/en/models/<id>?tab=<author>`) is the surface the person
        navigates to by hand anyway. Its id is opaque, so this is available only AFTER a capture
        for this exact part has ended there. Every miss - no store, no learned id, no evidenced tab
        for this route - falls through to the resolver URL, which is what makes a first run
        indistinguishable from the behaviour before deep-linking existed.

        The link is REBUILT from the id and re-checked against DigiKey's origin, never pasted from
        storage: the store is a machine-local file, so a tampered id must not be able to send the
        person anywhere but DigiKey.

        `_resolved_provider_url_issue` cannot gate this one, and deliberately is not asked to. That
        gate proves identity from the URL TEXT - an exact `/detail/<mfr>/<mpn>/` path or the MPN in
        the search query - and a models URL is an opaque id by construction. The proof here is
        provenance instead: the id was observed at the end of a capture for this exact part and is
        stored under that part's manufacturer AND MPN, so a hit is bound to the requested part
        rather than merely spelling it. That is enough to NAVIGATE on, and it is used for nothing
        else - identity for attachment continues to run through the unchanged candidate and
        detail-URL gates, so a stale or re-numbered id can only cost a wrong page.
        """

        if self._models_ids is None or self._vendor_key != "digikey":
            return url
        tab = getattr(adapter, "models_tab", "") or ""
        if not tab:
            return url
        try:
            models_id = self._models_ids.get(manufacturer=manufacturer, mpn=mpn)
            if not models_id:
                return url
            deep_link = digikey_models_url(models_id, tab=tab)
        except Exception:  # noqa: BLE001 - an unusable hint costs a search, never the capture
            return url
        if digikey_models_id(deep_link) != models_id:
            return url
        trace(
            "capture.route.deep-link",
            provider=self._vendor_key,
            route=_author_key(self._vendor_key, adapter),
            tab=tab,
            url=url_note(deep_link),
        )
        return deep_link

    def _learn_models_id(self, manufacturer: str, mpn: str, final_url: str) -> str:
        """Keep the DigiKey models id off the page the PERSON chose to end on, if there is one.

        Reading the URL Stockroom was already handed is not scraping: no page content is read, no
        provider control is touched, and only the opaque id is retained. A URL that is not a
        DigiKey models page teaches nothing and writes nothing.
        """

        if self._models_ids is None or self._vendor_key != "digikey":
            return ""
        try:
            return self._models_ids.learn(
                manufacturer=manufacturer,
                mpn=mpn,
                final_url=final_url or "",
            )
        except Exception:  # noqa: BLE001 - advisory state never fails a completed capture
            return ""

    def _supply_user_driven_route(
        self,
        record,
        session: _Session,
        adapter,
        manufacturer: str,
        mpn: str,
        url: str,
        formats: list[str],
    ) -> SourceOutcome:
        """Open one author-bound provider page without invoking provider controls."""

        provider_label = adapter.capability.label
        evidence_provider_key = _author_key(self._vendor_key, adapter)
        open_url = self._route_open_url(adapter, manufacturer, mpn, url)
        broker = DownloadBroker(
            DownloadTask(
                task_id=record.id,
                manufacturer_key=manufacturer,
                mpn_canonical=mpn,
                staging_root=self._download_root,
                surface_key=self._vendor_key,
                evidence_provider_key=evidence_provider_key,
            )
        )
        result = None
        capture_error: Exception | None = None
        selected_receipts = ()
        try:
            with self._active_route(open_url, evidence_provider_key) as route_token:
                try:
                    result = session.browser.capture_user_downloads(
                        open_url,
                        broker,
                        hud=ProviderHudSpec(
                            provider_label=provider_label,
                            author_route=_provider_hud_author_route(adapter),
                            manufacturer=manufacturer,
                            mpn=mpn,
                            required_file_labels=_provider_hud_labels(adapter, formats),
                            required_formats=tuple(formats),
                            automated_step="Listening for provider downloads.",
                            human_action=(
                                "Start this part's download with every required format shown here."
                            ),
                        ),
                        should_finish=self._user_finished,
                        should_cancel=self._user_cancelled,
                        timeout_s=self._user_capture_timeout_s,
                    )
                except Exception as exc:  # noqa: BLE001 - an accepted inbox must still drain
                    capture_error = exc
                finally:
                    selected_paths = (
                        self._take_selected_files(
                            self._vendor_key,
                            open_url,
                            evidence_provider_key,
                            route_token,
                        )
                        if self._take_selected_files is not None
                        else ()
                    )
                    selected_receipts = tuple(
                        broker.capture_local_file(
                            path,
                            source_url=open_url,
                            transport="manual-file-picker",
                        )
                        for path in selected_paths
                    )
        except Exception as exc:  # noqa: BLE001 - one part's failure is a row, not a dead run
            return SourceOutcome(error=f"{provider_label}: {exc}")

        if result is None and not selected_receipts:
            return SourceOutcome(error=f"{provider_label}: {capture_error}")
        result_files = () if result is None else result.files
        result_status = "browser-error-recovered" if result is None else result.status
        result_url = open_url if result is None else result.final_url
        landed = [*result_files, *selected_receipts]
        received = len(landed)
        evidence_url = result_url or open_url
        learned = self._learn_models_id(manufacturer, mpn, evidence_url)
        trace(
            "capture.route.user-result",
            provider=self._vendor_key,
            route=evidence_provider_key,
            status=result_status,
            files=received,
            names=[file_note(getattr(item, "path", "")) for item in landed],
            final_url=url_note(evidence_url),
            models_id=learned,
        )
        cancelled = result_status == "cancelled"
        if cancelled:
            if self._cancel_workflow is not None:
                self._cancel_workflow()
            if not landed:
                return SourceOutcome(
                    skipped=f"{provider_label} capture was cancelled before any file arrived",
                    blocked=True,
                )
        if result_status == "try_another" and not landed:
            suffix = f" after receiving {counted(received, 'file')}" if received else ""
            return SourceOutcome(
                skipped=(
                    f"{provider_label} was left for another provider{suffix}; nothing was attached"
                ),
                # This is a route-level instruction, not a provider-session failure.  DigiKey
                # exposes several independent CAD authors behind one remembered browser session;
                # choosing "Use Another Provider" must advance from (for example) Ultra
                # Librarian to SnapMagic instead of suppressing every later DigiKey route.
                blocked=False,
            )
        if result_status == "timed_out" and not landed:
            account_blocker = _account_verification_blocker(evidence_url)
            if account_blocker:
                return SourceOutcome(skipped=account_blocker, blocked=True)
            suffix = f" after receiving {counted(received, 'file')}" if received else ""
            return SourceOutcome(
                error=f"{provider_label} capture timed out{suffix}; nothing was attached"
            )
        if not landed:
            return SourceOutcome(error="the vendor download did not produce a file")

        if getattr(adapter, "supplementary_only", False):
            outcome = self._retain_supplementary(
                record,
                landed,
                detail_url=evidence_url,
                surface_key=self._vendor_key,
                evidence_provider_key=evidence_provider_key,
                catalog_identity_authorized=bool(
                    getattr(self, "_catalog_identity_authorized", False)
                ),
            )
        else:
            outcome = self._attach(
                record,
                landed,
                # The page actually opened, which is the deep link when one was used. Provenance
                # must record where the bytes came from, not the fallback URL.
                open_url,
                detail_url=evidence_url,
                evidence_provider_key=evidence_provider_key,
                provider_note=(
                    "files selected by the person from the active provider task"
                    if selected_receipts
                    else ""
                ),
                manual_identity_paths=tuple(receipt.path for receipt in selected_receipts),
                catalog_identity_authorized=bool(
                    getattr(self, "_catalog_identity_authorized", False)
                ),
            )
        # Cancel stops subsequent routes/workflow work. It does not erase bytes that crossed the
        # task-bound broker before the click; those retain their normal validation outcome.
        return outcome.as_blocked() if cancelled else outcome

    def _attach(
        self,
        record,
        landed,
        url: str,
        *,
        detail_url: str = "",
        evidence_provider_key: str = "",
        provider_note: str = "",
        manual_identity_paths: tuple[Path, ...] = (),
        catalog_identity_authorized: bool = False,
    ) -> SourceOutcome:
        provider_key = evidence_provider_key or self._evidence_provider_key
        if evidence_provider_key:
            binding_issue = _receipt_binding_issue(
                landed,
                record=record,
                surface_key=self._vendor_key,
                evidence_provider_key=provider_key,
            )
            if binding_issue:
                trace_warning(
                    "capture.attach.rejected",
                    provider=self._vendor_key,
                    route=provider_key,
                    why=binding_issue,
                )
                return SourceOutcome(error=binding_issue)
        attributed = {
            value
            for item in landed
            if (value := getattr(item, "evidence_provider_key", ""))
        }
        if evidence_provider_key and attributed != {provider_key}:
            trace_warning(
                "capture.attach.rejected",
                provider=self._vendor_key,
                route=provider_key,
                why="capture route attribution mismatch",
                observed=sorted(attributed),
            )
            return SourceOutcome(
                error=(
                    "capture route attribution mismatch: "
                    f"expected {provider_key!r}, received {sorted(attributed)!r}"
                )
            )
        self._retain_candidates(record, landed, evidence_provider_key=provider_key)
        cleanup_callbacks = []
        try:
            outcome = self._attach_impl(
                record,
                landed,
                url,
                detail_url=detail_url,
                evidence_provider_key=provider_key,
                cleanup_callbacks=cleanup_callbacks,
                provider_note=provider_note,
                manual_identity_paths=manual_identity_paths,
                catalog_identity_authorized=catalog_identity_authorized,
            )
            trace(
                "capture.attach.result",
                provider=self._vendor_key,
                route=provider_key,
                satisfied=sorted(item.value for item in outcome.satisfied),
                retained=outcome.retained,
                error=outcome.error,
                skipped=outcome.skipped,
                blocked=outcome.blocked,
            )
            return outcome
        finally:
            for cleanup in reversed(cleanup_callbacks):
                cleanup()

    def _attach_impl(
        self,
        record,
        landed,
        url: str,
        *,
        detail_url: str = "",
        evidence_provider_key: str,
        cleanup_callbacks,
        provider_note: str = "",
        manual_identity_paths: tuple[Path, ...] = (),
        catalog_identity_authorized: bool = False,
    ) -> SourceOutcome:
        """Turn the downloaded file(s) into attached assets, with provenance.

        Reuses the ingest pipeline's atomic materializer, so network capture has one validation and
        attachment path rather than separate per-tool seams that can drift.

        BOTH TOOLS OR NEITHER.  KiCad, STEP, and native Altium must be present in this exact
        provider download set and pass native cross-readback.  Only then does the pipeline borrow
        one shared transaction so every file and both active pointers commit or roll back
        together.  One-tool or independently sourced output is retained as non-projectable
        evidence and cannot replace an active library projection.
        """
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")
        conversion_failure = ""
        converted_altium = False
        altium_footprint_entry = ""
        captured_altium = _altium_libraries(landed)
        if captured_altium is not None:
            cleanup_callbacks.append(captured_altium.cleanup)
        altium_sources = [] if captured_altium is None else list(captured_altium.paths)
        # Recovery is intentionally content-bound, not timing-bound. The native picker belongs to
        # the active provider task, but the person may return an Ultra Librarian archive after the
        # DigiKey surface has already advanced from its UL row to SnapMagic or TraceParts. The
        # injected converter recognizes only a supported UL P-CAD/script package and returns None
        # for every other archive; receipt, identity, provenance, and coherent-pair checks below
        # still bind and validate the exact active task before anything can be activated.
        route_converter = self._convert_altium
        if not altium_sources and route_converter is not None:
            try:
                converted = route_converter(
                    tuple(item.path for item in landed),
                    record.manufacturer,
                    record.mpn,
                )
                if converted is not None:
                    converted_altium = True
                    cleanup = getattr(converted, "cleanup", None)
                    if callable(cleanup):
                        cleanup_callbacks.append(cleanup)
                    altium_sources = list(converted.libraries)
                    altium_footprint_entry = str(
                        getattr(converted, "preferred_footprint", "") or ""
                    )
            except Exception as exc:  # noqa: BLE001 - keep usable KiCad and report this gap
                conversion_failure = f"could not convert the provider's Altium package: {exc}"
        trace(
            "capture.attach.inputs",
            provider=self._vendor_key,
            route=evidence_provider_key,
            files=len(list(landed)),
            native_altium=len(altium_sources) if not converted_altium else 0,
            converted_altium=converted_altium,
            converter=route_converter is not None,
            conversion_failure=conversion_failure,
        )
        pipeline = self._make_pipeline()
        try:
            load_current = getattr(getattr(pipeline, "ops", None), "load_record", None)
            if callable(load_current):
                record = load_current(record.id)
            preserve_active_pair = (
                (self._preserve_active_pair or self._collect_variants)
                and self._evidence_store is not None
                and self._projection_verifier is not None
                and active_pair_is_verified(
                    self._evidence_store,
                    record,
                    projection_verifier=self._projection_verifier,
                )
            )
            candidates = []
            manual_candidates = []
            manual_path_set = {Path(path) for path in manual_identity_paths}
            inspect_errors: list[Exception] = []
            # The task owns one bundle even when a provider delivers KiCad, STEP, and Altium as
            # sibling downloads. The pipeline isolates an unreadable sibling, then merges every
            # successful fragment in one pass so a bare STEP cannot become an orphan candidate.
            try:
                candidates.extend(pipeline.inspect(inputs=[item.path for item in landed]))
            except Exception as exc:  # noqa: BLE001
                inspect_errors.append(exc)
            if manual_path_set:
                try:
                    manual_candidates.extend(
                        pipeline.inspect(inputs=sorted(manual_path_set))
                    )
                except Exception as exc:  # noqa: BLE001
                    inspect_errors.append(exc)
            if not landed:
                try:
                    candidates.extend(pipeline.inspect(inputs=[]))
                except Exception as exc:  # noqa: BLE001
                    inspect_errors.append(exc)
            trace(
                "capture.attach.inspected",
                provider=self._vendor_key,
                route=evidence_provider_key,
                candidates=len(candidates),
                inspect_errors=len(inspect_errors),
                first_inspect_error=str(inspect_errors[0]) if inspect_errors else "",
                altium_sources=len(altium_sources),
            )
            if not candidates and not altium_sources and inspect_errors:
                trace_warning(
                    "capture.attach.rejected",
                    provider=self._vendor_key,
                    route=evidence_provider_key,
                    why=f"could not read the download: {inspect_errors[0]}",
                )
                return SourceOutcome(error=f"could not read the download: {inspect_errors[0]}")

            if manual_path_set and not catalog_identity_authorized:
                manual_selection = select_exact_candidate(
                    record,
                    manual_candidates,
                    # An unbound file picker can point at anything on disk, so it still needs an
                    # internal identity. An exact catalog-authorized capture is already bound to
                    # the active component and uses the single normal selection below.
                    vendor_key=evidence_provider_key,
                    detail_url=detail_url,
                    trust_detail_url=False,
                )
                if manual_selection.error or manual_selection.candidate is None:
                    reason = manual_selection.error or (
                        "the selected archive does not expose an exact internal part identity"
                    )
                    return SourceOutcome(
                        error=f"manually selected CAD was not attached: {reason}"
                    )

            selection = select_exact_candidate(
                record,
                candidates,
                vendor_key=evidence_provider_key,
                detail_url=detail_url,
                catalog_identity_authorized=catalog_identity_authorized,
            )
            candidate = selection.candidate
            trace(
                "capture.attach.selection",
                provider=self._vendor_key,
                route=evidence_provider_key,
                exact_candidate=candidate is not None,
                why=selection.error,
            )
            if selection.error:
                return SourceOutcome(error=selection.error)
            if candidate is None:
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    catalog_identity_authorized=catalog_identity_authorized,
                    reason=(
                        "provider download contains no exact KiCad symbol, footprint, and STEP "
                        "beside its native Altium files"
                    ),
                )

            candidate.entry_name = record.mpn or candidate.entry_name or candidate.mpn
            missing_kicad: list[str] = []
            if candidate.symbol_lib_path is None:
                missing_kicad.append("KiCad symbol")
            if not candidate.footprint_variants:
                missing_kicad.append("KiCad footprint")
            if candidate.model_path is None:
                missing_kicad.append("STEP model")
            if missing_kicad or not altium_sources:
                absent = [
                    *missing_kicad,
                    *(["native Altium symbol/footprint"] if not altium_sources else []),
                ]
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    catalog_identity_authorized=catalog_identity_authorized,
                    reason=(
                        "provider download is not one complete dual-EDA source set; missing "
                        + ", ".join(absent)
                        + (f"; {conversion_failure}" if conversion_failure else "")
                        + _provider_note_suffix(provider_note)
                    ),
                )
            if self._evidence_store is None:
                return SourceOutcome(
                    error=(
                        "a complete provider CAD set landed, but immutable evidence storage is "
                        "unavailable; nothing was activated"
                    )
                )
            if self._cross_eda_verifier is None:
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    catalog_identity_authorized=catalog_identity_authorized,
                    reason=(
                        "the complete provider CAD set cannot be activated without native "
                        "cross-EDA verification"
                    ),
                )
            try:
                evidence_digest, cross_eda_verified = record_browser_cad_evidence(
                    store=self._evidence_store,
                    record=record,
                    candidate=candidate,
                    provider_key=evidence_provider_key,
                    detail_url=detail_url,
                    altium_sources=tuple(altium_sources),
                    cross_eda_verifier=self._cross_eda_verifier,
                    source_receipt_digests=tuple(
                        sorted({_captured_file_digest(item) for item in landed})
                    ),
                    source_receipts=tuple(item.path for item in landed),
                    catalog_identity_authorized=catalog_identity_authorized,
                    altium_footprint_entry=altium_footprint_entry,
                )
            except Exception as exc:  # noqa: BLE001 - no partial projection on any failure
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    catalog_identity_authorized=catalog_identity_authorized,
                    reason=f"same-set cross-EDA verification failed: {exc}",
                )
            if not cross_eda_verified:
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    catalog_identity_authorized=catalog_identity_authorized,
                    reason="same-set cross-EDA verification did not prove the provider bundle",
                )
            try:
                identity = exact_identity(record)
                verified_pair = resolve_verified_pair(
                    self._evidence_store,
                    identity=identity,
                    manifest_digest=evidence_digest,
                )
                kicad_resolved = verified_pair.kicad
                altium_resolved = verified_pair.altium
            except Exception as exc:  # noqa: BLE001 - never attach an unbound projection
                return SourceOutcome(error=f"CAD evidence pointer resolution failed: {exc}")

            if preserve_active_pair:
                return SourceOutcome(
                    retained=5,
                    skipped=(
                        f"retained a complete {evidence_provider_key} dual-EDA variant; "
                        "the active KiCad/Altium pair is unchanged"
                    ),
                )

            origin = AssetOrigin(
                vendor=evidence_provider_key,
                url=url,
                captured_at=self._now_iso() if self._now_iso else "",
                extra={
                    "evidence_adapter_version": BROWSER_CAPTURE_ADAPTER_VERSION,
                    "evidence_manifest_digest": evidence_digest,
                    "evidence_operation": kicad_resolved.descriptor.operation,
                    "evidence_set": evidence_digest,
                },
            )
            try:
                updated = self._run_write(
                    lambda: pipeline.attach_coherent_cad_assets(
                        record.id,
                        candidate,
                        *altium_sources,
                        kicad_origin=origin,
                        altium_origin=origin,
                        now_iso=self._now_iso() if self._now_iso else "",
                        kicad_active_variant=kicad_resolved.pointer,
                        altium_active_variant=altium_resolved.pointer,
                        preferred_altium_footprint=verified_pair.altium_footprint_entry,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - the whole set rolls back as one row
                return SourceOutcome(error=f"could not activate the coherent CAD set: {exc}")

            kicad_bundle = updated.assets_for("kicad")
            altium_bundle = updated.assets_for("altium")
            if not all(
                (
                    asset_present(kicad_bundle.symbol),
                    asset_present(kicad_bundle.footprint),
                    asset_present(kicad_bundle.model),
                    asset_present(altium_bundle.symbol),
                    asset_present(altium_bundle.footprint),
                )
            ):
                return SourceOutcome(
                    error=(
                        "the atomic CAD transaction returned without all five same-set "
                        "projections present"
                    )
                )
            trace(
                "capture.attach.activated",
                provider=self._vendor_key,
                route=evidence_provider_key,
                part=getattr(record, "id", ""),
                evidence=evidence_digest,
            )
            return SourceOutcome(
                satisfied=(
                    Requirement.KICAD_SYMBOL,
                    Requirement.KICAD_FOOTPRINT,
                    Requirement.KICAD_MODEL,
                    Requirement.ALTIUM_SYMBOL,
                    Requirement.ALTIUM_FOOTPRINT,
                )
            )
        finally:
            pipeline.cleanup()
