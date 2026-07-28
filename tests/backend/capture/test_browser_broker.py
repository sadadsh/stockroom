"""Windows production browser policy and provider-profile ownership."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.capture.browser import (
    CaptureBrowserError,
    PlaywrightCaptureBrowser,
    ProviderProfileLock,
    SharedPlaywrightRuntime,
    _allow_automatic_downloads,
    _browser_candidates,
    provider_profile_dir,
)
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.guided import _wait_for_capture
from stockroom.capture.runner import (
    _capture_downloads,
    _capture_evidence_root,
    _capture_profile,
    capture_state_root,
    run_guided_capture,
)


class _Context:
    pass


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
    assert "camoufox" not in [candidate.channel for candidate in _browser_candidates("windows")]


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


def test_the_production_runner_defaults_to_stockroom_managed_chromium():
    parameter = inspect.signature(run_guided_capture).parameters["engine"]
    assert parameter.default == "chromium"


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


def test_provider_profiles_and_downloads_are_isolated(monkeypatch, tmp_path):
    machine_root = tmp_path / "Machine Capture"
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(machine_root))
    ctx = SimpleNamespace(
        profile=SimpleNamespace(library=SimpleNamespace(root=tmp_path / "Library"))
    )

    ultra_profile = _capture_profile(ctx, "ultralibrarian")
    snap_profile = _capture_profile(ctx, "snapmagic")
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
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path)

    with pytest.raises(CaptureBrowserError, match="missing or empty"):
        browser._on_download(_EmptyDownload())

    assert browser.captured == []
    assert list(tmp_path.iterdir()) == []


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
    with pytest.raises(CaptureBrowserError, match="missing or empty"):
        _wait_for_capture(
            browser,
            page,
            before=0,
            timeout_s=120,
            errors_before=0,
        )


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
        with pytest.raises(CaptureBrowserError, match="browser download failed"):
            _wait_for_capture(
                browser,
                page,
                before=0,
                timeout_s=120,
                errors_before=0,
            )


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
