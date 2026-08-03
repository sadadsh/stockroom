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
from contextlib import contextmanager
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


class _CatalogRecord(_Record):
    catalog = {
        "digikey": {
            "product_url": "https://www.digikey.com/en/products/detail/acme/exact/1",
            "media": [
                {
                    "title": "TPD6E05U06RVZR by Ultra Librarian",
                    "url": "https://app.ultralibrarian.com/details/exact/tpd6e05u06rvzr",
                }
            ],
        }
    }


class _CapturedFile:
    def __init__(
        self,
        path,
        *,
        task_id: str = _Record.id,
        manufacturer_key: str = _Record.manufacturer,
        mpn_canonical: str = _Record.mpn,
        surface_key: str = "faketron",
        evidence_provider_key: str = "faketron",
    ):
        self.path = path
        self.task_id = task_id
        self.manufacturer_key = manufacturer_key
        self.mpn_canonical = mpn_canonical
        self.surface_key = surface_key
        self.evidence_provider_key = evidence_provider_key


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


def test_exact_digikey_media_route_wins_over_a_synthesized_provider_search(monkeypatch, tmp_path):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    adapter = guided.get_adapter("faketron")

    assert guided._exact_catalog_url(adapter, _CatalogRecord()) == (
        "https://app.ultralibrarian.com/details/exact/tpd6e05u06rvzr"
    )


def test_exact_catalog_route_accepts_the_reported_maxim_provider_slug_loss(
    monkeypatch,
):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    adapter = guided.get_adapter("faketron")
    record = type(
        "_MaximRecord",
        (),
        {
            "mpn": "MAX17608ATC+",
            "manufacturer": "Analog Devices / Maxim Integrated",
        },
    )()
    url = (
        "https://app.ultralibrarian.com/details/fixture/"
        "Analog-Devices-Inc/MAX17608ATC-?ref=digikey"
    )

    assert guided._resolved_provider_url_issue(adapter, url, record)
    assert (
        guided._resolved_provider_url_issue(
            adapter,
            url,
            record,
            exact_catalog_route=True,
        )
        == ""
    )


def test_strict_catalog_capture_stops_instead_of_falling_back_to_search(monkeypatch, tmp_path):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "dl",
        headless=True,
        strict_catalog_urls=True,
    )

    outcome = source.supply(_Record())

    assert "DigiKey Media did not return an exact" in outcome.skipped
    assert source._session is None


def test_person_driven_route_uses_the_embedded_provider_surface(monkeypatch, tmp_path):
    browser_arguments: list[dict[str, object]] = []
    surface_events: list[str] = []

    class _Choice:
        name = guided.TRANSPORT_DEFAULT_BROWSER
        why = "test person-driven route"

    class _EmbeddedBrowser:
        def __init__(self, **kwargs):
            browser_arguments.append(kwargs)

        @contextmanager
        def session(self):
            surface_events.append("listeners-attached")
            yield _FakePage()

    class _Lease:
        endpoint = "http://127.0.0.1:48123"

        @staticmethod
        def show():
            surface_events.append("shown")

    @contextmanager
    def provider_surface():
        surface_events.append("prepared-hidden")
        try:
            yield _Lease()
        finally:
            surface_events.append("hidden")

    monkeypatch.setattr(guided, "select_transport", lambda *_args, **_kwargs: _Choice())
    monkeypatch.setattr(guided, "trace_transport", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(guided, "PlaywrightCaptureBrowser", _EmbeddedBrowser)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "downloads",
        user_driven=True,
        provider_surface=provider_surface,
    )

    _install_adapter(
        monkeypatch,
        _FakeBrowser(),
        on_drive=lambda _: None,
    )
    session = source._ensure_session()

    assert session.page is not None
    assert browser_arguments[0]["cdp_endpoint"] == "http://127.0.0.1:48123"
    assert surface_events == ["prepared-hidden", "listeners-attached", "shown"]
    source.close()
    assert surface_events == [
        "prepared-hidden",
        "listeners-attached",
        "shown",
        "hidden",
    ]


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
    assert "no exact KiCad symbol, footprint, and STEP" in (outcome.error or ""), (
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
    assert "no exact KiCad symbol, footprint, and STEP" in (outcome.error or "")


def test_each_fresh_route_tab_is_initialized_even_after_run_scoped_sign_in(tmp_path):
    class Page:
        url = "about:blank"

        def __init__(self):
            self.gotos = []

        def goto(self, url, **options):
            self.gotos.append((url, options))
            self.url = url

    page = Page()

    class Browser:
        captured = []
        download_errors = []

        @contextmanager
        def task_page(self, _broker):
            yield page

    capability = VendorCapability(
        key="digikey",
        label="DigiKey · Ultra Librarian",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        browser_access="machine_allowed",
    )
    adapter = type(
        "_Route",
        (),
        {
            "capability": capability,
            "evidence_provider_key": "digikey-ultralibrarian",
        },
    )()
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        operator_authorized=True,
    )
    source._sign_in_attempted = True
    source._prepare_sign_in = lambda *_args: None

    def drive(_session, task_page, *_args):
        assert task_page.url.endswith("keywords=TPD6E05U06RVZR")
        return DriveReport(message="no fixture download"), None

    source._drive_automated = drive
    session = guided._Session(
        browser=Browser(),
        ctx_manager=None,
        page=_FakePage(),
    )
    url = "https://www.digikey.com/en/products/result?keywords=TPD6E05U06RVZR"

    outcome = source._supply_automated_route(
        _Record(),
        session,
        adapter,
        _Record.manufacturer,
        _Record.mpn,
        url,
        ["kicad", "model", "altium"],
    )

    assert page.gotos == [(url, {"wait_until": "domcontentloaded"})]
    assert outcome.error == "no fixture download"
    assert not outcome.skipped


def test_only_a_proved_absent_provider_route_is_unavailable(tmp_path):
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · Ultra Librarian",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        browser_access="machine_allowed",
    )
    adapter = type(
        "_Route",
        (),
        {
            "capability": capability,
            "evidence_provider_key": "digikey-ultralibrarian",
        },
    )()
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        operator_authorized=True,
    )
    source._sign_in_attempted = True
    source._prepare_sign_in = lambda *_args: None
    source._drive_automated = lambda *_args: (
        DriveReport(
            missed=["kicad", "model", "altium"],
            route_unavailable=True,
            message="DigiKey does not offer this author for the exact product.",
        ),
        None,
    )

    outcome = source._supply_automated_route(
        _Record(),
        guided._Session(browser=_FakeBrowser(), ctx_manager=None, page=_FakePage()),
        adapter,
        _Record.manufacturer,
        _Record.mpn,
        "https://www.digikey.com/en/products/result?keywords=TPD6E05U06RVZR",
        ["kicad", "model", "altium"],
    )

    assert outcome.skipped == "DigiKey does not offer this author for the exact product."
    assert not outcome.error


def test_reusable_exclusive_route_downloads_all_formats_without_reloading():
    class Page:
        url = "https://www.digikey.com/en/models/4307639?tab=ultralibrarian"

        def __init__(self):
            self.gotos = []

        def goto(self, url, **options):
            self.gotos.append((url, options))
            self.url = url

    page = Page()

    class Browser:
        def __init__(self):
            self.captured = []
            self.download_errors = []

    browser = Browser()
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · Ultra Librarian",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        browser_access="machine_allowed",
        reuse_page_between_formats=True,
    )

    class Adapter:
        max_download_attempts = 3

        def __init__(self):
            self.capability = capability
            self.formats = []

        def drive(self, _page, formats, **_identity):
            self.formats.extend(formats)
            browser.captured.append(_CapturedFile(Path(f"{formats[0]}.zip")))
            return DriveReport(selected=list(formats), submitted=True)

    adapter = Adapter()
    report, error = guided.drive_formats(
        browser,
        page,
        adapter,
        ["kicad", "model", "altium"],
        "https://www.digikey.com/en/products/result?keywords=TPD6E05U06RVZR",
        expected_manufacturer="Texas Instruments",
        expected_mpn="TPD6E05U06RVZR",
    )

    assert error is None
    assert page.gotos == []
    assert adapter.formats == ["kicad", "model", "altium"]
    assert report.selected == ["kicad", "model", "altium"]


@pytest.mark.parametrize(
    "capture_status",
    ["completed", "timed_out", "try_another", "cancelled"],
)
def test_user_driven_guided_supply_never_discards_captured_files(
    monkeypatch,
    tmp_path,
    capture_status,
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
        surface_key="faketron",
        evidence_provider_key="faketron",
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
                status=capture_status,
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
    cancel_calls: list[bool] = []
    source = guided.GuidedCaptureSource(
        lambda: pipeline,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        headless=True,
        user_driven=True,
        user_finished=finished,
        user_cancelled=cancelled,
        user_capture_timeout_s=5,
        cancel_workflow=lambda: cancel_calls.append(True),
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
    assert hud.author_route == "Faketron"
    assert hud.manufacturer == _Record.manufacturer
    assert hud.mpn == _Record.mpn
    assert hud.required_file_labels == ("KiCad symbol and footprint",)
    assert captured_call["options"] == {
        "should_finish": finished,
        "should_cancel": cancelled,
        "timeout_s": 5,
        "retryable_render_issue": None,
        "max_render_reloads": 0,
    }
    assert pipeline.inputs == [landed]
    assert "no exact KiCad symbol, footprint, and STEP" in (outcome.error or "")
    assert bool(cancel_calls) is (capture_status == "cancelled")
    assert outcome.blocked is (capture_status == "cancelled")


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


def test_snapmagic_phone_verification_timeout_is_reported_as_a_resumable_blocker(
    monkeypatch,
    tmp_path,
):
    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)

    def capture_user_downloads(_url, _broker, **_options):
        return UserCaptureResult(
            status="timed_out",
            files=(),
            final_url="https://www.snapeda.com/profiles/verify/",
        )

    browser.capture_user_downloads = capture_user_downloads
    source = guided.GuidedCaptureSource(
        lambda: (_ for _ in ()).throw(AssertionError("a provider gate must not attach")),
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        user_driven=True,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = source.supply(_Record())

    assert not outcome.error
    assert outcome.blocked is True
    assert "one-time phone verification" in outcome.skipped
    assert "embedded provider tab" in outcome.skipped


def test_selected_files_survive_a_browser_failure_and_keep_the_exact_route_binding(
    monkeypatch,
    tmp_path,
):
    from stockroom.capture.intent import PersonCaptureIntent

    browser = _FakeBrowser()
    _install_adapter(monkeypatch, browser, on_drive=lambda _browser: None)
    selected = tmp_path / "Recovered.zip"
    selected.write_bytes(b"selected CAD")
    intent = PersonCaptureIntent("part-1")

    def capture_user_downloads(url, _broker, **options):
        active = intent.active_route()
        assert active is not None
        intent.queue_selected_files(
            vendor="faketron",
            detail_url=url,
            route_token=active["route_token"],
            paths=(selected,),
        )
        assert options["should_finish"]() is True
        raise RuntimeError("provider page crashed after the selection was accepted")

    browser.capture_user_downloads = capture_user_downloads
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        user_driven=True,
        user_finished=intent.take_route_finish,
        publish_active_route=intent.set_active_route,
        clear_active_route=intent.clear_active_route,
        take_selected_files=intent.take_selected_files,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())
    observed = {}

    def attach(_record, landed, _url, **options):
        observed["receipt"] = landed[0]
        observed["options"] = options
        return SourceOutcome(satisfied=(Requirement.KICAD_SYMBOL,))

    monkeypatch.setattr(source, "_attach", attach)

    outcome = source.supply(_Record())

    assert outcome.satisfied == (Requirement.KICAD_SYMBOL,)
    assert observed["receipt"].transport == "manual-file-picker"
    assert observed["receipt"].evidence_provider_key == "faketron"
    assert observed["options"]["evidence_provider_key"] == "faketron"
    assert observed["options"]["manual_identity_paths"] == (observed["receipt"].path,)
    assert intent.active_route() is None


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
# Dual-EDA activation. Provider files are retained, but no one-tool download may become the active
# library. KiCad, STEP, and native Altium must survive one same-download validation transaction.
# --------------------------------------------------------------------------------------------


def _zip_with(tmp_path, members: dict[str, bytes]):
    import zipfile

    path = tmp_path / "vendor.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    return path


def test_altium_only_download_is_never_projected_as_a_complete_part(monkeypatch, tmp_path):
    """Native Altium files stay non-projectable without same-download KiCad and STEP."""
    browser = _FakeBrowser()
    bundle = _zip_with(
        tmp_path,
        {
            "AltiumLibs/PART.SchLib": b"altium-symbol",
            "AltiumLibs/PART.PcbLib": b"altium-footprint",
        },
    )

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
    outcome = src.supply(_Record())

    assert outcome.satisfied == ()
    assert "no exact KiCad symbol, footprint, and STEP" in outcome.error


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

    assert found is not None
    assert sorted(path.suffix.casefold() for path in found.paths) == [".pcblib", ".schlib"]
    assert all(
        path.read_bytes().startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        for path in found.paths
    )
    root = found.root
    found.cleanup()
    assert not root.exists()


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


def test_no_saved_credentials_is_named_but_never_fatal(monkeypatch, tmp_path):
    """Nothing saved must be NAMED on the part row, and must still not attempt a login.

    It stayed silent until 2026-07-31, and that silence is what left the owner guessing: a
    signed-out provider produced only "the Download button is not on this page", which is the
    symptom of the missing sign-in rather than the cause. The reason now rides on
    `_sign_in_error` and is appended to that row. It is still not fatal - everything up to the
    Download button works signed out, so the drive still runs and may report something better.
    """

    adapter = _LoginAdapter()
    src = _source_with_adapter(monkeypatch, tmp_path, _FakeBrowser(), adapter, lambda key: None)
    src._sign_in_once(_FakePage())
    assert adapter.calls == []
    assert "no Faketron sign-in is saved in Settings" in src._sign_in_error


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
    assert "did not accept the saved credentials" in (outcome.error or ""), outcome


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


def test_the_default_vendor_chain_uses_digikeys_multi_author_surface_then_fallbacks():
    """One DigiKey page can collect all authors; direct providers remain fallbacks."""
    from stockroom.capture import runner

    assert runner._vendor_chain(None) == [
        "digikey",
        "ultralibrarian",
        "snapmagic",
        "samacsys",
    ]


def test_digikey_collects_every_embedded_author_route_after_first_success(
    monkeypatch,
    tmp_path,
):
    def make_capability(label: str) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={
                "kicad": "KiCad v6+",
                "model": "STEP",
                "altium": "Altium Designer",
            },
            browser_access="machine_allowed",
        )

    snap = type(
        "_Route",
        (),
        {
            "capability": make_capability("DigiKey · SnapMagic"),
            "evidence_provider_key": "digikey-snapmagic",
        },
    )()
    ultra = type(
        "_Route",
        (),
        {
            "capability": make_capability("DigiKey · Ultra Librarian"),
            "evidence_provider_key": "digikey-ultralibrarian",
        },
    )()

    class _DigiKey:
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return (snap, ultra)

    parent = _DigiKey()
    parent.capability = make_capability("DigiKey CAD Models")
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        machine_access_check=lambda: True,
        collect_variants=True,
    )
    source._session = guided._Session(browser=_FakeBrowser(), ctx_manager=None, page=_FakePage())
    captured_routes: list[str] = []

    assert source.provider_route_ids() == (
        "digikey:digikey-snapmagic",
        "digikey:digikey-ultralibrarian",
    )

    def capture_route(_record, _session, route, *_args):
        captured_routes.append(route.evidence_provider_key)
        if len(captured_routes) > 1:
            return SourceOutcome(
                retained=5,
                skipped="retained a complete alternate provider pair",
            )
        return SourceOutcome(
            satisfied=(
                Requirement.KICAD_SYMBOL,
                Requirement.KICAD_FOOTPRINT,
            )
        )

    source._supply_automated_route = capture_route

    outcome = source.supply(_Record())

    assert captured_routes == ["digikey-snapmagic", "digikey-ultralibrarian"]
    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
    }
    assert [row.route_id for row in outcome.provider_outcomes] == [
        "digikey:digikey-snapmagic",
        "digikey:digikey-ultralibrarian",
    ]
    assert [row.status for row in outcome.provider_outcomes] == [
        "activated",
        "succeeded-retained",
    ]


def test_finish_first_stops_after_the_first_complete_author_route(monkeypatch, tmp_path):
    capability = VendorCapability(
        key="digikey",
        label="DigiKey CAD Models",
        tools=("kicad", "altium"),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        machine_format_labels={"kicad": "KiCad v6+", "altium": "Altium Designer"},
        browser_access="machine_allowed",
    )
    routes = tuple(
        type(
            "_Route",
            (),
            {
                "capability": capability,
                "evidence_provider_key": author,
            },
        )()
        for author in ("digikey-ultralibrarian", "digikey-snapmagic")
    )

    class _DigiKey:
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return routes

    parent = _DigiKey()
    parent.capability = capability
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    monkeypatch.setattr(
        guided,
        "capture_needs",
        lambda _record: [Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT],
    )
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(browser=_FakeBrowser(), ctx_manager=None, page=_FakePage())
    attempted: list[str] = []

    def capture_route(_record, _session, route, *_args):
        attempted.append(route.evidence_provider_key)
        return SourceOutcome(
            satisfied=(Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT)
        )

    source._supply_automated_route = capture_route

    outcome = source.supply(_Record())

    assert attempted == ["digikey-ultralibrarian"]
    assert [row.status for row in outcome.provider_outcomes] == [
        "activated",
        "not-attempted",
    ]
    assert "first validated source set" in outcome.provider_outcomes[1].reason


def test_cancellation_between_author_routes_prevents_the_next_route(monkeypatch, tmp_path):
    capability = VendorCapability(
        key="digikey",
        label="DigiKey CAD Models",
        tools=("kicad",),
        formats_exclusive=True,
        aggregator=True,
        needs_login=True,
        instruction="",
        machine_format_labels={"kicad": "KiCad v6+"},
        browser_access="machine_allowed",
    )
    routes = tuple(
        type(
            "_Route",
            (),
            {"capability": capability, "evidence_provider_key": author},
        )()
        for author in ("digikey-ultralibrarian", "digikey-snapmagic")
    )

    class _DigiKey:
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return routes

    parent = _DigiKey()
    parent.capability = capability
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    cancelled = False
    attempted: list[str] = []
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        machine_access_check=lambda: True,
        user_cancelled=lambda: cancelled,
    )
    source._session = guided._Session(browser=_FakeBrowser(), ctx_manager=None, page=_FakePage())

    def capture_route(_record, _session, route, *_args):
        nonlocal cancelled
        attempted.append(route.evidence_provider_key)
        cancelled = True
        return SourceOutcome(skipped="first route ended")

    source._supply_automated_route = capture_route

    outcome = source.supply(_Record())

    assert attempted == ["digikey-ultralibrarian"]
    assert [row.status for row in outcome.provider_outcomes] == [
        "unavailable",
        "cancelled",
    ]


def test_blocked_digikey_route_ledgers_every_later_route_as_not_attempted(
    monkeypatch,
    tmp_path,
):
    def make_capability(label: str) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={"kicad": "KiCad v6+", "altium": "Altium Designer"},
            browser_access="machine_allowed",
        )

    routes = tuple(
        type(
            "_Route",
            (),
            {
                "capability": make_capability(label),
                "evidence_provider_key": author,
            },
        )()
        for label, author in (
            ("DigiKey · Ultra Librarian", "digikey-ultralibrarian"),
            ("DigiKey · SnapMagic", "digikey-snapmagic"),
            ("DigiKey · TraceParts", "digikey-traceparts"),
        )
    )

    class _DigiKey:
        capability = make_capability("DigiKey CAD Models")
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return routes

    parent = _DigiKey()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(
        browser=_FakeBrowser(),
        ctx_manager=None,
        page=_FakePage(),
    )
    attempted_routes: list[str] = []

    def blocked_route(_record, _session, route, *_args):
        attempted_routes.append(route.evidence_provider_key)
        return SourceOutcome(
            error="DigiKey sign-in or security check requires user input",
            blocked=True,
        )

    source._supply_automated_route = blocked_route

    outcome = source.supply(_Record())

    assert attempted_routes == ["digikey-ultralibrarian"]
    assert [row.status for row in outcome.provider_outcomes] == [
        "requires-human",
        "not-attempted",
        "not-attempted",
    ]
    assert [row.attempted for row in outcome.provider_outcomes] == [
        True,
        False,
        False,
    ]


def test_collect_variants_visits_model_only_routes_for_a_two_d_gap(monkeypatch, tmp_path):
    def capability(label: str, formats: dict[str, str]) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=False,
            instruction="",
            machine_format_labels=formats,
            browser_access="machine_allowed",
        )

    coherent = type(
        "_Route",
        (),
        {
            "capability": capability(
                "DigiKey CAD Models",
                {"kicad": "KiCad v6+", "model": "STEP", "altium": "Altium Designer"},
            ),
            "evidence_provider_key": "digikey-ultralibrarian",
        },
    )()
    model_only = type(
        "_Route",
        (),
        {
            "capability": capability(
                "DigiKey · Manufacturer Provided",
                {"model": "3D Model"},
            ),
            "evidence_provider_key": "digikey-manufacturer",
            "supplementary_only": True,
        },
    )()

    class _DigiKey:
        capability = coherent.capability
        evidence_provider_key = coherent.evidence_provider_key

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return coherent, model_only

    parent = _DigiKey()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    monkeypatch.setattr(
        guided,
        "capture_needs",
        lambda _record: [Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT],
    )
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        collect_variants=True,
        operator_authorized=True,
    )
    source._session = guided._Session(
        browser=_FakeBrowser(),
        ctx_manager=None,
        page=_FakePage(),
    )
    requested: list[tuple[str, list[str]]] = []

    def capture_route(_record, _session, route, _manufacturer, _mpn, _url, formats):
        requested.append((route.evidence_provider_key, list(formats)))
        return SourceOutcome(skipped="fixture route settled")

    source._supply_automated_route = capture_route

    source.supply(_Record())

    assert requested == [
        ("digikey-ultralibrarian", ["kicad", "model", "altium"]),
        ("digikey-manufacturer", ["model"]),
    ]


def test_unavailable_digikey_route_does_not_skip_the_next_author(
    monkeypatch,
    tmp_path,
):
    def make_capability(label: str) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad",),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={"kicad": "KiCad v6+"},
            browser_access="machine_allowed",
        )

    routes = tuple(
        type(
            "_Route",
            (),
            {
                "capability": make_capability(label),
                "evidence_provider_key": author,
            },
        )()
        for label, author in (
            ("DigiKey · Ultra Librarian", "digikey-ultralibrarian"),
            ("DigiKey · SnapMagic", "digikey-snapmagic"),
        )
    )

    class _DigiKey:
        capability = make_capability("DigiKey CAD Models")
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return routes

    parent = _DigiKey()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: parent)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        machine_access_check=lambda: True,
    )
    source._session = guided._Session(
        browser=_FakeBrowser(),
        ctx_manager=None,
        page=_FakePage(),
    )
    attempted_routes: list[str] = []

    def capture_route(_record, _session, route, *_args):
        attempted_routes.append(route.evidence_provider_key)
        if route is routes[0]:
            return SourceOutcome(skipped="no exact deliverable on this route")
        return SourceOutcome(
            satisfied=(Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT)
        )

    source._supply_automated_route = capture_route

    outcome = source.supply(_Record())

    assert attempted_routes == [
        "digikey-ultralibrarian",
        "digikey-snapmagic",
    ]
    assert [row.status for row in outcome.provider_outcomes] == [
        "unavailable",
        "activated",
    ]
    assert all(row.attempted for row in outcome.provider_outcomes)


def test_user_driven_try_another_advances_to_the_next_digikey_author(
    monkeypatch,
    tmp_path,
):
    def make_capability(label: str) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={
                "kicad": "KiCad v6+",
                "model": "STEP",
                "altium": "Altium Designer",
            },
            browser_access="user_driven",
        )

    routes = tuple(
        type(
            "_Route",
            (),
            {
                "capability": make_capability(label),
                "evidence_provider_key": author,
            },
        )()
        for label, author in (
            ("DigiKey · Ultra Librarian", "digikey-ultralibrarian"),
            ("DigiKey · SnapMagic", "digikey-snapmagic"),
        )
    )

    class _DigiKey:
        capability = make_capability("DigiKey CAD Models")
        evidence_provider_key = "digikey-ultralibrarian"

        def resolve_url(self, mpn):
            return f"https://www.digikey.com/en/products/result?keywords={mpn}"

        def capture_routes(self):
            return routes

    monkeypatch.setattr(guided, "get_adapter", lambda _key: _DigiKey())
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        user_driven=True,
        collect_variants=True,
    )
    source._session = guided._Session(
        browser=_FakeBrowser(),
        ctx_manager=None,
        page=_FakePage(),
    )
    attempted: list[str] = []

    def capture_route(_record, _session, route, *_args):
        attempted.append(route.evidence_provider_key)
        if route is routes[0]:
            return SourceOutcome(skipped="left for another provider", blocked=False)
        return SourceOutcome(retained=5, skipped="retained complete SnapMagic set")

    source._supply_user_driven_route = capture_route

    outcome = source.supply(_Record())

    assert attempted == ["digikey-ultralibrarian", "digikey-snapmagic"]
    assert [row.status for row in outcome.provider_outcomes] == [
        "unavailable",
        "succeeded-retained",
    ]
    assert all(row.attempted for row in outcome.provider_outcomes)


def test_close_after_supply_releases_the_provider_before_control_returns(
    monkeypatch,
    tmp_path,
):
    capability = VendorCapability(
        key="faketron",
        label="Faketron",
        tools=("kicad",),
        formats_exclusive=False,
        aggregator=False,
        needs_login=False,
        instruction="",
    )
    adapter = type("_Adapter", (), {"capability": capability})()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: adapter)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        close_after_supply=True,
    )
    events: list[str] = []
    source._supply_once = lambda _record: (
        events.append("supply") or SourceOutcome(skipped="unavailable")
    )
    source.close = lambda: events.append("close")

    source.supply(_Record())

    assert events == ["supply", "close"]


def test_a_preferred_vendor_keeps_the_other_implemented_provider_as_fallback():
    """A chosen provider changes priority without disabling automatic fallback."""
    from stockroom.capture import runner

    assert runner._vendor_chain("snapmagic") == [
        "snapmagic",
        "digikey",
        "ultralibrarian",
        "samacsys",
    ]
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
    assert (
        guided._provider_hud_author_route(guided.get_adapter("ultralibrarian"))
        == "Ultra Librarian"
    )
    assert (
        guided._provider_hud_author_route(guided.get_adapter("digikey"))
        == "Ultra Librarian"
    )


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


def test_digikey_transient_download_failure_reopens_and_retries_exact_format(tmp_path):
    browser = _FakeBrowser()
    attempts: list[str] = []

    class _RetryingDigiKey:
        max_download_attempts = 3
        capability = VendorCapability(
            key="digikey",
            label="DigiKey · SnapMagic",
            tools=("kicad",),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={"kicad": "KiCad v6+"},
            browser_access="machine_allowed",
        )

        def drive(self, _page, formats):
            attempts.append(formats[0])
            if len(attempts) == 2:
                browser.captured.append(_CapturedFile(tmp_path / "landed.zip"))
            return DriveReport(selected=list(formats), submitted=True)

        def retryable_download_issue(self, _page):
            return (
                "DigiKey reported a retryable download failure"
                if len(attempts) == 1
                else ""
            )

    report, failure = guided.drive_formats(
        browser,
        _FakePage(),
        _RetryingDigiKey(),
        ["kicad"],
        "https://www.digikey.com/en/products/result?keywords=ABC-1",
    )

    assert failure is None
    assert attempts == ["kicad", "kicad"]
    assert report.selected == ["kicad"]
    assert report.submitted is True


def test_cad_exports_that_bundle_step_skip_the_duplicate_model_pass(tmp_path):
    browser = _FakeBrowser()
    drives: list[str] = []

    class _BundledStep:
        capability = VendorCapability(
            key="digikey",
            label="DigiKey · Ultra Librarian",
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={
                "kicad": "KiCad v6+",
                "model": "STEP",
                "altium": "PCAD v15",
            },
            browser_access="machine_allowed",
            bundles_model_with_cad=True,
        )

        def drive(self, _page, formats):
            fmt = formats[0]
            drives.append(fmt)
            browser.captured.append(_CapturedFile(tmp_path / f"{fmt}.zip"))
            return DriveReport(selected=[fmt], submitted=True)

    report, failure = guided.drive_formats(
        browser,
        _FakePage(),
        _BundledStep(),
        ["kicad", "model", "altium"],
        "https://www.digikey.com/en/models/1?tab=ultralibrarian",
    )

    assert failure is None
    assert drives == ["kicad", "altium"]
    assert report.selected == ["kicad", "altium"]
    assert len(browser.captured) == 2


def test_exclusive_drive_waits_for_the_reported_download_count(tmp_path):
    browser = _FakeBrowser()

    class _MultiDownload:
        max_download_attempts = 1
        capability = VendorCapability(
            key="digikey",
            label="DigiKey · Manufacturer Provided",
            tools=("kicad",),
            formats_exclusive=True,
            aggregator=True,
            needs_login=False,
            instruction="",
            machine_format_labels={"model": "3D Model"},
            browser_access="machine_allowed",
        )

        def drive(self, _page, formats):
            browser.captured.extend(
                _CapturedFile(tmp_path / f"original-{index}.stp")
                for index in range(2)
            )
            return DriveReport(
                selected=list(formats),
                submitted=True,
                expected_downloads=3,
            )

    report, failure = guided.drive_formats(
        browser,
        _FakePage(),
        _MultiDownload(),
        ["model"],
        "https://www.digikey.com/en/products/result?keywords=ABC-1",
        timeout_s=0.05,
    )

    assert report.submitted is False
    assert len(browser.captured) == 2
    assert failure == "DigiKey · Manufacturer Provided did not deliver model within 0s"


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


def test_a_late_format_failure_retains_files_that_already_landed(monkeypatch, tmp_path):
    browser = _FakeBrowser()
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "downloads",
        headless=True,
        machine_access_check=lambda: True,
    )
    session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())
    retained: list[tuple[list[_CapturedFile], str]] = []

    class _Adapter:
        capability = VendorCapability(
            key="faketron",
            label="Faketron",
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=False,
            needs_login=False,
            instruction="",
            browser_access="machine_allowed",
        )

    def fail_after_two_files(*_args, **_kwargs):
        browser.captured.extend(
            [
                _CapturedFile(tmp_path / "symbol.zip"),
                _CapturedFile(tmp_path / "model.step"),
            ]
        )
        return (
            DriveReport(selected=["kicad", "model"], submitted=False),
            "Faketron did not deliver altium within 1s",
        )

    def retain(_record, landed, *, reason, **_kwargs):
        retained.append((list(landed), reason))
        return SourceOutcome(retained=len(landed), skipped=f"{reason}; retained")

    monkeypatch.setattr(source, "_prepare_sign_in", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(source, "_drive_automated", fail_after_two_files)
    monkeypatch.setattr(source, "_retain_incomplete_cad_set", retain)

    outcome = source._supply_automated_route(
        _Record(),
        session,
        _Adapter(),
        _Record.manufacturer,
        _Record.mpn,
        "https://example.invalid/exact-part",
        ["kicad", "model", "altium"],
    )

    assert outcome.retained == 2
    assert [item.path.name for item in retained[0][0]] == ["symbol.zip", "model.step"]
    assert "did not deliver altium" in retained[0][1]


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


def test_missing_digikey_author_route_skips_remaining_format_timeouts():
    attempts: list[list[str]] = []

    class _UnavailableRoute:
        capability = VendorCapability(
            key="digikey",
            label="DigiKey · SnapMagic",
            tools=("kicad", "altium"),
            formats_exclusive=True,
            aggregator=True,
            needs_login=True,
            instruction="",
            machine_format_labels={
                "kicad": "KiCad v6+",
                "model": "STEP",
                "altium": "Altium Designer",
            },
        )

        def drive(self, _page, formats):
            attempts.append(list(formats))
            return DriveReport(
                missed=list(formats),
                route_unavailable=True,
                message="DigiKey does not offer SnapMagic for this exact product.",
            )

    report, failure = guided.drive_formats(
        _FakeBrowser(),
        _FakePage(),
        _UnavailableRoute(),
        ["kicad", "model", "altium"],
        "https://www.digikey.com/en/products/result?keywords=ABC-1",
    )

    assert failure is None
    assert report.route_unavailable is True
    assert attempts == [["kicad"]]
