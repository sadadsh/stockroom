"""Guided capture must decide success by looking at the SAVED FILE, never at the download event.

THE BUG THIS LOCKS, measured 2026-07-27. `GuidedCaptureSource.supply` waited with
`page.wait_for_event("download")`. But `PlaywrightCaptureBrowser` already registers an
`on("download")` handler when the session opens, and Playwright delivers a given event to whichever
listener is active - so a download that completed quickly was consumed by the handler, the wait
never saw it, and the source reported a hard failure for a file that was already on disk.

Two things made it expensive rather than merely wrong:
  * the failure is TIMING-dependent, so it looked like a hang (a 60-120s stall per part) rather
    than a bug, and it is what hung the suite;
  * it produced a confident NEGATIVE conclusion about the wrong component - "Camoufox cannot
    download" - when Camoufox had downloaded the file correctly.

`guided.py` was entirely untested before this file, which is why a defect this central survived.
"""

from __future__ import annotations

import time

import pytest

from stockroom.capture import guided
from stockroom.capture.complete import SourceOutcome
from stockroom.capture.requirements import Requirement
from stockroom.capture.vendors import DriveReport, VendorCapability


class _Record:
    """The slice of a record `capture_needs` actually reads."""

    id = "SR-TEST-0001"
    mpn = "TPD6E05U06RVZR"

    def capturable(self, tool_key: str) -> set[str]:
        return {"symbol", "footprint"} if tool_key == "kicad" else set()

    def assets_for(self, tool_key: str) -> dict:
        return {}  # nothing present, so everything is still needed


class _CapturedFile:
    def __init__(self, path):
        self.path = path


class _FakeBrowser:
    """Stands in for the real browser. `captured` is the OBSERVATION the source must key on."""

    def __init__(self):
        self.captured: list[_CapturedFile] = []


class _FakePage:
    """A page whose `wait_for_event` is a trap.

    This is the mutation lock. If anyone reintroduces `page.wait_for_event("download")`, this test
    fails immediately and by name, instead of the regression coming back as an intermittent stall
    that only shows up against a live vendor.
    """

    def __init__(self):
        self.url = "https://app.ultralibrarian.com/details/fake"

    def goto(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        """The real Page pumps Playwright's event greenlet here; the fake just sleeps.

        `_wait_for_capture` sleeps THROUGH the page on purpose (a bare `time.sleep` never lets the
        sync api dispatch `on("download")`), so the fake has to offer the same call or the test
        would be exercising a signature the production code does not use.
        """
        time.sleep(ms / 1000.0)

    def wait_for_event(self, *args, **kwargs):  # pragma: no cover - it must never be reached
        raise AssertionError(
            "supply() waited on the download EVENT. The browser session's own on('download') "
            "handler races that wait and consumes the event, so a fast download reports failure "
            "for a file that landed. Poll the saved list instead."
        )


def _install_adapter(monkeypatch, browser, *, on_drive):
    """Register a fake vendor whose drive() calls `on_drive(browser)`."""
    capability = VendorCapability(
        key="faketron",
        label="Faketron",
        tools=("kicad",),
        formats_exclusive=False,
        aggregator=False,
        needs_login=False,
        instruction="",
        version_pins={"kicad": "KiCADv6"},
    )

    class _Adapter:
        def __init__(self):
            self.capability = capability

        def resolve_url(self, mpn: str) -> str:
            return "https://example.invalid/part"

        def drive(self, page, formats):
            on_drive(browser)
            return DriveReport(selected=list(formats), submitted=True, message="Requested KiCad.")

    monkeypatch.setattr(guided, "get_adapter", lambda key: _Adapter())
    return capability


def _source(monkeypatch, tmp_path, browser, *, on_drive, pipeline=None):
    _install_adapter(monkeypatch, browser, on_drive=on_drive)
    src = guided.GuidedCaptureSource(
        (lambda: pipeline),
        vendor="faketron",
        download_root=tmp_path / "dl",
        headless=True,
    )
    # Inject the session rather than launching a browser: this test is about the WAIT, and a real
    # engine launch would make it slow and vendor-dependent for no added coverage.
    src._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())
    return src


def test_a_download_consumed_by_the_session_handler_still_counts_as_delivered(
    monkeypatch, tmp_path
):
    """THE REGRESSION. The file lands via the handler; no event is ever offered to a waiter."""
    browser = _FakeBrowser()
    landed = tmp_path / "part.zip"
    landed.write_bytes(b"PK\x03\x04not-a-real-zip")

    def on_drive(b):
        # exactly what the real on('download') handler does: save the file, record it, and the
        # event is gone - nothing is left for a `wait_for_event` to observe.
        b.captured.append(_CapturedFile(landed))

    class _Pipeline:
        def inspect(self, inputs):
            return []  # no candidates: stops before attach, which this test does not exercise

        def cleanup(self):
            return None  # the real source cleans up in a finally

    src = _source(monkeypatch, tmp_path, browser, on_drive=on_drive, pipeline=_Pipeline())
    outcome = src.supply(_Record())

    assert isinstance(outcome, SourceOutcome)
    # It must have got PAST the wait. The old code returned the wait's timeout error here.
    assert "did not deliver a file" not in (outcome.error or ""), (
        f"the wait reported a failure for a file that was on disk: {outcome.error!r}"
    )
    assert "no symbol, footprint" in (outcome.error or ""), (
        "expected to reach the attach stage and report the fixture's empty candidate list, "
        f"got {outcome!r}"
    )


def test_a_vendor_that_never_delivers_is_still_reported_as_a_failure(monkeypatch, tmp_path):
    """The NEGATIVE CONTROL, without which the test above proves nothing.

    If `_wait_for_capture` simply returned True, the regression test would pass while the code was
    incapable of ever reporting a real miss. Here nothing is ever saved, and the source must say
    so - and must say it from the timeout backstop, not hang.
    """
    browser = _FakeBrowser()
    monkeypatch.setattr(guided, "_DOWNLOAD_TIMEOUT_MS", 300)  # 0.3s: this path is a backstop

    src = _source(monkeypatch, tmp_path, browser, on_drive=lambda b: None)
    started = time.monotonic()
    outcome = src.supply(_Record())
    elapsed = time.monotonic() - started

    assert outcome.error and "did not deliver a file" in outcome.error, outcome
    assert elapsed < 10, f"the backstop did not bound the wait ({elapsed:.1f}s)"


def test_the_wait_returns_the_instant_the_file_appears(tmp_path):
    """It must not sit out its timeout once the observation is true - that was the original sin."""
    browser = _FakeBrowser()
    browser.captured.append(_CapturedFile(tmp_path / "already-here.zip"))

    started = time.monotonic()
    got = guided._wait_for_capture(browser, _FakePage(), before=0, timeout_s=30.0)
    elapsed = time.monotonic() - started

    assert got is True
    assert elapsed < 1.0, f"waited {elapsed:.1f}s for a file that was already there"


def test_the_wait_counts_only_files_that_arrived_after_this_part_started(tmp_path):
    """`before` is the guard against a PREVIOUS part's download satisfying this one.

    A whole-library run reuses one browser, so `captured` already holds earlier parts' files. A
    wait keyed on "is the list non-empty" would return instantly for every part after the first
    and attach the wrong part's files - the misattribution bug in a new place.
    """
    browser = _FakeBrowser()
    browser.captured.append(_CapturedFile(tmp_path / "previous-part.zip"))

    got = guided._wait_for_capture(browser, _FakePage(), before=1, timeout_s=0.4)

    assert got is False, "an earlier part's download satisfied this part's wait"


def test_the_wait_sleeps_THROUGH_the_page_so_playwright_can_dispatch(tmp_path):
    """The second half of the fix, and the one that is invisible against a fixture.

    playwright-python's SYNC api dispatches events on a greenlet that only runs while the main
    greenlet is inside a Playwright call. A poll built on bare `time.sleep()` never yields to it, so
    `on("download")` is never invoked and `captured` can never grow - the wait then burns its whole
    120s backstop on a download that finished immediately.

    MEASURED 2026-07-27, one line apart: with `time.sleep` the two API-driven capture tests failed at
    ~120s each with nothing attached; sleeping through `page.wait_for_timeout` made the same tests
    pass in 6.46s total. The localhost end-to-end tests passed BOTH ways, because they are faster
    than the bug - their download is already dispatched during `drive()`, so the loop never has to
    pump. That is exactly why this assertion is mechanical rather than left to those tests.
    """
    calls: list[float] = []

    class _CountingPage(_FakePage):
        def wait_for_timeout(self, ms):
            calls.append(ms)
            # grow the list on the SECOND poll, so the loop must really iterate to observe it
            if len(calls) >= 2:
                browser.captured.append(_CapturedFile(tmp_path / "landed.zip"))
            time.sleep(0.01)

    browser = _FakeBrowser()
    assert guided._wait_for_capture(browser, _CountingPage(), before=0, timeout_s=10.0) is True
    assert calls, (
        "the wait never called page.wait_for_timeout, so it is sleeping outside Playwright and "
        "cannot see a download event at all"
    )


@pytest.mark.parametrize("grows_after", [0.0, 0.3])
def test_the_wait_sees_a_file_that_lands_while_it_is_polling(tmp_path, grows_after):
    """Covers the real timing: the file appears partway through the wait, not before it."""
    import threading

    browser = _FakeBrowser()

    def land():
        time.sleep(grows_after)
        browser.captured.append(_CapturedFile(tmp_path / "late.zip"))

    threading.Thread(target=land, daemon=True).start()
    assert guided._wait_for_capture(browser, _FakePage(), before=0, timeout_s=10.0) is True
