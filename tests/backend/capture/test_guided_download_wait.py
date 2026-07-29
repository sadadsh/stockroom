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
from pathlib import Path

import pytest

from stockroom.capture import guided
from stockroom.capture.browser import (
    CapturedFile,
    PlaywrightCaptureBrowser,
    UserCaptureResult,
)
from stockroom.capture.complete import CompletionItem, SourceOutcome, complete_library
from stockroom.capture.download_broker import DownloadReceipt
from stockroom.capture.pacing import CircuitBreaker
from stockroom.capture.requirements import Requirement
from stockroom.capture.vendors import DriveReport, VendorCapability


class _Record:
    """The slice of a record `capture_needs` actually reads."""

    id = "tpd6e05u06rvzr-0001"
    mpn = "TPD6E05U06RVZR"
    manufacturer = "Texas Instruments"

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
        self.url = (
            "https://app.ultralibrarian.com/details/fixture/"
            "Texas%20Instruments/TPD6E05U06RVZR?open=exports"
        )

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
        key="ultralibrarian",
        label="Faketron",
        tools=("kicad",),
        formats_exclusive=False,
        aggregator=False,
        needs_login=False,
        instruction="",
        version_pins={"kicad": "KiCADv6"},
        browser_access="machine_allowed",
    )

    class _Adapter:
        def __init__(self):
            self.capability = capability

        def resolve_url(self, mpn: str) -> str:
            return f"https://app.ultralibrarian.com/search?queryText={mpn}"

        def drive(
            self,
            page,
            formats,
            *,
            expected_manufacturer="",
            expected_mpn="",
        ):
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
        machine_access_check=lambda: True,
    )
    # Inject the session rather than launching a browser: this test is about the WAIT, and a real
    # engine launch would make it slow and vendor-dependent for no added coverage.
    src._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())
    return src


def test_guided_source_reports_the_provider_without_changing_its_engine_key(monkeypatch, tmp_path):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)

    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "dl",
        headless=True,
    )

    assert source.key == "guided"
    assert source.report_label == "Faketron"


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
    assert "nothing this part can use" in (outcome.error or ""), (
        "expected to reach the attach stage and report the fixture's empty candidate list, "
        f"got {outcome!r}"
    )


def test_guided_supply_attaches_only_the_exact_task_broker_receipts(monkeypatch, tmp_path):
    class EventPage(_FakePage):
        def on(self, event: str, handler) -> None:
            assert event == "download"
            self.handler = handler

        def close(self) -> None:
            pass

    class Context:
        page = None

        def new_page(self):
            self.page = EventPage()
            return self.page

    class Download:
        suggested_filename = "current.zip"
        url = "https://vendor.example.test/current.zip"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"current-part")

    class Pipeline:
        def __init__(self):
            self.inputs = None

        def inspect(self, inputs):
            self.inputs = list(inputs)
            return []

        def cleanup(self):
            return None

    context = Context()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads")
    browser._context = context
    stale = tmp_path / "stale.zip"
    stale.write_bytes(b"previous-part")
    browser._captured.append(CapturedFile(stale, "stale.zip", "https://previous.invalid"))
    pipeline = Pipeline()
    _install_adapter(
        monkeypatch,
        browser,
        on_drive=lambda _browser: context.page.handler(Download()),
    )
    source = guided.GuidedCaptureSource(
        lambda: pipeline,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        headless=True,
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = source.supply(_Record())

    assert pipeline.inputs is not None
    assert stale not in pipeline.inputs
    assert len(pipeline.inputs) == 1
    assert pipeline.inputs[0].read_bytes() == b"current-part"
    assert "nothing this part can use" in (outcome.error or "")


def test_user_driven_guided_supply_skips_provider_automation_and_validates_captured_files(
    monkeypatch,
    tmp_path,
):
    landed = tmp_path / "captured.payload"
    landed.write_bytes(b"captured-bytes")
    receipt = DownloadReceipt(
        task_id=_Record.id,
        manufacturer_key=_Record.manufacturer,
        mpn_canonical=_Record.mpn,
        path=landed,
        suggested_name=landed.name,
        source_url="https://vendor.example.test/download",
        final_url="https://vendor.example.test/download",
        sha256="0" * 64,
        size_bytes=landed.stat().st_size,
        transport="playwright",
        attempt=1,
    )

    class Pipeline:
        inputs = None

        def inspect(self, inputs):
            self.inputs = list(inputs)
            return []

        def cleanup(self):
            return None

    pipeline = Pipeline()
    captured_call = {}

    class Manager:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    class Browser:
        def __init__(self, **_options):
            pass

        def session(self):
            return Manager()

        def capture_user_downloads(self, url, broker, **options):
            captured_call.update(url=url, broker=broker, options=options)
            return UserCaptureResult(
                status="completed",
                files=(receipt,),
                final_url="https://vendor.example.test/details/MPN-A",
            )

    def provider_drive_was_called(_browser):
        raise AssertionError("user-driven capture must not invoke the provider driver")

    _install_adapter(monkeypatch, object(), on_drive=provider_drive_was_called)
    monkeypatch.setattr(guided, "PlaywrightCaptureBrowser", Browser)
    monkeypatch.setattr(
        guided,
        "sign_in_adapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("user-driven capture must not fill or submit stored credentials")
        ),
    )
    finished = lambda: True
    cancelled = lambda: False
    source = guided.GuidedCaptureSource(
        lambda: pipeline,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        headless=True,
        user_driven=True,
        user_finished=finished,
        user_cancelled=cancelled,
        user_capture_timeout_s=5,
    )

    try:
        outcome = source.supply(_Record())
    finally:
        source.close()

    assert captured_call["url"] == (
        "https://app.ultralibrarian.com/search?queryText=TPD6E05U06RVZR"
    )
    assert captured_call["broker"].task.task_id == _Record.id
    assert captured_call["broker"].task.mpn_canonical == _Record.mpn
    hud = captured_call["options"].pop("hud")
    assert hud.provider_label == "Faketron"
    assert hud.manufacturer == _Record.manufacturer
    assert hud.mpn == _Record.mpn
    assert hud.required_file_labels == ("KiCad symbol and footprint",)
    assert captured_call["options"] == {
        "should_finish": finished,
        "should_cancel": cancelled,
        "timeout_s": 5,
    }
    assert pipeline.inputs == [landed]
    assert "nothing this part can use" in (outcome.error or "")


@pytest.mark.parametrize(
    ("status", "message", "workflow_cancelled"),
    [
        ("try_another", "left for another provider", False),
        ("cancelled", "capture was cancelled", True),
    ],
)
def test_user_hud_action_advances_or_cancels_without_attaching(
    monkeypatch,
    tmp_path,
    status,
    message,
    workflow_cancelled,
):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    cancel_calls: list[bool] = []

    def capture_user_downloads(_url, _broker, **options):
        assert options["hud"].required_file_labels == ("KiCad symbol and footprint",)
        return UserCaptureResult(status=status, files=(), final_url="https://example.invalid/part")

    browser.capture_user_downloads = capture_user_downloads
    source = guided.GuidedCaptureSource(
        lambda: (_ for _ in ()).throw(AssertionError("an action without files must not attach")),
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        user_driven=True,
        cancel_workflow=lambda: cancel_calls.append(True),
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = source.supply(_Record())

    assert message in outcome.skipped
    assert bool(cancel_calls) is workflow_cancelled


def test_guided_supply_refuses_ambiguous_identity_before_opening_a_browser(monkeypatch, tmp_path):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
    )
    record = _Record()
    record.manufacturer = ""

    outcome = source.supply(record)

    assert "exact manufacturer and MPN" in (outcome.error or "")
    assert source._session is None


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


# --------------------------------------------------------------------------------------------
# The ALTIUM attach. Guided capture could download Altium libraries and then silently drop them,
# because `_attach` only ever offered the three KiCad requirements while
# `library_ops.attach_altium_assets` sat written, atomic, and uncalled.
# --------------------------------------------------------------------------------------------


class _BoundAsset:
    """The surface `asset_present` actually reads. A bare dict would pass a shape the real
    `PartRecord` never returns, so the fake would be testing something that cannot happen."""

    def is_present(self) -> bool:
        return True


class _AltiumRecord(_Record):
    """A part that still needs its Altium pair, and can report what it holds afterwards."""

    def __init__(self):
        self.altium: dict = {}

    def capturable(self, tool_key: str) -> set[str]:
        return {"symbol", "footprint"}

    def assets_for(self, tool_key: str) -> dict:
        return self.altium if tool_key == "altium" else {}


def _zip_with(tmp_path, members: dict[str, bytes]):
    import zipfile

    path = tmp_path / "vendor.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return path


def test_altium_libraries_in_a_download_are_attached_not_dropped(monkeypatch, tmp_path):
    """THE GAP. A download carrying .SchLib/.PcbLib must reach `attach_altium_assets`."""
    browser = _FakeBrowser()
    bundle = _zip_with(
        tmp_path,
        {
            "AltiumLibs/PART.SchLib": b"altium-symbol",
            "AltiumLibs/PART.PcbLib": b"altium-footprint",
        },
    )

    record = _AltiumRecord()
    seen: dict = {}

    def fake_attach(part_id, *sources, origin=None, now_iso=""):
        seen["part_id"] = part_id
        seen["suffixes"] = sorted(p.suffix.lower() for p in sources)
        # what the real seam does: bind each side it could read, then hand back the record
        record.altium = {"symbol": _BoundAsset(), "footprint": _BoundAsset()}
        return record

    class _Pipeline:
        def inspect(self, inputs):
            return []  # no KiCad content at all - Altium must still be attached

        def cleanup(self):
            return None

    src = _source(
        monkeypatch,
        tmp_path,
        browser,
        on_drive=lambda b: b.captured.append(_CapturedFile(bundle)),
        pipeline=_Pipeline(),
    )
    src._attach_altium = fake_attach
    outcome = src.supply(record)

    assert seen.get("part_id") == record.id, "attach_altium_assets was never called"
    assert seen["suffixes"] == [".pcblib", ".schlib"], seen
    assert set(outcome.satisfied) == {Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}, (
        f"an Altium-only download must report Altium requirements, got {outcome!r}"
    )


def test_current_ul_native_archive_shape_exposes_both_altium_libraries(tmp_path):
    """UL's current .LibPkg bundle also carries native libraries Stockroom can attach directly."""
    fixtures = Path(__file__).parents[1] / "altium" / "fixtures"
    bundle = _zip_with(
        tmp_path,
        {
            "Altium Designer (Native)/TPD6E05U06RVZR.LibPkg": b"native package descriptor",
            "Altium Designer (Native)/TPD6E05U06RVZR.SchLib": (
                fixtures / "sample.SchLib"
            ).read_bytes(),
            "Altium Designer (Native)/TPD6E05U06RVZR.PcbLib": (
                fixtures / "sample.PcbLib"
            ).read_bytes(),
            "Altium Designer (Native)/TPD6E05U06RVZR.step": b"ISO-10303-21;",
        },
    )

    found = guided._altium_libraries([_CapturedFile(bundle)])

    assert sorted(path.suffix.casefold() for path in found) == [".pcblib", ".schlib"]
    assert all(path.read_bytes().startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") for path in found)


def test_only_the_side_the_record_actually_holds_is_reported(monkeypatch, tmp_path):
    """Report from the RECORD, never from what was requested.

    `attach_altium_assets` binds each side independently - a vendor may ship only the symbol. If
    this reported what it SENT rather than what landed, a half-delivery would read as complete,
    which is the "success that attached nothing" failure in miniature.
    """
    browser = _FakeBrowser()
    bundle = _zip_with(tmp_path, {"PART.SchLib": b"altium-symbol"})
    record = _AltiumRecord()

    def fake_attach(part_id, *sources, origin=None, now_iso=""):
        record.altium = {"symbol": _BoundAsset()}  # footprint deliberately NOT bound
        return record

    class _Pipeline:
        def inspect(self, inputs):
            return []

        def cleanup(self):
            return None

    src = _source(
        monkeypatch,
        tmp_path,
        browser,
        on_drive=lambda b: b.captured.append(_CapturedFile(bundle)),
        pipeline=_Pipeline(),
    )
    src._attach_altium = fake_attach
    outcome = src.supply(record)

    assert set(outcome.satisfied) == {Requirement.ALTIUM_SYMBOL}, outcome
    assert Requirement.ALTIUM_FOOTPRINT not in outcome.satisfied


def test_a_kicad_only_vendor_is_completely_unaffected(monkeypatch, tmp_path):
    """The regression guard. No Altium files means the seam is never invoked at all."""
    browser = _FakeBrowser()
    bundle = _zip_with(tmp_path, {"PART.kicad_sym": b"(kicad_symbol_lib)"})
    called = []

    class _Pipeline:
        def inspect(self, inputs):
            return []

        def cleanup(self):
            return None

    src = _source(
        monkeypatch,
        tmp_path,
        browser,
        on_drive=lambda b: b.captured.append(_CapturedFile(bundle)),
        pipeline=_Pipeline(),
    )
    src._attach_altium = lambda *a, **k: called.append(a)
    src.supply(_Record())

    assert not called, "attach_altium_assets was called for a download with no Altium libraries"


def test_a_failing_altium_attach_is_a_row_not_a_crash(monkeypatch, tmp_path):
    """Atomic seam: a failure leaves the part untouched and must surface as an error string."""
    browser = _FakeBrowser()
    bundle = _zip_with(tmp_path, {"PART.SchLib": b"altium-symbol"})

    class _Pipeline:
        def inspect(self, inputs):
            return []

        def cleanup(self):
            return None

    src = _source(
        monkeypatch,
        tmp_path,
        browser,
        on_drive=lambda b: b.captured.append(_CapturedFile(bundle)),
        pipeline=_Pipeline(),
    )

    def boom(part_id, *sources, origin=None, now_iso=""):
        raise RuntimeError("normalize refused the file")

    src._attach_altium = boom
    outcome = src.supply(_AltiumRecord())

    assert outcome.error and "Altium" in outcome.error, outcome
    assert "normalize refused the file" in outcome.error


# --------------------------------------------------------------------------------------------
# SIGN-IN. Measured against the LIVE site 2026-07-27: signed out, everything works - search
# resolves, the details page opens, the export panel renders 39 controls, KiCad and 3D both tick -
# and the ONLY missing piece is the Download button, which the vendor renders solely for a signed-in
# user. So one sign-in per run is the difference between a 90-part sitting completing by itself and
# failing on every single part.
# --------------------------------------------------------------------------------------------


class _LoginAdapter:
    """A vendor that needs a login, recording how it was asked."""

    def __init__(self, already_signed_in=False, refuse=""):
        self.capability = VendorCapability(
            key="ultralibrarian",
            label="Faketron",
            tools=("kicad",),
            formats_exclusive=False,
            aggregator=False,
            needs_login=True,
            instruction="",
            version_pins={"kicad": "KiCADv6"},
            browser_access="machine_allowed",
        )
        self.calls: list[tuple] = []
        self._already = already_signed_in
        self._refuse = refuse

    def signed_in(self, page):
        return self._already

    def sign_in(self, page, username, password):
        self.calls.append((username, password))
        return self._refuse

    def resolve_url(self, mpn):
        return f"https://app.ultralibrarian.com/search?queryText={mpn}"

    def drive(
        self,
        page,
        formats,
        *,
        expected_manufacturer="",
        expected_mpn="",
    ):
        return DriveReport(
            missed=list(formats),
            submitted=False,
            message="the Download button is not on this page.",
        )


def _source_with_adapter(monkeypatch, tmp_path, browser, adapter, credentials):
    monkeypatch.setattr(guided, "get_adapter", lambda key: adapter)
    src = guided.GuidedCaptureSource(
        (lambda: None),
        vendor="faketron",
        download_root=tmp_path / "dl",
        headless=True,
        credentials=credentials,
        machine_access_check=lambda: True,
    )
    src._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())
    return src


def test_the_run_signs_in_once_using_the_saved_credentials(monkeypatch, tmp_path):
    adapter = _LoginAdapter()
    src = _source_with_adapter(
        monkeypatch, tmp_path, _FakeBrowser(), adapter, lambda key: ("user@example.com", "secret")
    )
    src._sign_in_once(_FakePage())
    assert adapter.calls == [("user@example.com", "secret")]
    assert src._sign_in_error == ""


def test_an_already_signed_in_profile_is_not_signed_in_again(monkeypatch, tmp_path):
    """The persistent profile carrying the session is the whole point - re-logging in every run
    would throw away that benefit and hammer the vendor's login for nothing."""
    adapter = _LoginAdapter(already_signed_in=True)
    src = _source_with_adapter(
        monkeypatch, tmp_path, _FakeBrowser(), adapter, lambda key: ("user@example.com", "secret")
    )
    src._sign_in_once(_FakePage())
    assert adapter.calls == []


def test_no_saved_credentials_is_a_silent_no_op(monkeypatch, tmp_path):
    adapter = _LoginAdapter()
    src = _source_with_adapter(monkeypatch, tmp_path, _FakeBrowser(), adapter, lambda key: None)
    src._sign_in_once(_FakePage())
    assert adapter.calls == []
    assert src._sign_in_error == ""


def test_a_refused_sign_in_is_explained_in_the_part_row(monkeypatch, tmp_path):
    """A refused login must SAY SO on the part, not leave a bare vendor message.

    Everything up to the Download button works signed out, so without this the owner sees
    "the Download button is not on this page" on all 90 parts and no hint that the cause is a
    rejected password.
    """
    adapter = _LoginAdapter(refuse="Ultra Librarian did not accept the saved credentials.")
    src = _source_with_adapter(
        monkeypatch, tmp_path, _FakeBrowser(), adapter, lambda key: ("user@example.com", "wrong")
    )
    src._sign_in_once(_FakePage())
    assert src._sign_in_error

    outcome = src.supply(_Record())
    assert "did not accept the saved credentials" in (outcome.skipped or ""), outcome


def test_saved_credentials_refuses_a_half_filled_pair(monkeypatch):
    """A username with no password is not a credential; returning it would fail an empty login
    and report a vendor problem for what is really an unset setting."""
    from stockroom.capture import runner

    class _Cfg:
        ul_username = "user@example.com"
        ul_password = ""

    monkeypatch.setattr(
        "stockroom.store.machine_config.MachineConfig.load", classmethod(lambda cls: _Cfg())
    )
    assert runner._saved_credentials("ultralibrarian") is None
    assert runner._saved_credentials("no-such-vendor") is None


# --------------------------------------------------------------------------------------------
# `signed_in` MUST DISCRIMINATE. The first version checked only that `#loginLink` was absent, and
# returned True on the identity server's own login page - so a WRONG PASSWORD reported success in
# the same 3.5s as the right one. It was caught solely by feeding it a deliberately bad password.
# The three states below are the real ones, measured live 2026-07-27.
# --------------------------------------------------------------------------------------------


class _StatePage:
    """A page pinned to one of the three measured post-login states."""

    def __init__(self, url, login_link=0, username=0):
        self.url = url
        self._counts = {"#loginLink": login_link, "#Username": username}

    def locator(self, selector):
        count = self._counts.get(selector, 0)
        return type("L", (), {"count": staticmethod(lambda c=count: c)})()


def _ul():
    from stockroom.capture.vendors import UltraLibrarianAdapter

    return UltraLibrarianAdapter()


def test_signed_in_is_true_only_for_the_real_signed_in_state():
    """correct password -> www.ultralibrarian.com, no #loginLink, no #Username."""
    assert _ul().signed_in(_StatePage("https://www.ultralibrarian.com/")) is True


def test_signed_in_is_false_on_the_identity_servers_login_page():
    """THE BUG. Wrong password leaves you on sso.../Account/Login, which has NO #loginLink either -
    so an absence-only check called this signed in and reported a bad password as success."""
    page = _StatePage(
        "https://sso.ultralibrarian.com/Account/Login?ReturnUrl=%2Fconnect%2F",
        login_link=0,
        username=1,
    )
    assert _ul().signed_in(page) is False


def test_signed_in_is_false_when_the_header_still_offers_a_login():
    """signed out on the app host -> #loginLink present."""
    assert (
        _ul().signed_in(
            _StatePage("https://app.ultralibrarian.com/search?queryText=X", login_link=1)
        )
        is False
    )


def test_signed_in_is_false_before_any_ultra_page_has_loaded():
    assert _ul().signed_in(_StatePage("about:blank")) is False


def test_signed_in_needs_all_three_signals_not_any_one():
    """Mutation guard. Each single signal alone is satisfied by a state that is NOT signed in, which
    is exactly why the original one-signal version could not tell a hit from a miss."""
    ul = _ul()
    # no #loginLink alone is NOT enough - the login page also has none
    assert ul.signed_in(_StatePage("https://sso.ultralibrarian.com/Account/Login")) is False
    # off the identity host alone is NOT enough - a login form can still be on screen
    assert ul.signed_in(_StatePage("https://app.ultralibrarian.com/x", username=1)) is False


# --------------------------------------------------------------------------------------------
# BOTH VENDORS. Owner, 2026-07-27: *"i wanted both"* / *"check both to see which one has it, and if
# one download fails use the other."*
# --------------------------------------------------------------------------------------------


def test_the_default_vendor_chain_prefers_manufacturer_verified_ultra_librarian():
    """Trust wins the default; SnapMagic remains the availability fallback."""
    from stockroom.capture import runner

    assert runner._vendor_chain(None) == ["ultralibrarian", "snapmagic"]


def test_a_preferred_vendor_keeps_the_other_implemented_provider_as_fallback():
    """A chosen provider changes priority without disabling automatic fallback."""
    from stockroom.capture import runner

    assert runner._vendor_chain("snapmagic") == ["snapmagic", "ultralibrarian"]
    assert runner._vendor_chain(["snapmagic", "ultralibrarian"]) == ["snapmagic", "ultralibrarian"]


def test_an_unknown_or_empty_vendor_choice_fails_honestly():
    """A provider label must never silently execute another provider's browser adapter."""
    from stockroom.capture import runner

    with pytest.raises(ValueError, match="no network capture adapter"):
        runner._vendor_chain("no-such-vendor")
    with pytest.raises(ValueError, match="at least one implemented provider"):
        runner._vendor_chain([])


def test_snapmagic_serves_native_altium_which_needs_no_conversion():
    """SnapMagic remains a second native Altium route, not the only one."""
    from stockroom.capture.vendors import get_adapter

    sm = get_adapter("snapmagic")
    assert sm is not None
    assert set(sm.capability.tools) == {"kicad", "altium"}
    assert sm.capability.version_pins["altium"] == "altium_native"
    # KiCad V6+, never the V3/V4 rows: KiCad 5 emits `(module ...)` that Footprint.load REFUSES.
    assert sm.capability.version_pins["kicad"] == "kicad_modv6"
    # one button per format, so the engine MUST sequence it
    assert sm.capability.formats_exclusive is True


def test_ultra_librarian_native_altium_is_sourceable_without_a_dom_selector(tmp_path):
    """The user selects the current native export; Stockroom owns validation and attachment."""
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path / "downloads",
        user_driven=True,
    )

    assert source.provides() == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    }
    assert guided._provider_formats(
        guided.get_adapter("ultralibrarian"),
        [Requirement.ALTIUM_SYMBOL],
    ) == ["kicad", "model", "altium"]
    assert guided._provider_hud_labels(
        guided.get_adapter("ultralibrarian"),
        ["kicad", "model", "altium"],
    ) == ("KiCad 6 or later", "STEP", "Altium Designer (Native)")


def test_exclusive_formats_are_downloaded_one_at_a_time(monkeypatch, tmp_path):
    """THE SEQUENCING. `formats_exclusive` was DATA nothing read: a single drive with both formats
    would fetch only the first and silently lose the other."""
    browser = _FakeBrowser()
    drives: list[list[str]] = []

    class _Exclusive:
        capability = VendorCapability(
            key="faketron",
            label="Faketron",
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=False,
            needs_login=False,
            instruction="",
            version_pins={"kicad": "k", "altium": "a"},
        )

        def resolve_url(self, mpn):
            return "https://example.invalid/part"

        def drive(self, page, formats):
            drives.append(list(formats))
            browser.captured.append(_CapturedFile(tmp_path / f"{formats[0]}.zip"))
            return DriveReport(selected=list(formats), submitted=True, message="ok")

    monkeypatch.setattr(guided, "get_adapter", lambda key: _Exclusive())
    page = _FakePage()
    report, failure = guided.drive_formats(
        browser, page, _Exclusive(), ["kicad", "altium"], "https://example.invalid/part"
    )

    assert failure is None
    assert drives == [["kicad"], ["altium"]], f"formats were not sequenced: {drives}"
    assert report.selected == ["kicad", "altium"]
    assert report.submitted is True
    assert len(browser.captured) == 2, "each exclusive format must produce its OWN download"


def test_a_submitted_format_that_never_arrives_is_an_error_not_a_skip(monkeypatch, tmp_path):
    """MEASURED LIVE, 2026-07-27: SnapMagic clicked its Altium button and delivered nothing.

    The drive comes back `submitted=False` - the flag is only set AFTER the file lands - together
    with a hard failure. So a `supply` that tests `submitted` before `failure` reports a VANISHED
    download as "the vendor simply had nothing", which is the exact class of lie this file exists
    to stop: an intent-shaped report standing in for an observation.
    """
    browser = _FakeBrowser()

    class _NeverDelivers:
        capability = VendorCapability(
            key="ultralibrarian",
            label="Vanishtron",
            tools=("altium",),
            formats_exclusive=True,
            aggregator=False,
            needs_login=False,
            instruction="",
            version_pins={"altium": "a"},
            browser_access="machine_allowed",
        )

        def resolve_url(self, mpn):
            return f"https://app.ultralibrarian.com/search?queryText={mpn}"

        def drive(
            self,
            page,
            formats,
            *,
            expected_manufacturer="",
            expected_mpn="",
        ):
            # clicked, and nothing ever lands
            return DriveReport(selected=list(formats), submitted=True, message="ok")

    adapter = _NeverDelivers()
    monkeypatch.setattr(guided, "get_adapter", lambda key: adapter)
    monkeypatch.setattr(guided, "capture_needs", lambda record: [Requirement.ALTIUM_SYMBOL])
    monkeypatch.setattr(guided, "formats_for", lambda needs: ["altium"])
    monkeypatch.setattr(guided, "_DOWNLOAD_TIMEOUT_MS", 300)

    src = guided.GuidedCaptureSource(
        (lambda: None),
        vendor="vanishtron",
        download_root=tmp_path / "dl",
        headless=True,
        machine_access_check=lambda: True,
    )
    src._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = src.supply(_Record())

    assert outcome.error, f"a vanished download must be an ERROR, got {outcome!r}"
    assert "did not deliver" in outcome.error
    assert not outcome.skipped, "reporting it as a skip hides a lost file"


def test_the_kicad_chooser_waits_for_its_member_instead_of_sleeping():
    """A SLEEP USED AS A DETECTOR produced a FALSE NEGATIVE that looked like a vendor limitation.

    SnapMagic's KiCad row is a two-step chooser: clicking `kicad_options` renders the version
    members. The adapter used to `wait_for_timeout(300)` and then test `count() == 0`, so a chooser
    that took 301ms was reported as `SnapMagic does not offer kicad for this part` - a sentence
    about the VENDOR, produced by a clock.

    The fake below models exactly that: the member does not exist until something WAITS for it. Any
    fixed sleep fails here no matter how long, because the appearance is caused by the wait, not by
    elapsed time.
    """
    from stockroom.capture.vendors import SnapMagicAdapter

    class _Locator:
        def __init__(self, page, selector):
            self._page, self._sel = page, selector

        @property
        def first(self):
            return self

        def count(self):
            if self._sel == '[data-format="kicad_modv6"]:visible':
                return 1 if self._page.member_ready else 0
            return 1

        def wait_for(self, **kwargs):
            if self._sel == '[data-format="kicad_modv6"]:visible':
                self._page.member_ready = True

        def click(self, **kwargs):
            self._page.clicked.append(self._sel)

        def get_attribute(self, name):
            return ""

        def is_visible(self):
            return True

    class _ChooserPage:
        url = "https://www.snapeda.com/parts/X/view-part/"

        def __init__(self):
            self.member_ready = False
            self.clicked: list[str] = []

        def locator(self, selector):
            return _Locator(self, selector)

        def wait_for_timeout(self, ms):
            raise AssertionError(
                "the KiCad chooser slept and then looked. A member that renders one millisecond "
                "late is then reported as 'SnapMagic does not offer kicad for this part' - a false "
                "negative shaped exactly like a real vendor limitation. Wait for the member."
            )

        def inner_text(self, sel):
            return ""

    page = _ChooserPage()
    report = SnapMagicAdapter().drive(page, ["kicad"])

    assert report.submitted is True, f"the chooser member was never found: {report.message}"
    assert report.selected == ["kicad"]
    assert report.missed == []
    assert '[data-format="kicad_modv6"]:visible' in page.clicked, (
        "the pinned version was never clicked"
    )


def test_altium_only_gap_drives_one_full_ultralibrarian_evidence_bundle(monkeypatch, tmp_path):
    """A partial repair needs same-provider companion bytes for cross-EDA proof."""
    browser = _FakeBrowser()
    requested: list[str] = []

    def fake_drive(_browser, _page, _adapter, formats, _url):
        requested.extend(formats)
        return (
            DriveReport(missed=list(formats), blocked=True, message="account gate"),
            "account gate",
        )

    monkeypatch.setattr(guided, "drive_formats", fake_drive)
    monkeypatch.setattr(
        guided,
        "capture_needs",
        lambda _record: [Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT],
    )
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path / "downloads",
        headless=True,
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = source.supply(_Record())

    assert requested == ["kicad", "model", "altium"]
    assert outcome.blocked is True


def test_provider_wide_capture_gate_trips_batch_breaker_instead_of_burning_every_part(
    monkeypatch, tmp_path
):
    """A challenge/auth/download gate affects the session, not one MPN."""

    class _BlockedAdapter:
        capability = VendorCapability(
            key="ultralibrarian",
            label="Blocked Provider",
            tools=("kicad",),
            formats_exclusive=False,
            aggregator=False,
            needs_login=True,
            instruction="",
            version_pins={"kicad": "v6"},
            browser_access="machine_allowed",
        )

        def resolve_url(self, _mpn):
            return (
                "https://app.ultralibrarian.com/search"
                "?queryText=TPD6E05U06RVZR"
            )

    adapter = _BlockedAdapter()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: adapter)
    monkeypatch.setattr(
        guided,
        "drive_formats",
        lambda *_args, **_kwargs: (
            DriveReport(
                missed=["kicad"],
                blocked=True,
                message="confirm you are human",
            ),
            "confirm you are human",
        ),
    )
    browser = _FakeBrowser()
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="blocked-provider",
        download_root=tmp_path / "downloads",
        headless=True,
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    records = {f"part-{index}": _Record() for index in range(10)}
    for part_id, record in records.items():
        record.id = part_id
    report = complete_library(
        records,
        load_record=records.__getitem__,
        sources=[source],
        breaker=CircuitBreaker(threshold=2),
    )

    assert report.stopped is True
    assert len(report.items) == 2
    assert [item.status for item in report.items] == ["deferred", "deferred"]
    assert "confirm you are human" in report.stop_reason


def test_partial_fallback_does_not_hide_a_repeated_provider_wide_gate(monkeypatch):
    """KiCad progress must not reset the breaker while the dual-EDA provider stays blocked."""

    def blocked_but_improved(part_id, **_kwargs):
        return CompletionItem(
            part_id=part_id,
            status="improved",
            satisfied=["kicad_symbol", "kicad_footprint", "kicad_model"],
            remaining=["altium_symbol", "altium_footprint"],
            error="snapmagic: multiple-file download permission is blocked",
            provider_blocked=True,
        )

    monkeypatch.setattr("stockroom.capture.complete.complete_part", blocked_but_improved)
    report = complete_library(
        (f"part-{index}" for index in range(1000)),
        load_record=lambda _part_id: None,
        sources=[],
        breaker=CircuitBreaker(threshold=3),
    )

    assert report.stopped is True
    assert len(report.items) == 3
    assert all(item.status == "improved" for item in report.items)
    assert "multiple-file download permission" in report.stop_reason


def test_exclusive_provider_stops_remaining_formats_after_global_account_gate():
    attempts: list[list[str]] = []

    class _BlockedExclusive:
        capability = VendorCapability(
            key="blocked-exclusive",
            label="Blocked Exclusive",
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=False,
            needs_login=True,
            instruction="",
            version_pins={"kicad": "k", "model": "m", "altium": "a"},
        )

        def drive(self, _page, formats):
            attempts.append(list(formats))
            return DriveReport(
                missed=list(formats),
                blocked=True,
                message="account download gate",
            )

    report, failure = guided.drive_formats(
        _FakeBrowser(),
        _FakePage(),
        _BlockedExclusive(),
        ["kicad", "model", "altium"],
        "https://example.invalid/part",
    )

    assert failure is None
    assert report.blocked is True
    assert attempts == [["kicad"]]
