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
That matters for the workflow the owner actually has: a 90-part sitting must cost ONE sign-in, not
ninety. The persistent profile then carries that sign-in to later runs.

WHAT IT DOES NOT DO
It never invents a file. If the vendor offers nothing, the part is reported skipped and left
exactly as it was, because a capture that fabricates a partial answer is worse than one that says
"nothing here".
"""

from __future__ import annotations

import inspect
import tempfile
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

from stockroom.cad_variants import resolve_cad_variant, same_cad_evidence_set
from stockroom.capture.browser import (
    PlaywrightCaptureBrowser,
    ProviderHudSpec,
    SharedPlaywrightRuntime,
)
from stockroom.capture.cad_composition import OwnedMaterialization
from stockroom.capture.complete import (
    ProviderOutcome,
    ProviderOutcomeStatus,
    SourceOutcome,
    provider_outcome_from_source,
)
from stockroom.capture.cross_eda import verify_cross_eda_component
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.evidence import (
    BROWSER_CAPTURE_ADAPTER_VERSION,
    exact_identity,
    record_browser_cad_evidence,
)
from stockroom.capture.identity import (
    exact_observation_error,
    page_identity,
    provider_url_allowed,
    select_exact_candidate,
)
from stockroom.capture.requirements import Requirement, asset_present, capture_needs
from stockroom.capture.vendors import (
    DriveReport,
    VendorCapability,
    formats_for,
    get_adapter,
)
from stockroom.capture.verified_cache import active_pair_is_verified
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.asset import AssetOrigin

# How long to wait for the vendor's file after the adapter submits. Generous because a heavy part's
# export genuinely generates server-side for tens of seconds (measured live on DigiKey, 2026-07-23),
# and this is a BACKSTOP: the wait ends the instant the file appears in the saved list.
_DOWNLOAD_TIMEOUT_MS = 120_000
_COHERENT_CAD_FORMATS = ("kicad", "model", "altium")
_CAD_AUTHOR_LABELS = {
    "ultralibrarian": "Ultra Librarian",
    "snapmagic": "SnapMagic",
    "traceparts": "TraceParts",
    "samacsys": "SamacSys",
}


def _wait_for_capture(
    browser,
    page,
    before: int,
    timeout_s: float,
    gap: float = 0.25,
    *,
    errors_before: int | None = None,
    stop_when: Callable[[], bool] | None = None,
) -> bool:
    """True once a NEW file has actually been SAVED. Polls the saved list, not the event.

    The saved list is the observation; the download event is only a promise. See the call site for
    the race this exists to avoid.

    IT MUST SLEEP THROUGH THE PAGE, NOT THROUGH `time.sleep`. Playwright's SYNC api uses greenlet to
    switch between the caller's synchronous code and its async internals, and that switch only
    happens inside a Playwright call. A bare `time.sleep()` blocks the whole THREAD, so incoming
    browser messages sit unread in the socket buffer: `on("download")` is never invoked, `captured`
    can never grow, and the wait burns its full timeout on a download that completed immediately.
    `page.wait_for_timeout` IS a Playwright call, so it yields to that loop.

    Playwright's own docs say the same thing and are the reason this is stated as mechanism rather
    than as a guess - they recommend `wait_for_timeout` over the time module "because internally
    Playwright relies on asynchronous operations and when using time.sleep() they can't get
    processed correctly" (playwright.dev/python/docs/api/class-page, `wait_for_timeout`).

    Measured 2026-07-27: with `time.sleep` the localhost end-to-end tests passed (their download was
    already dispatched during `drive`) while the API-driven capture failed every time at the full
    120 s backstop with nothing attached - the same symptom as the event race this function replaced,
    from the opposite cause.
    """
    error_mark = (
        len(getattr(browser, "download_errors", ())) if errors_before is None else errors_before
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        errors = getattr(browser, "download_errors", ())
        if len(errors) > error_mark:
            raise errors[error_mark]
        if len(browser.captured) > before:
            return True
        if stop_when is not None and stop_when():
            return False
        page.wait_for_timeout(gap * 1000)
    # One last look: a file that landed inside the final gap still counts.
    errors = getattr(browser, "download_errors", ())
    if len(errors) > error_mark:
        raise errors[error_mark]
    return len(browser.captured) > before


def sign_in_adapter(adapter, page, credentials) -> str:
    """Sign this page in for the vendor. `""` when signed in or when there is nothing to do.

    Shared by `GuidedCaptureSource` and `scripts/webread.py --drive` so the live tool cannot
    authenticate differently from the app - the first version of that tool called `sign_in`
    unconditionally and crashed on the one adapter that does not have it.

    Deliberately NOT fatal, and every no-op case is distinct from a refusal. A vendor that needs no
    login, an adapter with NO `sign_in`, or absent credentials all return "" - because everything up
    to the Download button works signed out (measured 2026-07-27), so a per-part outcome is far more
    useful than a dead run. A refusal returns its reason so the caller can say WHY rather than
    leaving the owner to infer it from a vendor-shaped "no download button".
    """
    if adapter is None or not getattr(adapter.capability, "needs_login", False):
        return ""
    sign_in = getattr(adapter, "sign_in", None)
    if sign_in is None or credentials is None:
        return ""
    if getattr(adapter, "signed_in", None) and adapter.signed_in(page):
        return ""  # the persistent profile already carries the session
    creds = credentials(adapter.capability.key)
    if not creds:
        return ""
    return sign_in(page, creds[0], creds[1]) or ""


def _drive_adapter(
    adapter,
    page,
    formats: list[str],
    *,
    expected_manufacturer: str,
    expected_mpn: str,
):
    """Invoke the exact-identity contract while retaining fixture-adapter compatibility."""

    parameters = inspect.signature(adapter.drive).parameters.values()
    accepts_identity = {
        parameter.name for parameter in parameters
    } >= {"expected_manufacturer", "expected_mpn"} or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    if (expected_manufacturer or expected_mpn) and accepts_identity:
        return adapter.drive(
            page,
            formats,
            expected_manufacturer=expected_manufacturer,
            expected_mpn=expected_mpn,
        )
    if (
        (expected_manufacturer or expected_mpn)
        and adapter.capability.browser_access == "machine_allowed"
    ):
        raise TypeError("machine-access adapter does not implement exact manufacturer+MPN gating")
    return adapter.drive(page, formats)


def drive_formats(
    browser,
    page,
    adapter,
    formats,
    url,
    timeout_s: float | None = None,
    *,
    expected_manufacturer: str = "",
    expected_mpn: str = "",
):
    """Drive a vendor for `formats` and WAIT FOR THE FILES TO LAND. `(DriveReport, error|None)`.

    THE one place a vendor is driven for real. `GuidedCaptureSource.supply` runs it as part of
    completing a part; `scripts/webread.py --drive` runs it to answer "what does this vendor
    ACTUALLY deliver" without touching a library. Two callers, one implementation, so a fix to the
    sequencing or the wait reaches both - the alternative was measured on 2026-07-27, when a live
    vendor drive was done by a throwaway script and the knowledge died with the session.

    ONE download, or ONE PER FORMAT - decided by the adapter's capability, never by a vendor name.
    Ultra Librarian ticks checkboxes and exports everything together (`formats_exclusive=False`);
    SnapMagic has a separate button per format, so asking for both in one drive would fetch only the
    first and silently lose the other. That flag was DATA nothing read until 2026-07-27, which is
    exactly how a half-working vendor ships.

    A format the vendor simply does not carry is recorded as MISSED and the rest still run - a part
    that can get its footprint but not its 3D model must come away with the footprint, not nothing.
    A format that WAS submitted and never arrived is the returned error instead: calling that a miss
    would let a vanished file read as "the vendor had nothing".

    Re-navigates before each exclusive format unless the adapter declares a measured reusable-page
    contract. Taking a download generally closes a modal or changes the page, but DigiKey's models
    app does the opposite: the fragment survives while redundant renders trigger empty fragments
    and security challenges. Either behavior is capability data, never a vendor-name branch.

    THE WAIT IS ON THE SAVED FILE, NEVER ON THE DOWNLOAD EVENT. `wait_for_event("download")` RACES
    the `on("download")` handler the browser session registers up front; whichever listener is
    active when the event fires consumes it, so a fast download is taken by the handler and the wait
    then burns its full timeout reporting failure for a file already on disk (measured 2026-07-27,
    briefly and wrongly read as "Camoufox cannot download"). `browser.captured` grows only AFTER
    `save_as` returns, so polling it observes the file genuinely existing, and the timeout stays a
    backstop for a vendor that never answers rather than the thing that decides success.
    """
    from stockroom.capture.vendors import DriveReport

    label = adapter.capability.label
    wait_s = _DOWNLOAD_TIMEOUT_MS / 1000.0 if timeout_s is None else timeout_s

    if not adapter.capability.formats_exclusive:
        mark = len(browser.captured)
        error_mark = len(getattr(browser, "download_errors", ()))
        page.goto(url, wait_until="domcontentloaded")
        report = _drive_adapter(
            adapter,
            page,
            list(formats),
            expected_manufacturer=expected_manufacturer,
            expected_mpn=expected_mpn,
        )
        if not report.submitted:
            return report, None
        if not _wait_for_capture(
            browser,
            page,
            mark,
            wait_s,
            errors_before=error_mark,
            stop_when=lambda: bool(_user_clearance_issue(adapter, page)),
        ):
            gate = _download_gate(adapter, page)
            if gate:
                report.blocked = True
                report.requires_user_clearance = bool(_user_clearance_issue(adapter, page))
                return report, gate
            return report, f"{label} did not deliver a file within {wait_s:.0f}s"
        return report, None

    combined = DriveReport()
    reuse_page = bool(getattr(adapter.capability, "reuse_page_between_formats", False))
    for format_index, fmt in enumerate(formats):
        attempts = max(1, min(3, int(getattr(adapter, "max_download_attempts", 1))))
        delivered = False
        for attempt in range(1, attempts + 1):
            mark = len(browser.captured)
            error_mark = len(getattr(browser, "download_errors", ()))
            try:
                # Most exclusive-format providers need a fresh render after every download.
                # DigiKey's measured models app is the opposite: its fragment remains valid, while
                # repeated renders trigger empty fragments and then a Cloudflare challenge. The
                # caller already initialized the task page, so a declared reusable route navigates
                # only for a bounded retry or when a standalone caller supplied a blank page.
                current_url = str(getattr(page, "url", "") or "")
                if (
                    not reuse_page
                    or attempt > 1
                    or (
                        format_index == 0
                        and current_url in {"", "about:blank"}
                    )
                ):
                    page.goto(url, wait_until="domcontentloaded")
                one = _drive_adapter(
                    adapter,
                    page,
                    [fmt],
                    expected_manufacturer=expected_manufacturer,
                    expected_mpn=expected_mpn,
                )
            except Exception as exc:  # noqa: BLE001 - one format is one honest result row
                combined.missed.append(fmt)
                combined.message = f"{label}: {exc}"
                break
            if not one.submitted:
                retry_issue = _retryable_download_issue(adapter, page)
                if retry_issue and attempt < attempts:
                    combined.message = (
                        f"{retry_issue}; reopening the exact DigiKey route "
                        f"(attempt {attempt + 1} of {attempts})."
                    )
                    continue
                combined.missed.extend(one.missed or [fmt])
                combined.blocked = combined.blocked or one.blocked
                combined.requires_user_clearance = (
                    combined.requires_user_clearance or one.requires_user_clearance
                )
                combined.route_unavailable = (
                    combined.route_unavailable or one.route_unavailable
                )
                if retry_issue:
                    combined.message = (
                        f"{retry_issue}; stopped after {attempts} bounded attempts."
                    )
                elif one.message:
                    combined.message = one.message
                if one.blocked:
                    # Auth/challenge/account state is provider-wide. Trying the remaining format
                    # buttons cannot change it and only repeats the same failure.
                    return combined, None
                if one.route_unavailable:
                    return combined, None
                break
            if _wait_for_capture(
                browser,
                page,
                mark,
                wait_s,
                errors_before=error_mark,
                stop_when=lambda: bool(
                    _user_clearance_issue(adapter, page)
                    or _retryable_download_issue(adapter, page)
                ),
            ):
                combined.selected.extend(one.selected or [fmt])
                combined.submitted = True
                delivered = True
                break
            gate = _download_gate(adapter, page)
            if gate:
                combined.blocked = True
                combined.requires_user_clearance = bool(_user_clearance_issue(adapter, page))
                return combined, gate
            retry_issue = _retryable_download_issue(adapter, page)
            if retry_issue and attempt < attempts:
                combined.message = (
                    f"{retry_issue}; reopening the exact DigiKey route "
                    f"(attempt {attempt + 1} of {attempts})."
                )
                continue
            if retry_issue:
                return (
                    combined,
                    f"{label} could not deliver {fmt} after {attempts} bounded attempts: "
                    f"{retry_issue}",
                )
            return combined, f"{label} did not deliver {fmt} within {wait_s:.0f}s"
        if delivered:
            continue
    if combined.selected:
        combined.message = f"Requested {' and '.join(combined.selected)} from {label}."
    return combined, None


def _drive_formats_for_record(
    browser,
    page,
    adapter,
    formats,
    url,
    manufacturer: str,
    mpn: str,
):
    """Call the production identity-aware driver while allowing narrow legacy test doubles."""

    parameters = inspect.signature(drive_formats).parameters.values()
    accepts_identity = {
        parameter.name for parameter in parameters
    } >= {"expected_manufacturer", "expected_mpn"} or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    if accepts_identity:
        return drive_formats(
            browser,
            page,
            adapter,
            formats,
            url,
            expected_manufacturer=manufacturer,
            expected_mpn=mpn,
        )
    return drive_formats(browser, page, adapter, formats, url)


def _download_gate(adapter, page) -> str:
    """Provider-specific global blockage, consulted only after no file arrived."""
    detector = getattr(adapter, "download_gate", None)
    if detector is None:
        return ""
    try:
        return detector(page) or ""
    except Exception:  # noqa: BLE001 - a detector cannot replace the authoritative timeout
        return ""


def _user_clearance_issue(adapter, page) -> str:
    """Authentication/security gate that only the person may clear."""

    detector = getattr(adapter, "user_clearance_issue", None)
    if detector is None:
        return ""
    try:
        return detector(page) or ""
    except Exception:  # noqa: BLE001 - an unreadable page is not clearance evidence
        return ""


def _retryable_download_issue(adapter, page) -> str:
    """A provider-observed transient export failure, never inferred from elapsed time alone."""

    detector = getattr(adapter, "retryable_download_issue", None)
    if detector is None:
        return ""
    try:
        return detector(page) or ""
    except Exception:  # noqa: BLE001 - retry evidence must be positive and provider-observed
        return ""


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
) -> SourceOutcome:
    base = SourceOutcome(skipped=reason)
    return _with_route_outcome(
        base,
        provider_key=provider_key,
        author_key=author_key,
        label=label,
        attempted=False,
        status="not-attempted",
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


def _resolved_provider_url_issue(adapter, url: str, record) -> str:
    """Reject a resolver result before the managed browser can navigate to it."""

    provider_key = adapter.capability.key
    if not provider_url_allowed(provider_key, url):
        return (
            f"{adapter.capability.label} resolved outside its official provider origin; "
            "automatic navigation was refused."
        )
    detail = page_identity(provider_key, url)
    if detail is not None:
        error = exact_observation_error(record, detail)
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


# What `altium/extract.py::normalize_altium_source` can actually take TODAY. `.lia` is not here
# because normalize_altium_source raises on it, NOT because a P-CAD library is unconvertible -
# that was a wrong conclusion reached without research (owner corrected it, 2026-07-27).
#
# A `.lia` is convertible by SEVERAL routes, and Altium is only one of them (owner pushed back on an
# Altium-only framing, correctly, 2026-07-27):
#   * ACCEL_ASCII is an OPEN, parsed format - `xtoolbox/pcad2kicad` implements a parser for it and
#     KiCad itself natively loads P-CAD ASCII. Nothing about reading a `.lia` is proprietary.
#   * `AltiumSharp` (C#/.NET, open source) reads AND WRITES `.SchLib`/`.PcbLib` explicitly WITHOUT
#     Altium installed - so a conversion needs no license and no Windows.
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


def _model_only_fragment(candidate) -> bool:
    """True for a bare STEP discovered beside a converted provider script package."""

    if getattr(candidate, "symbol_lib_path", None) is not None:
        return False
    if getattr(candidate, "footprint_variants", ()):
        return False
    return getattr(candidate, "model_path", None) is not None


@dataclass
class _Session:
    browser: PlaywrightCaptureBrowser
    ctx_manager: "_SessionManager"
    page: object


class _SessionManager(Protocol):
    def __exit__(self, typ, value, traceback) -> object: ...


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
        """What this source can deliver through its declared browser-access contract.

        Human-visible format labels and machine selectors are separate declarations. A user-driven
        provider can be a supported path without granting Stockroom permission to inspect or
        operate its DOM; both declarations still require an implemented validation/attach seam.
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
        profile_dir: Path | None = None,
        headless: bool = False,
        engine: str = "chromium",
        convert_altium=None,
        collect_variants: bool = False,
        preserve_active_pair: bool = False,
        close_after_supply: bool = False,
        credentials=None,
        run_write=None,
        now_iso=None,
        evidence_store=None,
        cross_eda_verifier=None,
        playwright_runtime: SharedPlaywrightRuntime | None = None,
        user_driven: bool = False,
        operator_authorized: bool = False,
        user_finished: Callable[[], bool] | None = None,
        user_cancelled: Callable[[], bool] | None = None,
        cancel_workflow: Callable[[], None] | None = None,
        user_capture_timeout_s: float = 600.0,
        rate_limiter=None,
        user_clearance_timeout_s: float = 600.0,
        machine_access_check: Callable[[], bool] | None = None,
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
        self._profile_dir = profile_dir
        self._headless = headless
        self._engine = engine
        # Optional provider-package conversion seam. DigiKey's embedded Ultra Librarian route
        # delivers an official Altium scripting project, not native libraries. The runner injects
        # the narrowly recognized converter only for that route.
        self._convert_altium = convert_altium
        # Explicit provider capture may be used after a part is already complete to retain another
        # exact provider's full dual-EDA set. It must never silently replace the active pair; the
        # pair selector owns that decision.
        self._collect_variants = collect_variants
        self._preserve_active_pair = preserve_active_pair
        self._close_after_supply = close_after_supply
        # `(vendor_key) -> (username, password) | None`. Injected, so capture/ never reads the
        # machine config itself and a test can drive sign-in without one.
        self._credentials = credentials
        self._sign_in_error = ""
        self._run_write = run_write or (lambda fn: fn())
        self._now_iso = now_iso
        self._evidence_store = evidence_store
        self._cross_eda_verifier = cross_eda_verifier or verify_cross_eda_component
        self._playwright_runtime = playwright_runtime
        self._user_driven = user_driven
        self._operator_authorized = operator_authorized
        self._user_finished = user_finished
        self._user_cancelled = user_cancelled
        self._cancel_workflow = cancel_workflow
        self._user_capture_timeout_s = user_capture_timeout_s
        self._rate_limiter = rate_limiter
        self._user_clearance_timeout_s = user_clearance_timeout_s
        self._machine_access_check = machine_access_check
        self._sign_in_attempted = False
        self._session: _Session | None = None

    # -- lifecycle -------------------------------------------------------------------------

    def _ensure_session(self) -> _Session:
        """Open the browser once, on the first part that actually needs it.

        Lazy on purpose: a run whose parts are all already complete must not flash a browser
        window at the owner for nothing.
        """
        if self._session is not None:
            return self._session
        browser = PlaywrightCaptureBrowser(
            engine=self._engine,
            download_dir=self._download_root,
            profile_dir=self._profile_dir,
            headless=self._headless,
            provider_key=self._vendor_key,
            playwright_runtime=self._playwright_runtime,
        )
        manager = browser.session()
        page = manager.__enter__()
        self._session = _Session(browser=browser, ctx_manager=manager, page=page)
        return self._session

    def _sign_in_once(self, page) -> None:
        """Sign in for the WHOLE run, on the one session, before the first part.

        Here rather than per part because that is the shape of the real workflow: a 90-part sitting
        must cost one sign-in, and the persistent profile then carries it to later runs entirely.

        Deliberately NOT fatal. A vendor that needs no login, an adapter with no `sign_in`, or
        absent credentials all leave this a silent no-op, and a REFUSED sign-in is recorded and
        allowed to continue - because everything up to the Download button works signed out
        (measured), so the per-part outcome is a far more useful error than a dead run. The reason
        is kept on `_sign_in_error` so those per-part rows can say WHY rather than just "no button".
        """
        self._sign_in_error = sign_in_adapter(
            get_adapter(self._vendor_key), page, self._credentials
        )

    def close(self) -> None:
        """Close the browser. Called by the runner in a finally, so a stopped or failed run never
        leaves a window open."""
        session = self._session
        self._session = None
        if session is None:
            return
        try:
            session.ctx_manager.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass

    # -- the source contract ---------------------------------------------------------------

    def supply(self, record) -> SourceOutcome:
        """Run one part and optionally release the provider session before the next source."""

        try:
            try:
                return self._supply_once(record)
            except Exception as exc:  # noqa: BLE001 - preserve a complete provider ledger
                adapter = get_adapter(self._vendor_key)
                if adapter is None:
                    return SourceOutcome(
                        error=f"{self._vendor_key}: {exc}",
                    )
                return _provider_wide_outcome(
                    adapter,
                    SourceOutcome(error=f"{adapter.capability.label}: {exc}"),
                    attempted=True,
                    status="failed",
                )
        finally:
            if self._close_after_supply:
                self.close()

    def _supply_once(self, record) -> SourceOutcome:
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")
        routes = _capture_routes(adapter)
        if self._user_cancelled and self._user_cancelled():
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(skipped="provider capture workflow was cancelled"),
                attempted=False,
                status="cancelled",
            )

        manufacturer = (getattr(record, "manufacturer", "") or "").strip()
        mpn = (getattr(record, "mpn", "") or "").strip()
        if not manufacturer or not mpn:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(
                    error="browser acquisition requires an exact manufacturer and MPN"
                ),
                attempted=False,
                status="failed",
            )

        needs = list(capture_needs(record))
        if not needs:
            if not self._collect_variants or getattr(record, "passive", False):
                return _provider_wide_outcome(
                    adapter,
                    SourceOutcome(
                        skipped=f"{record.mpn or record.id} needs no captured files"
                    ),
                    attempted=True,
                    status="unavailable",
                )
            # A selected provider is being harvested as an alternative. Ask it for its complete
            # declared set even though the active library itself has no missing requirements.
            needs = sorted(self.provides(), key=lambda requirement: requirement.value)
        # Filter on the formats accepted by this provider's declared access contract and by
        # Stockroom's implemented attach seams. User-driven formats do not require DOM selectors.
        formats = _provider_formats(adapter, needs)
        if not formats:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(
                    skipped=(
                        f"{adapter.capability.label} cannot supply "
                        f"{', '.join(sorted({r.value.split('_')[0] for r in needs}))} for this part"
                    )
                ),
                attempted=True,
                status="unavailable",
            )

        url = adapter.resolve_url(mpn)
        if not url:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(
                    skipped=f"no {adapter.capability.label} page for {record.id}"
                ),
                attempted=True,
                status="unavailable",
            )
        resolved_url_issue = _resolved_provider_url_issue(adapter, url, record)
        if resolved_url_issue:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(error=resolved_url_issue, blocked=True),
                attempted=True,
                status="failed",
            )

        machine_access_issue = self._machine_access_issue(adapter)
        if machine_access_issue:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(error=machine_access_issue, blocked=True),
                attempted=False,
                status="requires-human",
            )
        # The first managed-browser start can perform a saved-credential sign-in before any part
        # navigation. Count it durably as provider access instead of letting login bypass pacing.
        if (
            not self._user_driven
            and self._session is None
            and not self._acquire_rate_limit()
        ):
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(
                    skipped="provider capture was cancelled while waiting for pacing"
                ),
                attempted=False,
                status="cancelled",
            )
        machine_access_issue = self._machine_access_issue(adapter)
        if machine_access_issue:
            return _provider_wide_outcome(
                adapter,
                SourceOutcome(error=machine_access_issue, blocked=True),
                attempted=False,
                status="requires-human",
            )
        session = self._ensure_session()
        if self._user_driven:
            outcomes: list[tuple[str, SourceOutcome]] = []
            for route_index, route in enumerate(routes):
                route_formats = _provider_formats(route, needs)
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
                        attempted=True,
                        status="unavailable",
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
            return _combine_route_outcomes(outcomes)

        outcomes: list[tuple[str, SourceOutcome]] = []
        for route_index, route in enumerate(routes):
            route_formats = _provider_formats(route, needs)
            if not route_formats:
                outcome = _with_route_outcome(
                    SourceOutcome(
                        skipped=f"{route.capability.label} has no accepted format for this task"
                    ),
                    provider_key=self._vendor_key,
                    author_key=_author_key(self._vendor_key, route),
                    label=route.capability.label,
                    attempted=True,
                    status="unavailable",
                )
            else:
                raw_outcome = self._supply_automated_route(
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
                                author_key=_author_key(self._vendor_key, later_route),
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

    def _supply_automated_route(
        self,
        record,
        session: _Session,
        adapter,
        manufacturer: str,
        mpn: str,
        url: str,
        formats: list[str],
    ) -> SourceOutcome:
        """Capture one immutable DigiKey author route on its own page/broker binding."""

        evidence_provider_key = getattr(
            adapter,
            "evidence_provider_key",
            self._evidence_provider_key,
        )
        open_task_page = getattr(session.browser, "task_page", None)
        broker = (
            DownloadBroker(
                DownloadTask(
                    task_id=record.id,
                    manufacturer_key=manufacturer,
                    mpn_canonical=mpn,
                    staging_root=self._download_root,
                    surface_key=self._vendor_key,
                    evidence_provider_key=evidence_provider_key,
                )
            )
            if callable(open_task_page)
            else None
        )
        before = len(session.browser.captured)
        detail_url = ""
        try:
            if broker is not None:
                assert callable(open_task_page)
                page_context = open_task_page(broker)
            else:
                page_context = nullcontext(session.page)
            with page_context as task_page:
                navigate = getattr(task_page, "goto", None)
                if not callable(navigate):
                    return SourceOutcome(
                        error=f"{adapter.capability.label} browser page cannot navigate.",
                        blocked=True,
                    )
                # Each attributed route owns a fresh broker-bound tab. Sign-in is run-scoped, but
                # tab initialization is not: the second and third tabs still start at about:blank.
                # DigiKey's provider catalogue is client-rendered and a cold tab that receives
                # only the later format navigation can race hydration, falsely reporting Ultra
                # Librarian absent after SnapMagic initialized the first tab.
                task_url = str(getattr(task_page, "url", "") or "")
                if not self._sign_in_attempted or task_url in {"", "about:blank"}:
                    navigate(url, wait_until="domcontentloaded")
                sign_in_outcome = self._prepare_sign_in(
                    session,
                    task_page,
                    adapter,
                    manufacturer,
                    mpn,
                )
                if sign_in_outcome is not None:
                    return sign_in_outcome
                report, failure = self._drive_automated(
                    session,
                    task_page,
                    adapter,
                    formats,
                    url,
                    manufacturer,
                    mpn,
                )
                # FAILURE IS CHECKED FIRST, and the order is load-bearing. A vendor whose LAST
                # format was submitted and never arrived comes back with `submitted=False` (the
                # flag is only set after the file lands) AND an error - so testing `submitted`
                # first would report a vanished download as "the vendor simply had nothing".
                if failure is not None:
                    return SourceOutcome(error=failure, blocked=report.blocked)
                if not report.submitted:
                    why = report.message or "the vendor offered no download"
                    if self._sign_in_error:
                        # Everything up to the Download button works signed out, so a refused
                        # sign-in is the real cause of "no Download button" and must be explicit.
                        why = f"{why} ({self._sign_in_error})"
                    if report.blocked:
                        return SourceOutcome(error=why, blocked=True)
                    return SourceOutcome(skipped=why)
                if broker is not None:
                    # Keep the exact task binding through a short quiet period. One provider click
                    # can legitimately emit symbol, footprint, and model as separate downloads;
                    # unbinding after the first file would misfile a late sibling under the next
                    # component in a batch.
                    broker.wait_for_playwright(
                        task_page,
                        minimum=1,
                        settle_seconds=0.75,
                    )
                detail_url = getattr(task_page, "url", "") or ""
                evidence_detail_url = getattr(adapter, "evidence_detail_url", None)
                if callable(evidence_detail_url):
                    detail_url = evidence_detail_url(
                        task_page,
                        expected_manufacturer=manufacturer,
                        expected_mpn=mpn,
                    )
        except Exception as exc:  # noqa: BLE001 - one part's failure is a row, not a crash
            return SourceOutcome(error=f"{adapter.capability.label}: {exc}")

        landed = list(broker.receipts) if broker is not None else session.browser.captured[before:]
        if not landed:
            return SourceOutcome(error="the vendor download did not produce a file")

        if getattr(adapter, "supplementary_only", False):
            return self._retain_supplementary(
                record,
                landed,
                detail_url=detail_url,
                surface_key=self._vendor_key,
                evidence_provider_key=evidence_provider_key,
            )

        return self._attach(
            record,
            landed,
            url,
            detail_url=detail_url,
            evidence_provider_key=evidence_provider_key,
        )

    def _retain_supplementary(
        self,
        record,
        landed,
        *,
        detail_url: str,
        surface_key: str,
        evidence_provider_key: str,
        require_step_model: bool = True,
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
        identity_error = exact_observation_error(record, observed)
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
    ) -> SourceOutcome:
        """Preserve raw bytes while refusing a mixed or one-tool active projection."""

        retained = self._retain_supplementary(
            record,
            landed,
            detail_url=detail_url,
            surface_key=self._vendor_key,
            evidence_provider_key=evidence_provider_key,
            require_step_model=False,
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

    def _machine_access_issue(self, adapter) -> str:
        """Fail closed when a machine-eligible adapter lacks live authorization."""

        if self._user_driven or self._operator_authorized:
            return ""
        if adapter.capability.browser_access != "machine_allowed":
            return (
                f"{adapter.capability.label} is not authorized for machine-driven capture; "
                "use its user-driven workflow."
            )
        if self._machine_access_check is None:
            return (
                f"{adapter.capability.label} automatic capture requires an explicit live "
                "machine-authorization check."
            )
        try:
            allowed = self._machine_access_check()
        except Exception:  # noqa: BLE001 - unreadable authorization is revoked authorization
            allowed = False
        if allowed:
            return ""
        return (
            f"{adapter.capability.label} automatic access is disabled or its private-evaluation "
            "authorization is no longer active."
        )

    def _acquire_rate_limit(self) -> bool:
        """Acquire the configured limiter and keep a pending wait cancellable."""

        if self._rate_limiter is None:
            return True
        acquire = self._rate_limiter.acquire
        parameters = inspect.signature(acquire).parameters.values()
        supports_cancel = "should_cancel" in {
            parameter.name for parameter in parameters
        } or any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters)
        result = (
            acquire(should_cancel=self._user_cancelled)
            if supports_cancel
            else acquire()
        )
        return result is not False

    def _prepare_sign_in(
        self,
        session: _Session,
        page,
        adapter,
        manufacturer: str,
        mpn: str,
    ) -> SourceOutcome | None:
        """Attempt saved-credential sign-in once and hand any security step to the person."""

        if self._user_driven or self._sign_in_attempted:
            return None
        self._sign_in_attempted = True
        detector = getattr(adapter, "user_clearance_issue", None)
        if not callable(detector):
            self._sign_in_once(page)
            return None

        def current_issue() -> str:
            return str(detector(page) or "")

        def security_issue() -> str:
            # A normal signed-out page is not a security gate. The provider's broader
            # user-clearance detector also reports its Login link, so using it before
            # `_sign_in_once` deadlocks automatic login: Stockroom waits for the person
            # without ever trying the saved credentials. Only actual CAPTCHA/MFA/passkey
            # evidence is eligible for the pre-login handoff.
            from stockroom.capture.vendors import _security_verification_issue

            return _security_verification_issue(page, adapter.capability.label)

        def clear_security_gate(issue_detector=current_issue) -> SourceOutcome | None:
            issue = issue_detector()
            if not issue:
                return None
            wait_for_clearance = getattr(session.browser, "wait_for_user_clearance", None)
            if not callable(wait_for_clearance):
                return SourceOutcome(error=issue, blocked=True)
            cleared = wait_for_clearance(
                page,
                provider_label=adapter.capability.label,
                author_route=_provider_hud_author_route(adapter),
                manufacturer=manufacturer,
                mpn=mpn,
                message=issue,
                issue_detector=issue_detector,
                should_cancel=self._user_cancelled,
                timeout_s=self._user_clearance_timeout_s,
            )
            if cleared:
                authorization_issue = self._machine_access_issue(adapter)
                if authorization_issue:
                    return SourceOutcome(error=authorization_issue, blocked=True)
                return None
            cancelled = self._user_cancelled is not None and self._user_cancelled()
            return SourceOutcome(
                error=(
                    "provider capture was cancelled during the security handoff"
                    if cancelled
                    else f"{adapter.capability.label} still needs its sign-in or security check "
                    "to be cleared; no provider control was bypassed."
                ),
                blocked=not cancelled,
            )

        gate_outcome = clear_security_gate(security_issue)
        if gate_outcome is not None:
            return gate_outcome
        signed_in = getattr(adapter, "signed_in", None)
        if callable(signed_in) and signed_in(page):
            self._sign_in_error = ""
            return None
        self._sign_in_once(page)
        gate_outcome = clear_security_gate()
        if gate_outcome is not None:
            return gate_outcome
        signed_in = getattr(adapter, "signed_in", None)
        if callable(signed_in) and signed_in(page):
            self._sign_in_error = ""
        return None

    def _drive_automated(
        self,
        session: _Session,
        page,
        adapter,
        formats: list[str],
        url: str,
        manufacturer: str,
        mpn: str,
    ):
        """Drive, hand security controls to the person, then resume without bypassing them."""

        # One handoff can cover a login -> 2FA -> challenge sequence because the browser waits until
        # the detector sees no security gate. A second handoff covers a distinct post-submit gate.
        # Anything beyond that is a provider loop and fails closed instead of keeping the user stuck.
        for handoff_number in range(3):
            machine_access_issue = self._machine_access_issue(adapter)
            if machine_access_issue:
                report = DriveReport(
                    missed=list(formats),
                    blocked=True,
                    message=machine_access_issue,
                )
                return report, report.message
            if not self._acquire_rate_limit():
                report = DriveReport(
                    missed=list(formats),
                    message="provider capture was cancelled while waiting for pacing",
                )
                return report, report.message
            machine_access_issue = self._machine_access_issue(adapter)
            if machine_access_issue:
                report = DriveReport(
                    missed=list(formats),
                    blocked=True,
                    message=machine_access_issue,
                )
                return report, report.message
            report, failure = _drive_formats_for_record(
                session.browser,
                page,
                adapter,
                formats,
                url,
                manufacturer,
                mpn,
            )
            if not report.requires_user_clearance:
                return report, failure
            if handoff_number >= 2:
                return (
                    report,
                    f"{adapter.capability.label} repeatedly returned to a security or sign-in "
                    "gate after it was cleared; automatic capture stopped.",
                )
            wait_for_clearance = getattr(session.browser, "wait_for_user_clearance", None)
            if not callable(wait_for_clearance):
                return report, failure or report.message
            detector = getattr(adapter, "user_clearance_issue", None)
            if not callable(detector):
                return report, failure or report.message
            cleared = wait_for_clearance(
                page,
                provider_label=adapter.capability.label,
                author_route=_provider_hud_author_route(adapter),
                manufacturer=manufacturer,
                mpn=mpn,
                message=failure or report.message,
                issue_detector=lambda: detector(page) or "",
                should_cancel=self._user_cancelled,
                timeout_s=self._user_clearance_timeout_s,
            )
            if not cleared:
                report.blocked = True
                return (
                    report,
                    f"{adapter.capability.label} still needs the sign-in or security check to be "
                    "cleared; no provider control was bypassed.",
                )
        raise AssertionError("unreachable security-handoff loop")

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
        try:
            result = session.browser.capture_user_downloads(
                url,
                broker,
                hud=ProviderHudSpec(
                    provider_label=provider_label,
                    author_route=_provider_hud_author_route(adapter),
                    manufacturer=manufacturer,
                    mpn=mpn,
                    required_file_labels=_provider_hud_labels(adapter, formats),
                ),
                should_finish=self._user_finished,
                should_cancel=self._user_cancelled,
                timeout_s=self._user_capture_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - one part's failure is a row, not a dead run
            return SourceOutcome(error=f"{provider_label}: {exc}")

        received = len(result.files)
        if result.status == "cancelled":
            if self._cancel_workflow is not None:
                self._cancel_workflow()
            suffix = f" after receiving {received} file(s)" if received else ""
            return SourceOutcome(
                skipped=f"{provider_label} capture was cancelled{suffix}; nothing was attached",
                blocked=True,
            )
        if result.status == "try_another" and not result.files:
            suffix = f" after receiving {received} file(s)" if received else ""
            return SourceOutcome(
                skipped=(
                    f"{provider_label} was left for another provider{suffix}; nothing was attached"
                ),
                blocked=True,
            )
        if result.status == "timed_out" and not result.files:
            suffix = f" after receiving {received} file(s)" if received else ""
            return SourceOutcome(
                error=f"{provider_label} capture timed out{suffix}; nothing was attached"
            )
        if not result.files:
            return SourceOutcome(error="the vendor download did not produce a file")

        if getattr(adapter, "supplementary_only", False):
            return self._retain_supplementary(
                record,
                list(result.files),
                detail_url=result.final_url,
                surface_key=self._vendor_key,
                evidence_provider_key=evidence_provider_key,
            )
        return self._attach(
            record,
            list(result.files),
            url,
            detail_url=result.final_url,
            evidence_provider_key=evidence_provider_key,
        )

    def _attach(
        self,
        record,
        landed,
        url: str,
        *,
        detail_url: str = "",
        evidence_provider_key: str = "",
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
                return SourceOutcome(error=binding_issue)
        attributed = {
            value
            for item in landed
            if (value := getattr(item, "evidence_provider_key", ""))
        }
        if evidence_provider_key and attributed != {provider_key}:
            return SourceOutcome(
                error=(
                    "capture route attribution mismatch: "
                    f"expected {provider_key!r}, received {sorted(attributed)!r}"
                )
            )
        cleanup_callbacks = []
        try:
            return self._attach_impl(
                record,
                landed,
                url,
                detail_url=detail_url,
                evidence_provider_key=provider_key,
                cleanup_callbacks=cleanup_callbacks,
            )
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
        captured_altium = _altium_libraries(landed)
        if captured_altium is not None:
            cleanup_callbacks.append(captured_altium.cleanup)
        altium_sources = [] if captured_altium is None else list(captured_altium.paths)
        route_converter = (
            self._convert_altium
            if evidence_provider_key == self._evidence_provider_key
            else None
        )
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
            except Exception as exc:  # noqa: BLE001 - keep usable KiCad and report this gap
                conversion_failure = f"could not convert the provider's Altium package: {exc}"
        pipeline = self._make_pipeline()
        try:
            load_current = getattr(getattr(pipeline, "ops", None), "load_record", None)
            if callable(load_current):
                record = load_current(record.id)
            preserve_active_pair = (
                (self._preserve_active_pair or self._collect_variants)
                and self._evidence_store is not None
                and active_pair_is_verified(self._evidence_store, record)
            )
            candidates = []
            inspect_errors: list[Exception] = []
            # Exclusive-format providers deliver KiCad and Altium as sibling files. Inspecting
            # the whole list in one call aborts on the Altium-only sibling and discards the valid
            # KiCad candidate already found in the first file. Inspect each captured file through
            # the same pipeline and combine successful candidates instead.
            for item in landed:
                try:
                    candidates.extend(pipeline.inspect(inputs=[item.path]))
                except Exception as exc:  # noqa: BLE001
                    inspect_errors.append(exc)
            if not landed:
                try:
                    candidates.extend(pipeline.inspect(inputs=[]))
                except Exception as exc:  # noqa: BLE001
                    inspect_errors.append(exc)
            if converted_altium:
                # DigiKey's UL script ZIP carries a root STEP named for the package, not the MPN.
                # The ingest fingerprint correctly exposes it as a model-only candidate, but it
                # is supplemental package data rather than a second KiCad definition. Keep any
                # symbol/footprint-bearing candidate; drop model-only fragments so one complete
                # same-download dual-EDA set is evaluated rather than competing fragments.
                candidates = [
                    candidate
                    for candidate in candidates
                    if not _model_only_fragment(candidate)
                ]
            if not candidates and not altium_sources and inspect_errors:
                return SourceOutcome(error=f"could not read the download: {inspect_errors[0]}")

            selection = select_exact_candidate(
                record,
                candidates,
                vendor_key=evidence_provider_key,
                detail_url=detail_url,
            )
            candidate = selection.candidate
            if selection.error:
                return SourceOutcome(error=selection.error)
            if candidate is None:
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
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
                    reason=(
                        "provider download is not one complete dual-EDA source set; missing "
                        + ", ".join(absent)
                        + (f"; {conversion_failure}" if conversion_failure else "")
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
                )
            except Exception as exc:  # noqa: BLE001 - no partial projection on any failure
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    reason=f"same-set cross-EDA verification failed: {exc}",
                )
            if not cross_eda_verified:
                return self._retain_incomplete_cad_set(
                    record,
                    landed,
                    detail_url=detail_url,
                    evidence_provider_key=evidence_provider_key,
                    reason="same-set cross-EDA verification did not prove the provider bundle",
                )
            try:
                identity = exact_identity(record)
                kicad_resolved = resolve_cad_variant(
                    self._evidence_store,
                    identity=identity,
                    tool="kicad",
                    manifest_digest=evidence_digest,
                )
                altium_resolved = resolve_cad_variant(
                    self._evidence_store,
                    identity=identity,
                    tool="altium",
                    manifest_digest=evidence_digest,
                )
                if not same_cad_evidence_set(
                    kicad_resolved.descriptor,
                    altium_resolved.descriptor,
                ):
                    raise ValueError(
                        "resolved KiCad and Altium projections do not share one evidence set"
                    )
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
