"""Guided capture must decide success by looking at the SAVED FILE, never at the download event.

THE BUG THIS LOCKS, measured 2026-07-27. Guided capture waited with
`page.wait_for_event("download")`. But `PlaywrightCaptureBrowser` already registers an
`on("download")` handler when the session opens, and Playwright delivers a given event to whichever
listener is active - so a download that completed quickly was consumed by the handler, the wait
never saw it, and the source reported a hard failure for a file that was already on disk.

Two things made it expensive rather than merely wrong:
  * the failure is TIMING-dependent, so it looked like a hang (a 60-120s stall per part) rather
    than a bug, and it is what hung the suite;
  * it produced a confident NEGATIVE conclusion about the wrong component - "the browser cannot
    download" - when the browser had downloaded the file correctly.

The person now works every provider page, so what is asserted here is the rest of the chain:
the exact route Stockroom opens, the task-bound receipts it accepts, and the fact that nothing
already captured is ever discarded.
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
from stockroom.capture.vendors import VendorCapability


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
    """Stands in for the real browser. `captured` is the OBSERVATION the source must key on.

    ``on_delivery`` stands in for the PERSON: the person-driven window opens, they work the
    provider page, and whatever they start arrives through the task-bound broker exactly as the
    real session handler delivers it.
    """

    def __init__(self, on_delivery=None):
        self.captured: list[_CapturedFile] = []
        self.on_delivery = on_delivery

    def capture_user_downloads(self, url, broker, **_options):
        del broker
        if self.on_delivery is not None:
            self.on_delivery(self)
        return UserCaptureResult(
            status="completed",
            files=tuple(self.captured),
            final_url=url,
        )


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

        Capture waits THROUGH the page on purpose (a bare `time.sleep` never lets the sync api
        dispatch `on("download")`), so the fake has to offer the same call or the test would be
        exercising a signature the production code does not use.
        """
        time.sleep(ms / 1000.0)

    def wait_for_event(self, *args, **kwargs):  # pragma: no cover - it must never be reached
        raise AssertionError(
            "supply() waited on the download EVENT. The browser session's own on('download') "
            "handler races that wait and consumes the event, so a fast download reports failure "
            "for a file that landed. Poll the saved list instead."
        )


def _install_adapter(monkeypatch, browser, *, on_drive=None):
    """Register a fake vendor surface. It carries DATA only, like every real one."""
    del browser, on_drive
    capability = VendorCapability(
        key="ultralibrarian",
        label="Faketron",
        tools=("kicad",),
        aggregator=False,
        needs_login=False,
        instruction="",
        user_format_labels={"kicad": "KiCad symbol and footprint"},
    )

    class _Adapter:
        def __init__(self):
            self.capability = capability

        def resolve_url(self, mpn: str) -> str:
            return f"https://app.ultralibrarian.com/search?queryText={mpn}"

    monkeypatch.setattr(guided, "get_adapter", lambda key: _Adapter())
    return capability


def _source(monkeypatch, tmp_path, browser, *, on_drive=None, pipeline=None):
    _install_adapter(monkeypatch, browser, on_drive=on_drive)
    if on_drive is not None and getattr(browser, "on_delivery", None) is None:
        browser.on_delivery = on_drive
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

    monkeypatch.setattr(guided, "PlaywrightCaptureBrowser", _EmbeddedBrowser)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="faketron",
        download_root=tmp_path / "downloads",
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
    """A file from an earlier part sits on the browser; only THIS task's receipts may attach."""

    class Pipeline:
        def __init__(self):
            self.inputs = None

        def inspect(self, inputs):
            self.inputs = list(inputs)
            return []

        def cleanup(self):
            return None

    current = tmp_path / "current.zip"
    current.write_bytes(b"current-part")
    stale = tmp_path / "stale.zip"
    stale.write_bytes(b"previous-part")

    class Browser:
        """Delivers this task's file through its own broker, as the real session handler does."""

        def __init__(self):
            self.captured = [CapturedFile(stale, "stale.zip", "https://previous.invalid")]

        def capture_user_downloads(self, url, broker, **_options):
            receipt = broker.capture_local_file(
                current,
                source_url="https://vendor.example.test/current.zip",
                transport="manual-file-picker",
            )
            return UserCaptureResult(status="completed", files=(receipt,), final_url=url)

    browser = Browser()
    pipeline = Pipeline()
    _install_adapter(monkeypatch, browser)
    source = guided.GuidedCaptureSource(
        lambda: pipeline,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        headless=True,
    )
    source._session = guided._Session(browser=browser, ctx_manager=None, page=_FakePage())

    outcome = source.supply(_Record())

    assert pipeline.inputs is not None
    assert stale not in pipeline.inputs
    assert len(pipeline.inputs) == 1
    assert pipeline.inputs[0].read_bytes() == b"current-part"
    assert "no exact KiCad symbol, footprint, and STEP" in (outcome.error or "")


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

    _install_adapter(monkeypatch, object())
    monkeypatch.setattr(guided, "PlaywrightCaptureBrowser", Browser)
    finished = lambda: True
    cancelled = lambda: False
    cancel_calls: list[bool] = []
    source = guided.GuidedCaptureSource(
        lambda: pipeline,
        vendor="faketron",
        download_root=tmp_path / "Downloads",
        headless=True,
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


# --------------------------------------------------------------------------------------------
# `signed_in` MUST DISCRIMINATE. The first version checked only that `#loginLink` was absent, and
# returned True on the identity server's own login page - so a WRONG PASSWORD reported success in
# the same 3.5s as the right one. It was caught solely by feeding it a deliberately bad password.
# The three states below are the real ones, measured live 2026-07-27.
# --------------------------------------------------------------------------------------------


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


def test_user_driven_try_another_advances_to_the_next_digikey_author(
    monkeypatch,
    tmp_path,
):
    def make_capability(label: str) -> VendorCapability:
        return VendorCapability(
            key="digikey",
            label=label,
            tools=("kicad", "altium"),
            aggregator=True,
            needs_login=True,
            instruction="",
            user_format_labels={
                "kicad": "KiCad v6 or later",
                "model": "STEP",
                "altium": "Altium Designer",
            },
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
    assert sm.capability.user_format_labels["altium"] == "Altium native"
    # KiCad V6+, never the V3/V4 rows: KiCad 5 emits `(module ...)` that Footprint.load REFUSES.
    assert sm.capability.user_format_labels["kicad"] == "KiCad V6 & Later"


def test_ultra_librarian_native_altium_is_sourceable_without_a_dom_selector(tmp_path):
    """The user selects the current native export; Stockroom owns validation and attachment."""
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path / "downloads",
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


