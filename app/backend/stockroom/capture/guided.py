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

import time
from dataclasses import dataclass
from pathlib import Path

from stockroom.capture.browser import PlaywrightCaptureBrowser
from stockroom.capture.complete import SourceOutcome
from stockroom.capture.requirements import Requirement, capture_needs
from stockroom.capture.vendors import formats_for, get_adapter
from stockroom.model.asset import AssetOrigin

# How long to wait for the vendor's file after the adapter submits. Generous because a heavy part's
# export genuinely generates server-side for tens of seconds (measured live on DigiKey, 2026-07-23),
# and this is a BACKSTOP: the wait ends the instant the file appears in the saved list.
_DOWNLOAD_TIMEOUT_MS = 120_000


def _wait_for_capture(browser, page, before: int, timeout_s: float, gap: float = 0.25) -> bool:
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
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(browser.captured) > before:
            return True
        page.wait_for_timeout(gap * 1000)
    # One last look: a file that landed inside the final gap still counts.
    return len(browser.captured) > before


@dataclass
class _Session:
    browser: PlaywrightCaptureBrowser
    ctx_manager: object
    page: object


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
        run_write=None,
        now_iso=None,
    ) -> None:
        self._make_pipeline = make_pipeline
        self._vendor_key = vendor
        self._download_root = Path(download_root)
        self._profile_dir = profile_dir
        self._headless = headless
        self._engine = engine
        self._run_write = run_write or (lambda fn: fn())
        self._now_iso = now_iso
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
        )
        manager = browser.session()
        page = manager.__enter__()
        self._session = _Session(browser=browser, ctx_manager=manager, page=page)
        return self._session

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

        needs = list(capture_needs(record))
        if not needs:
            return SourceOutcome(skipped=f"{record.mpn or record.id} needs no captured files")
        # Filter on what the adapter can ACTUALLY select (its measured pins), not on a tool
        # name. Ultra Librarian nominally "does Altium", but its Altium export is a script that
        # produces no library files - so asking for it produced a confident success that attached
        # nothing. `version_pins` is the honest answer to "what can you really fetch".
        selectable = set(adapter.capability.version_pins)
        formats = [f for f in formats_for(needs) if f in selectable]
        if not formats:
            return SourceOutcome(
                skipped=(
                    f"{adapter.capability.label} cannot supply "
                    f"{', '.join(sorted({r.value.split('_')[0] for r in needs}))} for this part"
                )
            )

        url = adapter.resolve_url(record.mpn or "")
        if not url:
            return SourceOutcome(skipped=f"no {adapter.capability.label} page for {record.id}")

        session = self._ensure_session()
        before = len(session.browser.captured)
        try:
            session.page.goto(url, wait_until="domcontentloaded")
            report = adapter.drive(session.page, formats)
            if not report.submitted:
                return SourceOutcome(skipped=report.message or "the vendor offered no download")
            # Wait for the FILE TO BE SAVED, not for the download EVENT.
            #
            # `wait_for_event("download")` RACES the `on("download")` handler the browser session
            # registers up front. Whichever listener is active when the event fires consumes it, so
            # a download that completes quickly is taken by the handler and the wait then runs to
            # its full timeout - reporting a failure for a file that is already on disk. Measured
            # 2026-07-27: this timed out at 60s on a download that had landed correctly, which was
            # briefly and wrongly read as "Camoufox cannot download".
            #
            # `browser.captured` grows only AFTER `save_as` returns, so polling it observes the file
            # genuinely existing. The timeout stays a backstop for a vendor that never answers,
            # never the thing that decides success.
            if not _wait_for_capture(
                session.browser, session.page, before, _DOWNLOAD_TIMEOUT_MS / 1000.0
            ):
                return SourceOutcome(
                    error=f"{adapter.capability.label} did not deliver a file within "
                    f"{_DOWNLOAD_TIMEOUT_MS // 1000}s"
                )
        except Exception as exc:  # noqa: BLE001 - one part's failure is a row, not a crash
            return SourceOutcome(error=f"{adapter.capability.label}: {exc}")

        landed = session.browser.captured[before:]
        if not landed:
            return SourceOutcome(error="the vendor download did not produce a file")

        return self._attach(record, landed, url)

    def _attach(self, record, landed, url: str) -> SourceOutcome:
        """Turn the downloaded file(s) into attached assets, with provenance.

        Reuses the ingest pipeline the rest of the app already attaches through, so a guided
        capture and a hand-dropped zip land identically - there is no second attach path to drift.
        """
        adapter = get_adapter(self._vendor_key)
        origin = AssetOrigin(
            vendor=self._vendor_key,
            url=url,
            captured_at=self._now_iso() if self._now_iso else "",
        )
        pipeline = self._make_pipeline()
        try:
            try:
                candidates = pipeline.inspect(inputs=[item.path for item in landed])
            except Exception as exc:  # noqa: BLE001
                return SourceOutcome(error=f"could not read the download: {exc}")
            if not candidates:
                return SourceOutcome(
                    error=(
                        f"{adapter.capability.label} delivered a file with no symbol, footprint "
                        "or 3D model in it"
                    )
                )
            candidate = candidates[0]
            candidate.entry_name = record.mpn or candidate.entry_name or candidate.mpn

            offered: list[Requirement] = []
            if candidate.symbol_lib_path is not None:
                offered.append(Requirement.KICAD_SYMBOL)
            if candidate.footprint_variants:
                offered.append(Requirement.KICAD_FOOTPRINT)
            if candidate.model_path is not None:
                offered.append(Requirement.KICAD_MODEL)
            if not offered:
                return SourceOutcome(
                    error=f"{adapter.capability.label} delivered nothing this part can use"
                )
            try:
                self._run_write(
                    lambda: pipeline.attach_assets(record.id, candidate, origin=origin)
                )
            except Exception as exc:  # noqa: BLE001 - the attach is atomic; a failure is a row
                return SourceOutcome(error=str(exc))
            return SourceOutcome(satisfied=tuple(offered))
        finally:
            pipeline.cleanup()
