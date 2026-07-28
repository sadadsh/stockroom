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

import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stockroom.capture.browser import PlaywrightCaptureBrowser, SharedPlaywrightRuntime
from stockroom.capture.complete import SourceOutcome
from stockroom.capture.cross_eda import (
    CrossEdaVerificationError,
    verify_cross_eda_component,
)
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.evidence import (
    BROWSER_CAPTURE_ADAPTER_VERSION,
    record_browser_cad_evidence,
)
from stockroom.capture.identity import select_exact_candidate
from stockroom.capture.requirements import Requirement, asset_present, capture_needs
from stockroom.capture.vendors import formats_for, get_adapter
from stockroom.model.asset import AssetOrigin

# How long to wait for the vendor's file after the adapter submits. Generous because a heavy part's
# export genuinely generates server-side for tens of seconds (measured live on DigiKey, 2026-07-23),
# and this is a BACKSTOP: the wait ends the instant the file appears in the saved list.
_DOWNLOAD_TIMEOUT_MS = 120_000
_COHERENT_CAD_FORMATS = ("kicad", "model", "altium")


def _wait_for_capture(
    browser,
    page,
    before: int,
    timeout_s: float,
    gap: float = 0.25,
    *,
    errors_before: int | None = None,
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


def drive_formats(browser, page, adapter, formats, url, timeout_s: float | None = None):
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

    Re-navigates before each exclusive format, because taking a download generally leaves the
    vendor's modal closed or the page changed; `open_panel` is cheap and idempotent, and assuming
    the panel survived a download is the kind of guess that works on a fixture and fails on the
    real site.

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
        report = adapter.drive(page, list(formats))
        if not report.submitted:
            return report, None
        if not _wait_for_capture(
            browser,
            page,
            mark,
            wait_s,
            errors_before=error_mark,
        ):
            gate = _download_gate(adapter, page)
            if gate:
                report.blocked = True
                return report, gate
            return report, f"{label} did not deliver a file within {wait_s:.0f}s"
        return report, None

    combined = DriveReport()
    for fmt in formats:
        mark = len(browser.captured)
        error_mark = len(getattr(browser, "download_errors", ()))
        try:
            page.goto(url, wait_until="domcontentloaded")
            one = adapter.drive(page, [fmt])
        except Exception as exc:  # noqa: BLE001 - one format failing is a row, not a dead run
            combined.missed.append(fmt)
            combined.message = f"{label}: {exc}"
            continue
        if not one.submitted:
            combined.missed.extend(one.missed or [fmt])
            combined.blocked = combined.blocked or one.blocked
            if one.message:
                combined.message = one.message
            if one.blocked:
                # Auth/challenge/account state is provider-wide. Trying the remaining format
                # buttons cannot change it and only repeats the same failure.
                return combined, None
            continue
        if not _wait_for_capture(
            browser,
            page,
            mark,
            wait_s,
            errors_before=error_mark,
        ):
            gate = _download_gate(adapter, page)
            if gate:
                combined.blocked = True
                return combined, gate
            return combined, f"{label} did not deliver {fmt} within {wait_s:.0f}s"
        combined.selected.extend(one.selected or [fmt])
        combined.submitted = True
    if combined.selected:
        combined.message = f"Requested {' and '.join(combined.selected)} from {label}."
    return combined, None


def _download_gate(adapter, page) -> str:
    """Provider-specific global blockage, consulted only after no file arrived."""
    detector = getattr(adapter, "download_gate", None)
    if detector is None:
        return ""
    try:
        return detector(page) or ""
    except Exception:  # noqa: BLE001 - a detector cannot replace the authoritative timeout
        return ""


def _provider_formats(adapter, needs) -> list[str]:
    """Request one coherent bundle when a provider can supply every cross-EDA artifact.

    Evidence proves a relationship between actual bytes, not between old library references and
    one newly downloaded side. Therefore an Altium-only (or any other partial) repair through a
    complete-bundle provider downloads KiCad symbol/footprint, STEP, and native Altium from that
    SAME provider. Verification runs before any existing asset can be replaced.
    """
    selectable = set(adapter.capability.version_pins)
    requested = [fmt for fmt in formats_for(needs) if fmt in selectable]
    if requested and set(_COHERENT_CAD_FORMATS) <= selectable:
        return list(_COHERENT_CAD_FORMATS)
    return requested


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


def _altium_libraries(landed) -> list[Path]:
    """Altium library files inside the download, unpacked with the ingest sandbox.

    Uses `unpack_inputs` rather than a second unzip: it already handles a directory, a loose file
    and a zip identically, and its `_safe_extract` refuses path traversal. A private zip reader
    here would be a second implementation of the one thing the ingest layer already does safely.

    The temp tree is intentionally NOT cleaned up here - the paths are handed to
    `attach_altium_assets`, which copies them into the library inside its own transaction, and
    tearing the tree down first would pull the files out from under it. It lives under the system
    temp dir and is reclaimed there.
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
        return []
    return found


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
        """What this source can actually deliver, derived from the ADAPTER's measured pins.

        Never a hardcoded set, and never keyed on a tool NAME: the honest answer to "what can you
        really fetch" is which export controls the adapter has measured AND this app can then
        STORE - which is what `version_pins` records. A vendor that pins none of a part's needs is
        never scheduled for it, so a pin that cannot be attached would make the engine chase a
        requirement forever (see UltraLibrarianAdapter on why altium is not pinned yet).
        """
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return frozenset()
        pins = set(adapter.capability.version_pins)
        out: set[Requirement] = set()
        if "kicad" in pins:
            out |= {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}
        if "model" in pins:
            out.add(Requirement.KICAD_MODEL)
        if "altium" in pins:
            out |= {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}
        return frozenset(out)

    def __init__(
        self,
        make_pipeline,
        *,
        vendor: str = "ultralibrarian",
        download_root: Path,
        profile_dir: Path | None = None,
        headless: bool = False,
        engine: str = "chromium",
        attach_altium=None,
        credentials=None,
        run_write=None,
        now_iso=None,
        evidence_store=None,
        cross_eda_verifier=None,
        playwright_runtime: SharedPlaywrightRuntime | None = None,
    ) -> None:
        self._make_pipeline = make_pipeline
        self._vendor_key = vendor
        adapter = get_adapter(vendor)
        # Public, human-facing identity for completion reports. `key` must remain "guided"
        # because it names the source implementation, while two instances in one fallback chain
        # need distinct provider names so their honest decline reasons remain distinguishable.
        self.report_label = adapter.capability.label if adapter is not None else vendor
        self._download_root = Path(download_root)
        self._download_root.mkdir(parents=True, exist_ok=True)
        self._profile_dir = profile_dir
        self._headless = headless
        self._engine = engine
        # `library_ops.attach_altium_assets`, injected rather than imported, so this module stays
        # free of the mutation layer and a test can drive the Altium path without a real library.
        self._attach_altium = attach_altium
        # `(vendor_key) -> (username, password) | None`. Injected, so capture/ never reads the
        # machine config itself and a test can drive sign-in without one.
        self._credentials = credentials
        self._sign_in_error = ""
        self._run_write = run_write or (lambda fn: fn())
        self._now_iso = now_iso
        self._evidence_store = evidence_store
        self._cross_eda_verifier = cross_eda_verifier or verify_cross_eda_component
        self._playwright_runtime = playwright_runtime
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
        self._sign_in_once(page)
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
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")

        manufacturer = (getattr(record, "manufacturer", "") or "").strip()
        mpn = (getattr(record, "mpn", "") or "").strip()
        if not manufacturer or not mpn:
            return SourceOutcome(error="browser acquisition requires an exact manufacturer and MPN")

        needs = list(capture_needs(record))
        if not needs:
            return SourceOutcome(skipped=f"{record.mpn or record.id} needs no captured files")
        # Filter on what the adapter can ACTUALLY select (its measured pins), not on a tool
        # name. Ultra Librarian nominally "does Altium", but its Altium export is a script that
        # produces no library files - so asking for it produced a confident success that attached
        # nothing. `version_pins` is the honest answer to "what can you really fetch".
        formats = _provider_formats(adapter, needs)
        if not formats:
            return SourceOutcome(
                skipped=(
                    f"{adapter.capability.label} cannot supply "
                    f"{', '.join(sorted({r.value.split('_')[0] for r in needs}))} for this part"
                )
            )

        url = adapter.resolve_url(mpn)
        if not url:
            return SourceOutcome(skipped=f"no {adapter.capability.label} page for {record.id}")

        session = self._ensure_session()
        open_task_page = getattr(session.browser, "task_page", None)
        broker = (
            DownloadBroker(
                DownloadTask(
                    task_id=record.id,
                    manufacturer_key=manufacturer,
                    mpn_canonical=mpn,
                    staging_root=self._download_root,
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
                report, failure = drive_formats(session.browser, task_page, adapter, formats, url)
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
        except Exception as exc:  # noqa: BLE001 - one part's failure is a row, not a crash
            return SourceOutcome(error=f"{adapter.capability.label}: {exc}")

        landed = list(broker.receipts) if broker is not None else session.browser.captured[before:]
        if not landed:
            return SourceOutcome(error="the vendor download did not produce a file")

        return self._attach(
            record,
            landed,
            url,
            detail_url=detail_url,
        )

    def _attach(self, record, landed, url: str, *, detail_url: str = "") -> SourceOutcome:
        """Turn the downloaded file(s) into attached assets, with provenance.

        Reuses the ingest pipeline the rest of the app already attaches through, so a guided
        capture and a hand-dropped zip land identically - there is no second attach path to drift.

        BOTH TOOLS, through their own existing seams. KiCad assets go through `IngestPipeline`;
        Altium libraries go through `library_ops.attach_altium_assets`, which was already written
        and already atomic but which guided capture never called - so a vendor shipping real
        `.SchLib`/`.PcbLib` had them downloaded and then silently dropped. Each attach is its own
        atomic commit (two commits when a download carries both), because that is what the two
        underlying seams each guarantee; neither can leave a partial write behind.
        """
        adapter = get_adapter(self._vendor_key)
        if adapter is None:
            return SourceOutcome(error=f"no capture adapter for vendor {self._vendor_key!r}")
        offered: list[Requirement] = []
        failures: list[str] = []
        identity_error = ""
        evidence_digest = ""
        cross_eda_verified = False
        altium_sources = _altium_libraries(landed)
        pipeline = self._make_pipeline()
        try:
            try:
                candidates = pipeline.inspect(inputs=[item.path for item in landed])
            except Exception as exc:  # noqa: BLE001
                return SourceOutcome(error=f"could not read the download: {exc}")

            kicad_offered: list[Requirement] = []
            selection = select_exact_candidate(
                record,
                candidates,
                vendor_key=self._vendor_key,
                detail_url=detail_url,
            )
            candidate = selection.candidate
            identity_error = selection.error
            if candidate is not None:
                candidate.entry_name = record.mpn or candidate.entry_name or candidate.mpn
                if candidate.symbol_lib_path is not None:
                    kicad_offered.append(Requirement.KICAD_SYMBOL)
                if candidate.footprint_variants:
                    kicad_offered.append(Requirement.KICAD_FOOTPRINT)
                if candidate.model_path is not None:
                    kicad_offered.append(Requirement.KICAD_MODEL)
                if self._evidence_store is not None:
                    try:
                        evidence_digest, cross_eda_verified = record_browser_cad_evidence(
                            store=self._evidence_store,
                            record=record,
                            candidate=candidate,
                            provider_key=self._vendor_key,
                            detail_url=detail_url,
                            altium_sources=tuple(altium_sources),
                            cross_eda_verifier=self._cross_eda_verifier,
                        )
                    except CrossEdaVerificationError as exc:
                        # A bad/unsupported Altium binary must not poison an independently valid
                        # KiCad set. Record only the proved KiCad artifacts, retain Altium as
                        # unsatisfied, and surface the exact cross-EDA reason below.
                        failures.append(f"cross-EDA verification failed: {exc}")
                        evidence_digest, cross_eda_verified = record_browser_cad_evidence(
                            store=self._evidence_store,
                            record=record,
                            candidate=candidate,
                            provider_key=self._vendor_key,
                            detail_url=detail_url,
                        )
                    except Exception as exc:  # noqa: BLE001 - fail closed before any library write
                        return SourceOutcome(error=f"CAD evidence verification failed: {exc}")
            elif self._evidence_store is not None and not identity_error:
                return SourceOutcome(
                    error=(
                        "CAD evidence verification failed: the provider download has no exact "
                        "KiCad symbol, footprint, and STEP set"
                    )
                )
            origin = AssetOrigin(
                vendor=self._vendor_key,
                url=url,
                captured_at=self._now_iso() if self._now_iso else "",
                extra=(
                    {}
                    if not evidence_digest
                    else {
                        "evidence_adapter_version": BROWSER_CAPTURE_ADAPTER_VERSION,
                        "evidence_manifest_digest": evidence_digest,
                        "evidence_operation": "cad:kicad",
                    }
                ),
            )
            if kicad_offered:
                try:
                    self._run_write(
                        lambda: pipeline.attach_assets(record.id, candidate, origin=origin)
                    )
                    offered.extend(kicad_offered)
                except Exception as exc:  # noqa: BLE001 - each attach is atomic; a failure is a row
                    failures.append(str(exc))
        finally:
            pipeline.cleanup()

        # A mismatched or ambiguous KiCad candidate poisons the whole browser download. Do not
        # attach native Altium files beside it and then hide the identity failure behind a partial
        # success: both came from the same untrusted selection.
        if identity_error:
            return SourceOutcome(error=identity_error)

        if altium_sources and self._evidence_store is not None and not cross_eda_verified:
            failures.append(
                "native Altium files were left unattached: "
                "cross-EDA terminal, pad, and package equivalence is not verified"
            )
        else:
            offered.extend(
                self._attach_altium_assets(
                    record,
                    landed,
                    failures,
                    origin,
                    sources=altium_sources,
                )
            )

        if offered:
            return SourceOutcome(
                satisfied=tuple(offered),
                error="; ".join(failures),
            )
        if failures:
            return SourceOutcome(error="; ".join(failures))
        return SourceOutcome(
            error=(
                f"{adapter.capability.label} delivered a file with nothing this part can use in it"
            )
        )

    def _attach_altium_assets(
        self,
        record,
        landed,
        failures: list[str],
        origin=None,
        *,
        sources: list[Path] | None = None,
    ) -> list[Requirement]:
        """Attach any Altium libraries in the download, and report what the RECORD then holds.

        Reports from the record rather than from what was requested, because
        `attach_altium_assets` decides per side which of symbol/footprint it could actually bind -
        a vendor may ship only one. Reading it back is the difference between "we sent the files"
        and "the part has them", and only the second is a success worth reporting.

        Silent no-op when the runner supplied no attach callable or the download carries no Altium
        library, so a KiCad-only vendor is completely unaffected.
        """
        if self._attach_altium is None:
            return []
        attach_altium = self._attach_altium
        sources = _altium_libraries(landed) if sources is None else sources
        if not sources:
            return []
        try:
            # The SAME origin the KiCad half files. Without it a guided capture recorded where its
            # symbol came from and left the Altium library beside it unattributed, which is the
            # provenance story holding for one tool and quietly not the other.
            updated = self._run_write(lambda: attach_altium(record.id, *sources, origin=origin))
        except Exception as exc:  # noqa: BLE001 - atomic: a failure leaves the part untouched
            failures.append(f"could not attach the Altium libraries: {exc}")
            return []
        if updated is None:
            return []
        bundle = updated.assets_for("altium") or {}
        got: list[Requirement] = []
        if asset_present(bundle.get("symbol")):
            got.append(Requirement.ALTIUM_SYMBOL)
        if asset_present(bundle.get("footprint")):
            got.append(Requirement.ALTIUM_FOOTPRINT)
        return got
