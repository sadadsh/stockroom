"""Windows production browser policy and provider-profile ownership."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import quote

import pytest

from stockroom.capture import browser as browser_module
from stockroom.capture.browser import (
    CaptureBrowserError,
    PlaywrightCaptureBrowser,
    ProviderHudSpec,
    ProviderProfileLock,
    ProviderSurfaceCapture,
    SharedPlaywrightRuntime,
    _allow_automatic_downloads,
    _browser_candidates,
    _completed_provider_formats,
    provider_profile_dir,
)
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.runner import (
    _capture_downloads,
    _capture_evidence_root,
    capture_state_root,
)


def test_download_completion_comes_from_complementary_archive_contents(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    kicad = tmp_path / "KiCad.zip"
    altium = tmp_path / "Altium.zip"
    with zipfile.ZipFile(kicad, "w") as archive:
        archive.writestr("Part.kicad_sym", "symbol")
        archive.writestr("Part.pretty/Part.kicad_mod", "footprint")
        archive.writestr("Part.step", "model")
    with zipfile.ZipFile(altium, "w") as archive:
        archive.writestr("Part.SchLib", "symbol")
        archive.writestr("Part.PcbLib", "footprint")
    broker = DownloadBroker(
        DownloadTask(
            task_id="part-a",
            manufacturer_key="Exact Manufacturer",
            mpn_canonical="MPN-A/7",
            staging_root=staging,
        )
    )
    first = broker.capture_local_file(kicad, source_url="https://provider.example/kicad")
    second = broker.capture_local_file(altium, source_url="https://provider.example/altium")

    assert _completed_provider_formats(
        (first,),
        ("kicad", "model", "altium"),
    ) == ("kicad", "model")
    assert _completed_provider_formats(
        (first, second),
        ("kicad", "model", "altium"),
    ) == ("kicad", "model", "altium")


class _Context:
    def __init__(self):
        self.init_scripts: list[str] = []

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


def _claim_profile_in_child(profile: str, result) -> None:
    try:
        with ProviderProfileLock(Path(profile), "snapmagic"):
            result.put("acquired")
    except CaptureBrowserError:
        result.put("busy")


class _BrowserType:
    def __init__(self, *, fail_channels=()):
        self.fail_channels = set(fail_channels)
        self.calls: list[tuple[str, Path, dict]] = []

    def launch_persistent_context(self, profile: str, **options):
        channel = options.get("channel", "")
        self.calls.append(("persistent", Path(profile), options))
        if channel in self.fail_channels:
            raise RuntimeError(f"{channel} unavailable")
        return _Context()


def test_windows_policy_prefers_installed_chrome_then_managed_chromium():
    assert [candidate.channel for candidate in _browser_candidates("windows")] == [
        "chrome",
        None,
    ]


def test_windows_policy_falls_back_to_managed_chromium_with_the_same_provider_profile(tmp_path):
    browser_type = _BrowserType(fail_channels={"chrome"})
    pw = SimpleNamespace(chromium=browser_type)
    profile = tmp_path / "profiles" / "snapmagic"
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "downloads",
        profile_dir=profile,
        provider_key="snapmagic",
        engine="windows",
        headless=False,
    )

    context, launched = browser._launch_playwright(pw)

    assert isinstance(context, _Context)
    assert launched is None
    assert browser.launched_browser == "Playwright Chromium"
    assert [call[2].get("channel") for call in browser_type.calls] == ["chrome", None]
    assert all(call[1] == profile for call in browser_type.calls)
    assert all(call[2]["accept_downloads"] is True for call in browser_type.calls)
    assert all(call[2]["headless"] is False for call in browser_type.calls)
    assert all(call[2]["timeout"] == 20_000 for call in browser_type.calls)
    assert len(context.init_scripts) == 1
    assert "RTCPeerConnection" in context.init_scripts[0]
    assert "webkitRTCPeerConnection" in context.init_scripts[0]
    preferences = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert preferences["profile"]["default_content_setting_values"]["automatic_downloads"] == 1


def test_automatic_download_permission_preserves_existing_profile_preferences(tmp_path):
    profile = tmp_path / "snapmagic"
    preferences_path = profile / "Default" / "Preferences"
    preferences_path.parent.mkdir(parents=True)
    preferences_path.write_text(
        json.dumps(
            {
                "profile": {"name": "SnapMagic"},
                "download": {"prompt_for_download": False},
            }
        ),
        encoding="utf-8",
    )

    _allow_automatic_downloads(profile)

    preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
    assert preferences["profile"]["name"] == "SnapMagic"
    assert preferences["download"]["prompt_for_download"] is False
    assert preferences["profile"]["default_content_setting_values"]["automatic_downloads"] == 1


def test_malformed_profile_preferences_fail_closed(tmp_path):
    preferences_path = tmp_path / "snapmagic" / "Default" / "Preferences"
    preferences_path.parent.mkdir(parents=True)
    preferences_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CaptureBrowserError, match="safely update"):
        _allow_automatic_downloads(tmp_path / "snapmagic")


def test_the_provider_surface_capture_exposes_no_browser_driver_seam():
    """A person-driven capture must own no page, no context, and no engine choice.

    Every one of these was a real method on the retired provider browser. Naming them keeps the
    removal a contract instead of an absence nobody would notice being refilled.
    """

    for seam in (
        "session",
        "task_page",
        "engine",
        "navigate_provider",
        "ensure_connected",
        "wait_for_user_clearance",
        "_launch_playwright",
    ):
        assert not hasattr(ProviderSurfaceCapture, seam), seam


@pytest.mark.timeout(30)
def test_two_provider_contexts_share_one_real_playwright_runtime(tmp_path):
    from stockroom.capture.browser import chromium_unavailable_reason

    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    runtime = SharedPlaywrightRuntime()
    first = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "First Downloads",
        profile_dir=tmp_path / "First Profile",
        provider_key="first",
        headless=True,
        playwright_runtime=runtime,
    )
    second = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Second Downloads",
        profile_dir=tmp_path / "Second Profile",
        provider_key="second",
        headless=True,
        playwright_runtime=runtime,
    )
    try:
        with first.session() as first_page, second.session() as second_page:
            first_page.set_content("<title>First</title>")
            second_page.set_content("<title>Second</title>")
            assert first_page.title() == "First"
            assert second_page.title() == "Second"
    finally:
        runtime.close()


@pytest.mark.timeout(30)
def test_webrtc_is_disabled_before_scripts_in_each_new_document_and_frame(tmp_path):
    from stockroom.capture.browser import chromium_unavailable_reason

    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile",
        provider_key="webrtc-contract-probe",
        headless=True,
        engine="chromium",
    )
    observe_types = """
      window.observedWebRtcTypes = [
        typeof globalThis.RTCPeerConnection,
        typeof globalThis.webkitRTCPeerConnection,
      ];
    """
    expected = ["undefined", "undefined"]

    with browser.session() as page:
        for document_number in (1, 2):
            document = f"<script>{observe_types}</script><p>{document_number}</p>"
            page.goto(f"data:text/html,{quote(document)}")
            assert page.evaluate("window.observedWebRtcTypes") == expected

            page.evaluate(
                """observeTypes => {
                  const frame = document.createElement("iframe");
                  frame.srcdoc = `<script>${observeTypes}<\\/script>`;
                  document.body.appendChild(frame);
                }""",
                observe_types,
            )
            page.locator("iframe").wait_for()
            child = next(frame for frame in page.frames if frame is not page.main_frame)
            child.wait_for_load_state()
            assert child.evaluate("window.observedWebRtcTypes") == expected


@pytest.mark.timeout(30)
def test_digikey_session_state_survives_relaunch_only_in_its_provider_profile(tmp_path):
    from stockroom.capture.browser import chromium_unavailable_reason

    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            body = b"<title>Provider session probe</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    profile = tmp_path / "Profiles" / "digikey"

    def make_browser(provider_key: str, profile_dir: Path) -> PlaywrightCaptureBrowser:
        return PlaywrightCaptureBrowser(
            download_dir=tmp_path / "Downloads" / provider_key,
            profile_dir=profile_dir,
            provider_key=provider_key,
            headless=True,
            engine="chromium",
        )

    try:
        first = make_browser("digikey", profile)
        with first.session() as page:
            page.goto(url)
            page.evaluate(
                "localStorage.setItem('stockroom-session-probe', 'remembered-by-provider-profile')"
            )

        relaunched = make_browser("digikey", profile)
        with relaunched.session() as page:
            page.goto(url)
            remembered = page.evaluate("localStorage.getItem('stockroom-session-probe')")

        isolated = make_browser("ultralibrarian", tmp_path / "Profiles" / "ultralibrarian")
        with isolated.session() as page:
            page.goto(url)
            leaked = page.evaluate("localStorage.getItem('stockroom-session-probe')")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert first.persistent_digikey_session is True
    assert relaunched.persistent_digikey_session is True
    assert remembered == "remembered-by-provider-profile"
    assert isolated.persistent_digikey_session is False
    assert leaked is None


def test_provider_profiles_and_downloads_are_isolated(monkeypatch, tmp_path):
    machine_root = tmp_path / "Machine Capture"
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(machine_root))
    ctx = SimpleNamespace(
        profile=SimpleNamespace(library=SimpleNamespace(root=tmp_path / "Library"))
    )

    ultra_profile = provider_profile_dir(capture_state_root() / "Profiles", "ultralibrarian")
    snap_profile = provider_profile_dir(capture_state_root() / "Profiles", "snapmagic")
    ultra_downloads = _capture_downloads(ctx, "ultralibrarian")
    snap_downloads = _capture_downloads(ctx, "snapmagic")
    evidence = _capture_evidence_root(ctx)

    assert ultra_profile != snap_profile
    assert ultra_downloads != snap_downloads
    assert ultra_profile.name == "ultralibrarian"
    assert snap_profile.name == "snapmagic"
    assert ultra_downloads.name == "ultralibrarian"
    assert snap_downloads.name == "snapmagic"
    assert capture_state_root() == machine_root
    assert ultra_profile.parent == machine_root / "Profiles"
    assert ultra_downloads.parent == machine_root / "Downloads"
    assert evidence == machine_root / "Evidence"
    assert not ultra_profile.is_relative_to(tmp_path / "Library")


def test_a_provider_profile_has_one_worker_owner(tmp_path):
    profile = provider_profile_dir(tmp_path / "profiles", "snapmagic")
    first = ProviderProfileLock(profile, "snapmagic")
    second = ProviderProfileLock(profile, "snapmagic")

    first.acquire()
    try:
        with pytest.raises(CaptureBrowserError, match="already using its browser profile"):
            second.acquire()
    finally:
        first.release()

    # Releasing the first owner makes the same provider profile usable by the next job.
    with second:
        pass


def test_different_provider_profile_locks_do_not_contend(tmp_path):
    root = tmp_path / "profiles"
    ultra = ProviderProfileLock(provider_profile_dir(root, "ultralibrarian"), "ultralibrarian")
    snap = ProviderProfileLock(provider_profile_dir(root, "snapmagic"), "snapmagic")

    with ultra, snap:
        assert ultra.path != snap.path


def test_provider_profile_lock_excludes_another_process(tmp_path):
    profile = provider_profile_dir(tmp_path / "profiles", "snapmagic")
    owner = ProviderProfileLock(profile, "snapmagic")
    process_context = multiprocessing.get_context("spawn")
    result = process_context.Queue()

    owner.acquire()
    try:
        process = process_context.Process(
            target=_claim_profile_in_child,
            args=(str(profile), result),
        )
        process.start()
        process.join(timeout=15)
        assert process.exitcode == 0
        assert result.get(timeout=2) == "busy"
    finally:
        owner.release()


class _Download:
    suggested_filename = "invalid:name?.zip"
    url = "https://vendor.invalid/file"

    def save_as(self, destination: str) -> None:
        Path(destination).write_bytes(b"real-cad-bytes")


class _EmptyDownload(_Download):
    def save_as(self, destination: str) -> None:
        Path(destination).write_bytes(b"")


class _EventPage:
    def __init__(self):
        self.handlers: list = []
        self.closed = False

    def on(self, event: str, handler) -> None:
        assert event == "download"
        self.handlers.append(handler)

    def close(self) -> None:
        self.closed = True


class _PageContext:
    def __init__(self):
        self.pages: list[_EventPage] = []

    def new_page(self) -> _EventPage:
        page = _EventPage()
        self.pages.append(page)
        return page


def _provider_hud_spec() -> ProviderHudSpec:
    return ProviderHudSpec(
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=(
            "KiCad symbol (.kicad_sym)",
            "KiCad footprint (.kicad_mod)",
            "3D model (.step)",
        ),
    )


def test_download_is_saved_before_it_is_reported_and_uses_a_windows_safe_name(tmp_path):
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path)

    browser._on_download(_Download())

    assert len(browser.captured) == 1
    captured = browser.captured[0]
    assert captured.path.parent == tmp_path
    assert captured.path.name == "invalid_name_.zip"
    assert captured.path.read_bytes() == b"real-cad-bytes"
    assert captured.suggested_name == _Download.suggested_filename


def test_empty_download_is_removed_and_never_reported(tmp_path):
    from stockroom.store.machine_config import config_dir

    browser = PlaywrightCaptureBrowser(download_dir=tmp_path)

    with pytest.raises(CaptureBrowserError, match="missing or empty"):
        browser._on_download(_EmptyDownload())

    assert browser.captured == []
    # No download artifact survives. The suite-wide config isolation puts the capture trace's own
    # directory under the same tmp root, and that is not a leftover download.
    assert [entry for entry in tmp_path.iterdir() if entry != config_dir()] == []


def test_download_callback_failure_is_reported_to_the_owning_wait(tmp_path):
    class EventPage:
        def on(self, event: str, handler) -> None:
            assert event == "download"
            self.handler = handler

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("a known download failure must not wait for the timeout")

    page = EventPage()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path)
    browser._wire_downloads(page)

    page.handler(_EmptyDownload())

    assert len(browser.download_errors) == 1
    assert isinstance(browser.download_errors[0], CaptureBrowserError)
    assert "missing or empty" in str(browser.download_errors[0])
    assert browser.captured == []


def test_bound_broker_callback_failure_is_reported_without_waiting_for_timeout(tmp_path):
    class EventPage(_EventPage):
        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("a broker save failure must not wait for the timeout")

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Exact Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    context = _PageContext()
    context.new_page = EventPage
    browser._context = context

    with browser.task_page(broker) as page:
        page.handlers[0](_EmptyDownload())
        assert len(browser.download_errors) == 1
        assert "browser download failed" in str(browser.download_errors[0])
        assert browser.captured == []


def test_one_page_is_wired_once_even_when_context_and_session_both_observe_it(tmp_path):
    class EventPage:
        def __init__(self):
            self.handlers: list = []

        def on(self, event: str, handler) -> None:
            assert event == "download"
            self.handlers.append(handler)

    page = EventPage()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path)

    browser._wire_downloads(page)
    browser._wire_downloads(page)

    assert len(page.handlers) == 1
    page.handlers[0](_Download())
    assert len(browser.captured) == 1


def test_one_permanent_handler_routes_one_physical_download_to_the_bound_task(tmp_path):
    class CountedDownload(_Download):
        def __init__(self):
            self.calls = 0

        def save_as(self, destination: str) -> None:
            self.calls += 1
            super().save_as(destination)

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(
        DownloadTask(
            task_id="part-a",
            manufacturer_key="Exact Manufacturer",
            mpn_canonical="MPN-A",
            staging_root=staging,
        )
    )
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = _PageContext()
    download = CountedDownload()

    with browser.task_page(broker) as page:
        page.handlers[0](download)

    assert page.closed is True
    assert len(page.handlers) == 1
    assert download.calls == 1
    assert len(browser.captured) == 1
    assert len(broker.receipts) == 1
    assert browser.captured[0].path == broker.receipts[0].path
    assert broker.receipts[0].path.parent == staging / "part-a"


def test_task_page_reuses_initial_blank_page_and_closes_its_popups(tmp_path):
    class Popup(_EventPage):
        def __init__(self, parent):
            super().__init__()
            self._parent = parent

        def opener(self):
            return self._parent

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    initial = _EventPage()
    context = _PageContext()
    context.pages.append(initial)
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = context

    with browser.task_page(broker) as page:
        popup = Popup(page)
        context.pages.append(popup)
        assert page is initial

    # The claimed page is the context's first page, which is exactly what the session yields
    # and holds for its whole lifetime. Closing a page the task did not open ends the session's
    # own window, so later routes lose the surface they navigate. Popups the task spawned are
    # still its own and must close with it.
    assert initial.closed is False
    assert popup.closed is True
    assert browser._page_brokers == []
    assert browser._wired_pages == []


def test_duplicate_browser_event_is_reported_once(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Exact Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = _PageContext()

    with browser.task_page(broker) as page:
        browser._on_download(_Download(), page=page)
        browser._on_download(_Download(), page=page)

    assert len(broker.receipts) == 1
    assert len(browser.captured) == 1
    assert browser.captured[0].path == broker.receipts[0].path


def test_late_first_task_event_cannot_be_filed_under_the_second_task(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    first = DownloadBroker(DownloadTask("part-a", "Manufacturer A", "MPN-A", staging))
    second = DownloadBroker(DownloadTask("part-b", "Manufacturer B", "MPN-B", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = _PageContext()

    with browser.task_page(first) as first_page:
        with browser.task_page(second) as second_page:
            # The first provider finishes late while the second task page already exists.
            first_page.handlers[0](_Download())
            second_page.handlers[0](_Download())

    assert first.receipts[0].path.parent == staging / "part-a"
    assert second.receipts[0].path.parent == staging / "part-b"
    assert first.receipts[0].mpn_canonical == "MPN-A"
    assert second.receipts[0].mpn_canonical == "MPN-B"
    assert first.receipts[0].path.read_bytes() == second.receipts[0].path.read_bytes()


@pytest.mark.timeout(20)
def test_real_one_click_multi_download_does_not_deadlock(tmp_path):
    from stockroom.capture.browser import chromium_unavailable_reason

    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path == "/":
                body = (
                    b"<button id='go' onclick=\"for(const x of "
                    b"['symbol.kicad_sym','footprint.kicad_mod','model.step'])"
                    b"{const a=document.createElement('a');a.href='/file/'+x;"
                    b'a.download=x;document.body.appendChild(a);a.click();a.remove();}">'
                    b"Download all</button>"
                )
                content_type = "text/html"
                filename = ""
            else:
                filename = self.path.rsplit("/", 1)[-1]
                body = f"payload:{filename}".encode()
                content_type = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile",
        provider_key="multi-download-probe",
        headless=True,
        engine="chromium",
    )
    try:
        with browser.session() as page:
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.locator("#go").click()
            for _ in range(100):
                if len(browser.captured) == 3:
                    break
                page.wait_for_timeout(50)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert sorted(item.path.name for item in browser.captured) == [
        "footprint.kicad_mod",
        "model.step",
        "symbol.kicad_sym",
    ]
    assert {item.path.name: item.path.read_text() for item in browser.captured} == {
        "symbol.kicad_sym": "payload:symbol.kicad_sym",
        "footprint.kicad_mod": "payload:footprint.kicad_mod",
        "model.step": "payload:model.step",
    }


def test_task_page_teardown_survives_an_unreadable_opener(tmp_path):
    """A page whose opener cannot be read must not abort task teardown.

    The ownership walk runs inside the contextmanager's finally block. An exception there
    replaces any in-flight error and returns before the close loop, leaking every window and
    leaving stale broker bindings that route the next task's downloads to this task.
    """

    class Hostile(_EventPage):
        def opener(self):
            raise RuntimeError("target page, context or browser has been closed")

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    context = _PageContext()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = context

    with browser.task_page(broker) as page:
        context.pages.append(Hostile())

    assert page.closed is True
    assert browser._page_brokers == []
    assert browser._wired_pages == []


# --- the person-driven provider surface, observed and never driven ------------------------------


def _native_event(
    sequence: int,
    *,
    operation_id: str = "operation-1",
    phase: str = "terminal",
    state: str = "completed",
    path: Path | None = None,
    name: str = "Part.zip",
    uri: str = "https://provider.example.test/download",
) -> SimpleNamespace:
    """One journal entry shaped exactly like ``ProviderDownloadEvent``."""

    return SimpleNamespace(
        sequence=sequence,
        operation_id=operation_id,
        phase=phase,
        state=state,
        result_file_path=str(path or ""),
        suggested_file_name=name,
        uri=uri,
    )


class _NativeSurface:
    """A leased provider surface: commands in, journal entries out, no page and no driver."""

    def __init__(self, script=()) -> None:
        self.calls: list[str] = []
        self.url = "https://provider.example.test/part"
        self.document: dict[str, object] = {}
        # Each poll returns the next scripted batch, then keeps returning nothing.
        self.script = list(script)
        self.redirect_to = ""
        self.retained = False

    def show(self) -> None:
        self.calls.append("show")

    def hide(self) -> None:
        self.calls.append("hide")

    def navigate(self, url: str) -> None:
        self.calls.append("navigate:" + url)
        self.url = self.redirect_to or url

    def current_url(self) -> str:
        return self.url

    def security_state(self) -> dict[str, object]:
        return dict(self.document)

    def retain(self) -> None:
        self.retained = True

    def download_events(self, *, after_sequence: int = 0):
        batch = self.script.pop(0) if self.script else ()
        return tuple(event for event in batch if event.sequence > after_sequence)


def _cad_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Part.kicad_sym", "symbol")
        archive.writestr("Part.pretty/Part.kicad_mod", "footprint")
        archive.writestr("Part.step", "model")
    return path


def _surface_capture(tmp_path, surface) -> ProviderSurfaceCapture:
    return ProviderSurfaceCapture(
        download_dir=tmp_path / "Downloads",
        provider_key="ultralibrarian",
        native_surface=surface,
    )


def _surface_broker(tmp_path) -> DownloadBroker:
    staging = tmp_path / "Staging"
    staging.mkdir(exist_ok=True)
    return DownloadBroker(
        DownloadTask(
            task_id="part-a",
            manufacturer_key="Exact Manufacturer",
            mpn_canonical="MPN-A/7",
            staging_root=staging,
            surface_key="ultralibrarian",
            evidence_provider_key="ultralibrarian",
        )
    )


def test_a_native_download_reaches_the_exact_broker_with_no_driver_attached(tmp_path):
    landed = _cad_zip(tmp_path / "Part.zip")
    surface = _NativeSurface([(), (_native_event(1, path=landed),)])
    capture = _surface_capture(tmp_path, surface)
    broker = _surface_broker(tmp_path)

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        broker,
        hud=_provider_hud_spec(),
        poll_interval_s=0.01,
        settle_seconds=0.01,
        auto_finish_seconds=0.01,
        timeout_s=5.0,
    )

    assert result.status == "completed"
    assert [receipt.transport for receipt in result.files] == ["webview2-native"]
    assert result.files[0].path.is_file()
    # The surface was shown and navigated. Nothing else was ever asked of it.
    assert surface.calls == ["show", "navigate:https://www.ultralibrarian.com/part"]
    # The host's own copy is removed once the bytes are staged under the task.
    assert not landed.exists()


def test_a_native_download_that_begins_without_a_task_binding_is_refused(tmp_path):
    landed = _cad_zip(tmp_path / "Part.zip")
    surface = _NativeSurface()
    capture = _surface_capture(tmp_path, surface)

    # No capture is active, so no generation owns this operation and nothing may claim its bytes.
    surface.script = [(_native_event(1, path=landed),)]
    capture._poll_native_surface_downloads()

    assert [str(error) for error in capture.download_errors] == [
        "the native download began without one exact Stockroom task binding"
    ]


def test_each_task_keeps_its_own_receipts_when_two_routes_run_in_sequence(tmp_path):
    first_file = _cad_zip(tmp_path / "First.zip")
    second_file = _cad_zip(tmp_path / "Second.zip")
    surface = _NativeSurface([(), (_native_event(1, path=first_file),)])
    capture = _surface_capture(tmp_path, surface)
    first = _surface_broker(tmp_path)

    capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        first,
        hud=_provider_hud_spec(),
        poll_interval_s=0.01,
        settle_seconds=0.01,
        auto_finish_seconds=0.01,
        timeout_s=5.0,
    )

    second_staging = tmp_path / "Staging B"
    second_staging.mkdir()
    second = DownloadBroker(
        DownloadTask(
            task_id="part-b",
            manufacturer_key="Exact Manufacturer",
            mpn_canonical="MPN-B/2",
            staging_root=second_staging,
            surface_key="ultralibrarian",
            evidence_provider_key="ultralibrarian",
        )
    )
    surface.script = [
        (),
        (_native_event(2, operation_id="operation-2", path=second_file),),
    ]

    second_spec = ProviderHudSpec(
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Exact Manufacturer",
        mpn="MPN-B/2",
        required_file_labels=(
            "KiCad symbol (.kicad_sym)",
            "KiCad footprint (.kicad_mod)",
            "3D model (.step)",
        ),
    )

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        second,
        hud=second_spec,
        poll_interval_s=0.01,
        settle_seconds=0.01,
        auto_finish_seconds=0.01,
        timeout_s=5.0,
    )

    assert result.status == "completed"
    # Every receipt stays inside the staging root of the task that was open when it arrived.
    assert len(first.receipts) == 1
    assert len(second.receipts) == 1
    assert first.receipts[0].path.is_relative_to(tmp_path / "Staging")
    assert second.receipts[0].path.is_relative_to(second_staging)


def test_a_terminal_provider_error_page_advances_to_the_next_author_route(tmp_path):
    surface = _NativeSurface()
    surface.document = {"provider_error": True}
    capture = _surface_capture(tmp_path, surface)
    broker = _surface_broker(tmp_path)

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        broker,
        hud=_provider_hud_spec(),
        poll_interval_s=0.01,
        settle_seconds=0.01,
        timeout_s=5.0,
    )

    assert result.status == "try_another"
    assert result.files == ()


def test_an_account_verification_gate_returns_the_exact_final_url(tmp_path):
    surface = _NativeSurface()
    surface.document = {"account_verification": True}
    # The provider redirects the person's own navigation onto its verification page.
    surface.redirect_to = "https://www.snapmagic.com/profiles/verify"
    capture = _surface_capture(tmp_path, surface)
    broker = _surface_broker(tmp_path)

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        broker,
        hud=_provider_hud_spec(),
        poll_interval_s=0.01,
        settle_seconds=0.01,
        timeout_s=5.0,
    )

    # `guided.py` turns this exact URL into a resumable blocked verdict rather than a failure.
    assert result.status == "timed_out"
    assert result.final_url == "https://www.snapmagic.com/profiles/verify"


def test_the_persons_finish_route_ends_the_capture_and_keeps_what_landed(tmp_path):
    landed = _cad_zip(tmp_path / "Part.zip")
    surface = _NativeSurface([(_native_event(1, path=landed),)])
    capture = _surface_capture(tmp_path, surface)
    broker = _surface_broker(tmp_path)
    finishes = iter([False, True, True, True, True])

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        broker,
        hud=_provider_hud_spec(),
        should_finish=lambda: next(finishes, True),
        poll_interval_s=0.01,
        settle_seconds=0.01,
        auto_finish_seconds=30.0,
        auto_finish_idle_seconds=600.0,
        timeout_s=5.0,
    )

    assert result.status == "completed"
    assert len(result.files) == 1


def test_a_bounded_timeout_returns_the_files_received_so_far(tmp_path):
    landed = _cad_zip(tmp_path / "Part.zip")
    # The archive carries no Altium library, so the completion rule can never be satisfied.
    surface = _NativeSurface([(), (_native_event(1, path=landed),)])
    capture = _surface_capture(tmp_path, surface)
    broker = _surface_broker(tmp_path)
    spec = ProviderHudSpec(
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=("Altium symbol (.SchLib)",),
        required_formats=("altium_symbol",),
    )

    result = capture.capture_user_downloads(
        "https://www.ultralibrarian.com/part",
        broker,
        hud=spec,
        poll_interval_s=0.01,
        settle_seconds=0.01,
        auto_finish_seconds=0.01,
        auto_finish_idle_seconds=0.0,
        timeout_s=0.3,
    )

    assert result.status == "timed_out"
    assert len(result.files) == 1


def test_a_route_identity_that_is_not_its_bound_task_is_refused(tmp_path):
    capture = _surface_capture(tmp_path, _NativeSurface())
    broker = _surface_broker(tmp_path)
    foreign = ProviderHudSpec(
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Other Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=("KiCad symbol (.kicad_sym)",),
    )

    with pytest.raises(CaptureBrowserError, match="must exactly match its bound download task"):
        capture.capture_user_downloads(
            "https://www.ultralibrarian.com/part",
            broker,
            hud=foreign,
        )


def test_an_incomplete_route_can_retain_the_visible_provider_document(tmp_path):
    surface = _NativeSurface()
    capture = _surface_capture(tmp_path, surface)

    assert capture.retain_provider_surface() is True
    assert surface.retained is True
