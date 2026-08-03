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
    ProviderControlHint,
    ProviderHudSpec,
    ProviderPageTerminalError,
    ProviderProfileLock,
    SharedPlaywrightRuntime,
    _allow_automatic_downloads,
    _browser_candidates,
    _completed_provider_formats,
    _ProviderHudState,
    _ReconnectablePage,
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
    assert len(context.init_scripts) == 1
    assert "RTCPeerConnection" in context.init_scripts[0]
    assert "webkitRTCPeerConnection" in context.init_scripts[0]
    preferences = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert preferences["profile"]["default_content_setting_values"]["automatic_downloads"] == 1


def test_embedded_webview_connection_reuses_its_existing_context(tmp_path):
    context = _Context()
    cdp_calls = []

    class BrowserSession:
        def __init__(self):
            self.handlers = {}

        def on(self, event, handler):
            self.handlers[event] = handler

        def send(self, method, params):
            cdp_calls.append((method, params))

        def detach(self):
            cdp_calls.append(("detach", None))

    browser_connection = SimpleNamespace(
        contexts=[context],
        new_browser_cdp_session=lambda: BrowserSession(),
    )

    class Chromium:
        def __init__(self):
            self.calls = []

        def connect_over_cdp(self, endpoint, **options):
            self.calls.append((endpoint, options))
            return browser_connection

    chromium = Chromium()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "downloads",
        provider_key="snapmagic",
        cdp_endpoint="http://127.0.0.1:43127",
        # A native surface may suppress WebView2's Save-As dialog, but it must never replace the
        # browser-domain download owner. This is the exact source-host boundary that lost a real
        # Ultra Librarian download while the provider page reported success.
        native_surface=SimpleNamespace(snapshot_downloads=lambda **_options: ()),
    )

    opened_context, opened_browser = browser._launch_playwright(SimpleNamespace(chromium=chromium))

    assert opened_context is context
    assert opened_browser is browser_connection
    assert chromium.calls == [("http://127.0.0.1:43127", {"timeout": 20_000})]
    assert browser.launched_browser == "Stockroom Embedded WebView2"
    assert context.init_scripts == []
    assert cdp_calls == [
        (
            "Browser.setDownloadBehavior",
            {
                "behavior": "allowAndName",
                "downloadPath": str((tmp_path / "downloads").resolve()),
                "eventsEnabled": True,
            },
        ),
    ]


def test_browser_domain_download_is_bound_to_the_active_task_when_page_event_is_late(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads")
    browser._embedded_download_session = object()
    browser._embedded_download_generation = 1
    browser._embedded_active_generation = 1
    browser._page_brokers.append((object(), broker))

    browser._on_embedded_download_will_begin(
        {
            "guid": "2c25f6ba-77d4-4d84-99f5-bd8884d62be9",
            "suggestedFilename": "Exact Part.step",
            "url": "https://provider.example.test/Exact%20Part.step",
        }
    )
    guid_path = browser.download_dir / "2c25f6ba-77d4-4d84-99f5-bd8884d62be9"
    guid_path.write_text("ISO-10303-21;", encoding="utf-8")
    browser._on_embedded_download_progress(
        {
            "guid": "2c25f6ba-77d4-4d84-99f5-bd8884d62be9",
            "state": "completed",
        }
    )

    pending, finalized = browser._drain_native_downloads(finalize_if_idle=True)

    assert (pending, finalized) == (0, True)
    assert [receipt.suggested_name for receipt in broker.receipts] == ["Exact Part.step"]
    assert broker.receipts[0].path.read_text(encoding="utf-8") == "ISO-10303-21;"
    assert not guid_path.exists()


def test_native_host_download_survives_detached_cdp_and_reaches_exact_broker(tmp_path):
    source = tmp_path / "native-download.step"
    source.write_text("ISO-10303-21;", encoding="utf-8")
    events = (
        SimpleNamespace(
            sequence=1,
            operation_id="native-operation",
            phase="started",
            state="in_progress",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name="Exact Part.step",
            result_file_path=str(source),
        ),
        SimpleNamespace(
            sequence=2,
            operation_id="native-operation",
            phase="terminal",
            state="completed",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name="Exact Part.step",
            result_file_path=str(source),
        ),
    )

    class Surface:
        def download_events(self, *, after_sequence=0):
            return tuple(item for item in events if item.sequence > after_sequence)

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        native_surface=Surface(),
    )
    browser._embedded_active_generation = 1
    browser._page_brokers.append((object(), broker))

    pending, finalized = browser._drain_native_downloads(finalize_if_idle=True)

    assert (pending, finalized) == (0, True)
    assert [receipt.suggested_name for receipt in broker.receipts] == ["Exact Part.step"]
    assert broker.receipts[0].path.read_text(encoding="utf-8") == "ISO-10303-21;"
    assert not source.exists()


def test_native_host_and_browser_domain_events_materialize_one_receipt(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    guid = "2c25f6ba-77d4-4d84-99f5-bd8884d62be9"
    download_root = tmp_path / "Downloads"
    source = download_root / guid
    events = (
        SimpleNamespace(
            sequence=1,
            operation_id="native-operation",
            phase="started",
            state="in_progress",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name=guid,
            result_file_path=str(source),
        ),
        SimpleNamespace(
            sequence=2,
            operation_id="native-operation",
            phase="terminal",
            state="completed",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name=guid,
            result_file_path=str(source),
        ),
    )

    class Surface:
        def download_events(self, *, after_sequence=0):
            return tuple(item for item in events if item.sequence > after_sequence)

    browser = PlaywrightCaptureBrowser(
        download_dir=download_root,
        native_surface=Surface(),
    )
    browser._embedded_active_generation = 1
    browser._page_brokers.append((object(), broker))
    browser._on_embedded_download_will_begin(
        {
            "guid": guid,
            "suggestedFilename": "Exact Part.step",
            "url": "https://provider.example.test/Exact.step",
        }
    )
    source.write_text("ISO-10303-21;", encoding="utf-8")

    pending, finalized = browser._drain_native_downloads(finalize_if_idle=True)

    assert (pending, finalized) == (0, True)
    assert [receipt.suggested_name for receipt in broker.receipts] == ["Exact Part.step"]


def test_same_url_native_events_join_their_exact_browser_guids(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    download_root = tmp_path / "Downloads"
    shared_url = "https://provider.example.test/export"
    guids = [f"00000000-0000-0000-0000-00000000000{index}" for index in range(1, 4)]
    events = []
    for index, guid in enumerate(guids, start=1):
        source = download_root / guid
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"payload-{index}", encoding="utf-8")
        events.extend(
            (
                SimpleNamespace(
                    sequence=index * 2 - 1,
                    operation_id=f"native-{index}",
                    phase="started",
                    state="in_progress",
                    uri=shared_url,
                    suggested_file_name=f"Part-{index}.step",
                    result_file_path=str(source),
                ),
                SimpleNamespace(
                    sequence=index * 2,
                    operation_id=f"native-{index}",
                    phase="terminal",
                    state="completed",
                    uri=shared_url,
                    suggested_file_name=f"Part-{index}.step",
                    result_file_path=str(source),
                ),
            )
        )

    class Surface:
        def download_events(self, *, after_sequence=0):
            return tuple(item for item in events if item.sequence > after_sequence)

    browser = PlaywrightCaptureBrowser(download_dir=download_root, native_surface=Surface())
    browser._embedded_active_generation = 1
    browser._page_brokers.append((object(), broker))
    for index, guid in enumerate(guids, start=1):
        browser._on_embedded_download_will_begin(
            {
                "guid": guid,
                "suggestedFilename": f"Part-{index}.step",
                "url": shared_url,
            }
        )

    pending, finalized = browser._drain_native_downloads(finalize_if_idle=True)

    assert (pending, finalized) == (0, True)
    assert [receipt.suggested_name for receipt in broker.receipts] == [
        "Part-1.step",
        "Part-2.step",
        "Part-3.step",
    ]
    assert {receipt.path.read_text(encoding="utf-8") for receipt in broker.receipts} == {
        "payload-1",
        "payload-2",
        "payload-3",
    }


def test_browser_domain_download_keeps_its_original_task_across_page_rebinding(tmp_path):
    staging_a = tmp_path / "A"
    staging_b = tmp_path / "B"
    staging_a.mkdir()
    staging_b.mkdir()
    broker_a = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging_a))
    broker_b = DownloadBroker(DownloadTask("part-b", "Manufacturer", "MPN-B", staging_b))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads")
    browser._embedded_download_session = object()
    browser._embedded_active_generation = 1
    browser._page_brokers[:] = [(object(), broker_a)]
    guid = "cd030070-c05a-4cc3-b7f4-451bd9b5356a"
    browser._on_embedded_download_will_begin(
        {
            "guid": guid,
            "suggestedFilename": "Part A.step",
            "url": "https://provider.example.test/Part-A.step",
        }
    )

    browser._embedded_active_generation = 2
    browser._page_brokers[:] = [(object(), broker_b)]
    (browser.download_dir / guid).write_text("ISO-10303-21;", encoding="utf-8")
    browser._on_embedded_download_progress({"guid": guid, "state": "completed"})

    assert [receipt.suggested_name for receipt in broker_a.receipts] == ["Part A.step"]
    assert broker_b.receipts == ()


def test_cancel_waits_for_a_just_started_browser_domain_download(tmp_path):
    page = _HudPage()
    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = _provider_hud_spec()
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads")
    browser._context = SimpleNamespace(new_page=lambda: page)
    browser._embedded_download_session = object()
    page.on_goto = lambda: page.invoke_hud_action("cancel")

    def complete_after_cancel(wait_number: int) -> None:
        if wait_number != 1:
            return
        guid = "d41ba2ca-acde-4f15-bb2e-b3586916df24"
        browser._on_embedded_download_will_begin(
            {
                "guid": guid,
                "suggestedFilename": "Late.step",
                "url": "https://provider.example.test/Late.step",
            }
        )
        (browser.download_dir / guid).write_text("ISO-10303-21;", encoding="utf-8")
        browser._on_embedded_download_progress({"guid": guid, "state": "completed"})

    page.on_wait = complete_after_cancel
    result = browser.capture_user_downloads(
        "https://provider.example.test/part",
        broker,
        hud=spec,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
    )

    assert result.status == "cancelled"
    assert [receipt.suggested_name for receipt in result.files] == ["Late.step"]


def test_explicit_ordinary_control_operator_runs_after_embedded_navigation(tmp_path):
    events: list[str] = []

    class Page(_EventPage):
        url = "about:blank"

        def goto(self, url: str, **_options) -> None:
            self.url = url
            events.append(f"navigate:{url}")

        def is_closed(self) -> bool:
            return False

    page = Page()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "downloads",
        provider_key="digikey",
    )
    browser._context = SimpleNamespace(new_page=lambda: page)
    staging = tmp_path / "staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))

    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        operate_controls=lambda active_page: events.append(f"operate:{active_page.url}"),
        should_finish=lambda: True,
        settle_seconds=0,
        timeout_s=1,
    )

    assert result.status == "completed"
    assert events == [
        "navigate:https://vendor.example.test/part",
        "operate:https://vendor.example.test/part",
    ]


def test_ordinary_control_operator_resumes_after_an_ordinary_login_navigation(tmp_path):
    operator_runs = 0

    class Page(_EventPage):
        url = "about:blank"

        def goto(self, url: str, **_options) -> None:
            self.url = url

        def wait_for_timeout(self, milliseconds: int) -> None:
            time.sleep(milliseconds / 1000)

        def is_closed(self) -> bool:
            return False

    page = Page()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "downloads",
        provider_key="digikey",
    )
    browser._context = SimpleNamespace(new_page=lambda: page)
    staging = tmp_path / "staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))

    def operate(active_page) -> None:
        nonlocal operator_runs
        operator_runs += 1
        if operator_runs == 1:
            active_page.url = "https://provider.example.test/sign-in"
        else:
            active_page.url = "https://provider.example.test/part"

    result = browser.capture_user_downloads(
        "https://provider.example.test/part",
        broker,
        operate_controls=operate,
        should_finish=lambda: operator_runs >= 2,
        settle_seconds=0,
        poll_interval_s=0.01,
        timeout_s=2,
    )

    assert result.status == "completed"
    assert operator_runs == 2
    assert result.final_url == "https://provider.example.test/part"


@pytest.mark.parametrize("standalone_engine", ["camoufox", "cloak"])
def test_embedded_webview_overrides_every_standalone_provider_engine(
    monkeypatch,
    tmp_path,
    standalone_engine,
):
    events: list[str] = []

    class Runtime:
        @staticmethod
        def get():
            events.append("runtime")
            return object()

    @contextmanager
    def embedded_session(_runtime):
        events.append("embedded")
        yield "embedded-page"

    @contextmanager
    def forbidden_standalone_session():
        pytest.fail("a standalone provider browser was launched beside the embedded WebView")
        yield  # pragma: no cover

    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "downloads",
        engine=standalone_engine,
        provider_key="digikey",
        playwright_runtime=Runtime(),
        cdp_endpoint="http://127.0.0.1:43127",
    )
    monkeypatch.setattr(browser, "_playwright_session", embedded_session)
    monkeypatch.setattr(browser, "_camoufox_session", forbidden_standalone_session)
    monkeypatch.setattr(browser, "_cloak_session", forbidden_standalone_session)

    with browser.session() as page:
        assert page == "embedded-page"

    assert events == ["runtime", "embedded"]


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


def test_the_production_runner_defers_to_each_stockroom_managed_provider_engine():
    parameter = inspect.signature(run_guided_capture).parameters["engine"]
    assert parameter.default == ""


@pytest.mark.parametrize("persistent", [False, True])
def test_each_camoufox_context_disables_webrtc_before_opening_a_page(
    monkeypatch,
    tmp_path,
    persistent,
):
    context_events: list[tuple[str, object]] = []

    class Context:
        def __init__(self):
            self.pages = []

        def add_init_script(self, script: str) -> None:
            context_events.append(("init_script", script))

        def on(self, event: str, _handler) -> None:
            context_events.append(("on", event))

        def new_page(self):
            context_events.append(("new_page", None))
            return _EventPage()

        def close(self) -> None:
            context_events.append(("close", None))

    context = Context()

    class Browser:
        def new_context(self, **options):
            context_events.append(("new_context", options))
            return context

    class Handle:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return context if self.options.get("persistent_context") else Browser()

        def __exit__(self, *_args):
            return False

    camoufox_module = ModuleType("camoufox")
    camoufox_module.DefaultAddons = SimpleNamespace(UBO=object())
    sync_api_module = ModuleType("camoufox.sync_api")
    sync_api_module.Camoufox = lambda **options: Handle(options)
    monkeypatch.setitem(sys.modules, "camoufox", camoufox_module)
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", sync_api_module)

    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile" if persistent else None,
        provider_key="camoufox-probe" if persistent else None,
        engine="camoufox",
        headless=True,
    )

    with browser._camoufox_session():
        pass

    init_index = next(
        index for index, event in enumerate(context_events) if event[0] == "init_script"
    )
    page_index = next(index for index, event in enumerate(context_events) if event[0] == "new_page")
    script = context_events[init_index][1]
    assert init_index < page_index
    assert isinstance(script, str)
    assert "RTCPeerConnection" in script
    assert "webkitRTCPeerConnection" in script


@pytest.mark.parametrize("persistent", [False, True])
def test_each_cloak_context_is_pinned_and_disables_webrtc_before_opening_a_page(
    monkeypatch,
    tmp_path,
    persistent,
):
    context_events: list[tuple[str, object]] = []
    launch_options: list[tuple[str, dict]] = []

    class Context:
        def __init__(self):
            self.pages = []

        def add_init_script(self, script: str) -> None:
            context_events.append(("init_script", script))

        def on(self, event: str, _handler) -> None:
            context_events.append(("on", event))

        def new_page(self):
            context_events.append(("new_page", None))
            return _EventPage()

        def close(self) -> None:
            context_events.append(("context_close", None))

    context = Context()

    class Browser:
        def new_context(self, **options):
            context_events.append(("new_context", options))
            return context

        def close(self) -> None:
            context_events.append(("browser_close", None))

    def launch(**options):
        launch_options.append(("ephemeral", options))
        return Browser()

    def launch_persistent_context(profile, **options):
        launch_options.append(("persistent", {"profile": profile, **options}))
        return context

    cloak_module = ModuleType("cloakbrowser")
    cloak_module.launch = launch
    cloak_module.launch_persistent_context = launch_persistent_context
    monkeypatch.setitem(sys.modules, "cloakbrowser", cloak_module)

    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile" if persistent else None,
        provider_key="cloak-probe" if persistent else None,
        engine="cloak",
        headless=True,
    )

    with browser._cloak_session():
        pass

    kind, options = launch_options[0]
    assert kind == ("persistent" if persistent else "ephemeral")
    assert options["browser_version"] == "146.0.7680.177.5"
    assert options["headless"] is True
    assert options["humanize"] is True
    assert len(options["args"]) == 1
    assert options["args"][0].startswith("--fingerprint=")
    init_index = next(
        index for index, event in enumerate(context_events) if event[0] == "init_script"
    )
    page_index = next(index for index, event in enumerate(context_events) if event[0] == "new_page")
    script = context_events[init_index][1]
    assert init_index < page_index
    assert isinstance(script, str)
    assert "RTCPeerConnection" in script
    assert "webkitRTCPeerConnection" in script


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


class _HudPage(_EventPage):
    """Deterministic Page double exposing only Stockroom's injection/update seams."""

    url = "about:blank"

    def __init__(self):
        super().__init__()
        self.events: list[str] = []
        self.init_scripts: list[str] = []
        self.bindings: dict[str, object] = {}
        self.evaluations: list[tuple[str, object]] = []
        self.waits = 0
        self.on_goto = None
        self.on_wait = None

    def on(self, event: str, handler) -> None:
        self.events.append(f"on:{event}")
        super().on(event, handler)

    def expose_binding(self, name: str, callback) -> None:
        self.events.append("expose-binding")
        self.bindings[name] = callback

    def add_init_script(self, script: str) -> None:
        self.events.append("add-init-script")
        self.init_scripts.append(script)

    def evaluate(self, expression: str, arg=None) -> None:
        self.events.append("evaluate-stockroom")
        self.evaluations.append((expression, arg))

    def goto(self, url: str, **_options) -> None:
        self.events.append(f"goto:{url}")
        assert self.handlers, "download interception must be wired before navigation"
        assert self.bindings, "HUD actions must be bound before navigation"
        assert self.init_scripts, "HUD must survive provider navigation"
        self.url = url
        if self.on_goto is not None:
            self.on_goto()

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.events.append("wait")
        self.waits += 1
        if self.on_wait is not None:
            self.on_wait(self.waits)

    def is_closed(self) -> bool:
        return self.closed

    def _hud_payload(self) -> dict:
        assert self.evaluations
        return self.evaluations[0][1]

    def invoke_hud_action(self, action: str, *, token: str | None = None) -> bool:
        payload = self._hud_payload()
        callback = self.bindings[payload["actionBinding"]]
        return callback(
            SimpleNamespace(page=self),
            action,
            token if token is not None else payload["actionToken"],
        )

    def read_hud_state(self, *, token: str | None = None) -> dict:
        payload = self._hud_payload()
        callback = self.bindings[payload["stateBinding"]]
        return callback(
            SimpleNamespace(page=self),
            token if token is not None else payload["stateToken"],
        )


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


def _hud_capture(
    tmp_path,
    page: _HudPage,
    *,
    action: str | None = None,
    profile_dir: Path | None = None,
    provider_key: str | None = None,
    auto_finish_seconds: float = 2.0,
    auto_finish_idle_seconds: float = 25.0,
):
    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = _provider_hud_spec()
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        profile_dir=profile_dir,
        provider_key=provider_key,
    )
    browser._context = SimpleNamespace(new_page=lambda: page)
    if action is not None:
        page.on_goto = lambda: page.invoke_hud_action(action)
    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A%2F7",
        broker,
        hud=spec,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
        auto_finish_seconds=auto_finish_seconds,
        auto_finish_idle_seconds=auto_finish_idle_seconds,
    )
    return result, broker


def test_security_handoff_has_the_same_tabs_and_return_cancels_the_workflow(tmp_path):
    page = _HudPage()
    cancelled: list[bool] = []
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")

    def request_return(_waits: int) -> None:
        payload = page.evaluations[0][1]
        accepted = page.bindings[payload["actionBinding"]](
            SimpleNamespace(page=page),
            "cancel",
            payload["actionToken"],
        )
        assert accepted is True

    page.on_wait = request_return
    cleared = browser.wait_for_user_clearance(
        page,
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        message="Clear the visible provider security gate.",
        issue_detector=lambda: "security gate remains",
        cancel_workflow=lambda: cancelled.append(True),
        timeout_s=1,
        poll_interval_s=0.01,
    )

    bootstrap, payload = page.evaluations[0]
    assert cleared is False
    assert cancelled == [True]
    assert payload["actionBinding"] in page.bindings
    assert 'browserHost.setAttribute("aria-label", "Stockroom provider tabs")' in bootstrap
    assert 'stockroomTab.setAttribute("aria-label", "Return to Stockroom")' in bootstrap
    assert 'toggle.setAttribute("aria-expanded", collapsed ? "false" : "true")' in bootstrap
    assert "setCollapsed(true)" in bootstrap


def test_user_capture_hud_is_injected_before_navigation_and_reads_no_provider_content(
    tmp_path,
):
    page = _HudPage()

    result, _broker = _hud_capture(tmp_path, page, action="finish")

    assert result.status == "completed"
    goto_index = page.events.index("goto:https://vendor.example.test/search?query=MPN-A%2F7")
    assert page.events.index("on:download") < goto_index
    assert page.events.index("expose-binding") < goto_index
    assert page.events.index("add-init-script") < goto_index
    assert page.events.index("evaluate-stockroom") < goto_index
    assert len(page.init_scripts) == 1

    bootstrap, payload = page.evaluations[0]
    assert payload["providerLabel"] == "Exact Provider"
    assert payload["authorRoute"] == "Exact CAD Author"
    assert payload["manufacturer"] == "Exact Manufacturer"
    assert payload["mpn"] == "MPN-A/7"
    assert payload["automatedStep"] == "Listening for provider downloads."
    assert (
        payload["humanAction"]
        == "Start this part's download with every required format shown here."
    )
    assert payload["requiredFileLabels"] == [
        "KiCad symbol (.kicad_sym)",
        "KiCad footprint (.kicad_mod)",
        "3D model (.step)",
    ]
    assert payload["downloadCount"] == 0
    assert payload["sessionPersistent"] is False
    assert 'attachShadow({ mode: "closed" })' in bootstrap
    assert 'host.setAttribute("popover", "manual")' in bootstrap
    assert '"Author Route"' in bootstrap
    assert '"Automated Step"' in bootstrap
    assert '"Human Action"' in bootstrap
    assert "This assisted window never reads or submits " in bootstrap
    assert "credentials, CAPTCHA, 2FA, or passkeys." in bootstrap
    assert "color-scheme: light dark" in bootstrap
    assert "@media (prefers-color-scheme: dark)" in bootstrap
    assert "var(--sr-surface)" in bootstrap
    assert 'Consolas, "Cascadia Mono"' in bootstrap
    assert "border-radius: 3px" in bootstrap
    assert "prefers-reduced-motion" in bootstrap
    assert 'live.setAttribute("aria-live", "polite")' in bootstrap
    assert 'header.addEventListener("pointerdown"' in bootstrap
    assert 'move.addEventListener("keydown"' in bootstrap
    assert 'browserHost.setAttribute("aria-label", "Stockroom provider tabs")' in bootstrap
    assert 'stockroomTab.setAttribute("aria-label", "Return to Stockroom")' in bootstrap
    assert 'back.addEventListener("click", () => globalThis.history.back())' in bootstrap
    assert 'forward.addEventListener("click", () => globalThis.history.forward())' in bootstrap
    assert "downloads stay with this part" in bootstrap
    assert '"Resume Now"' in bootstrap
    assert "Stockroom will resume automatically after downloads settle." in bootstrap
    assert '"Use Another Provider"' in bootstrap
    assert '"Close Capture"' in bootstrap

    # The narrowed contract: the injected script may ask the document WHERE an element is, and
    # nothing else. Every primitive that would harvest page CONTENT - text, markup, attribute or
    # form values, credentials, cookies, storage - stays forbidden, and the fake page deliberately
    # has no locator/query APIs at all.
    provider_content_primitives = (
        "innerHTML",
        "outerHTML",
        "innerText",
        "getAttribute",
        "attributes",
        "document.forms",
        "document.cookie",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "navigator.credentials",
        "FormData",
        "fetch(",
        "XMLHttpRequest",
    )
    found = [value for value in provider_content_primitives if value in bootstrap]
    assert found == [], f"the injected HUD can harvest provider content: {found}"
    # Position-only DOM access is what the owner relaxed the contract for, and it is present.
    assert "getBoundingClientRect()" in bootstrap
    assert "document.querySelectorAll(" in bootstrap


def test_embedded_provider_blank_links_are_contained_before_the_hud_mounts(tmp_path):
    page = _HudPage()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        provider_key="digikey",
        cdp_endpoint="http://127.0.0.1:43127",
    )

    browser._bind_provider_hud(page, _ProviderHudState(_provider_hud_spec()))

    assert len(page.init_scripts) == 2
    containment = page.init_scripts[0]
    assert 'anchor.target.toLowerCase() !== "_blank"' in containment
    assert 'anchor.hasAttribute("download")' in containment
    assert '["http:", "https:"].includes(destination.protocol)' in containment
    assert "destination.username || destination.password" in containment
    assert "event.stopImmediatePropagation()" in containment
    assert "globalThis.location.assign(destination.href)" in containment
    assert page.evaluations[0] == (containment, None)
    assert page.evaluations[1][1]["providerLabel"] == "Exact Provider"


def test_digikey_hud_names_provider_isolated_session_memory_only_with_its_profile(tmp_path):
    page = _HudPage()

    result, _broker = _hud_capture(
        tmp_path,
        page,
        action="finish",
        profile_dir=tmp_path / "DigiKey Profile",
        provider_key="digikey",
    )

    assert result.status == "completed"
    bootstrap, payload = page.evaluations[0]
    assert payload["sessionPersistent"] is True
    assert '"Session Memory On"' in bootstrap
    assert "Provider-only browser profile keeps this session on this PC." in bootstrap
    assert "This assisted " in bootstrap
    assert "window never reads or stores passwords from the page." in bootstrap
    assert "DigiKey sign-in or " in bootstrap
    assert "consent returns only after session expiry or a new gate." in bootstrap

    other_browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Other Downloads",
        profile_dir=tmp_path / "Other Profile",
        provider_key="ultralibrarian",
    )
    assert other_browser.persistent_digikey_session is False


def test_user_capture_hud_receives_live_stockroom_download_count(tmp_path):
    class Download:
        suggested_filename = "symbol.kicad_sym"
        url = "https://vendor.example.test/files/symbol.kicad_sym"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"captured-symbol")

    page = _HudPage()

    def during_wait(wait_number: int) -> None:
        if wait_number == 1:
            page.handlers[0](Download())
        elif wait_number == 2:
            assert page.invoke_hud_action("finish") is True

    page.on_wait = during_wait
    result, broker = _hud_capture(tmp_path, page)

    assert result.status == "completed"
    assert len(broker.receipts) == 1
    assert broker.receipts[0].path.read_bytes() == b"captured-symbol"
    count_updates = [
        argument["downloadCount"]
        for _expression, argument in page.evaluations[1:]
        if isinstance(argument, dict) and "downloadCount" in argument
    ]
    assert 1 in count_updates


def test_stockroom_tab_hides_the_provider_without_ending_the_capture(tmp_path):
    binding_returned = threading.Event()
    hidden = threading.Event()

    class Surface:
        def __init__(self) -> None:
            self.events: list[str] = []

        def show(self) -> None:
            self.events.append("show")

        def hide(self) -> None:
            # A synchronous hide from the renderer binding deadlocks real WebView2. The binding
            # must acknowledge the tab click before the native surface command begins.
            assert binding_returned.wait(1)
            self.events.append("hide")
            hidden.set()

    page = _HudPage()
    surface = Surface()
    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = _provider_hud_spec()
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        native_surface=surface,
    )
    browser._context = SimpleNamespace(new_page=lambda: page)
    def return_to_stockroom() -> None:
        assert page.invoke_hud_action("hide") is True
        binding_returned.set()

    page.on_goto = return_to_stockroom

    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        hud=spec,
        timeout_s=0.05,
        poll_interval_s=0.01,
        settle_seconds=0,
    )

    assert result.status == "timed_out"
    assert hidden.wait(1)
    assert surface.events == ["show", "hide"]


def test_step_only_snapmagic_offer_finishes_after_other_formats_are_confirmed_absent(
    tmp_path,
):
    class Download:
        suggested_filename = "Part.step"
        url = "https://snapeda.com/files/Part.step"

        def save_as(self, destination: str) -> None:
            Path(destination).write_text("ISO-10303-21;", encoding="utf-8")

    page = _HudPage()
    operated = False

    def operate(_page):
        nonlocal operated
        if operated:
            return []
        operated = True
        page.handlers[0](Download())
        return [
            SimpleNamespace(selected=[], missed=["kicad"], submitted=False, blocked=False),
            SimpleNamespace(selected=["model"], missed=[], submitted=True, blocked=False),
            SimpleNamespace(selected=[], missed=["altium"], submitted=False, blocked=False),
        ]

    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = ProviderHudSpec(
        provider_label="SnapMagic",
        author_route="SnapMagic",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=("KiCad", "STEP", "Altium"),
        required_formats=("kicad", "model", "altium"),
    )
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        provider_key="snapmagic",
    )
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://www.snapeda.com/parts/MPN-A-7/Exact-Manufacturer/view-part/",
        broker,
        hud=spec,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
        auto_finish_seconds=0,
        operate_controls=operate,
    )

    assert result.status == "completed"
    assert [receipt.suggested_name for receipt in result.files] == ["Part.step"]
    unavailable_updates = [
        argument["unavailableFormats"]
        for _expression, argument in page.evaluations
        if isinstance(argument, dict) and argument.get("unavailableFormats")
    ]
    assert ["kicad", "altium"] in unavailable_updates


def test_all_unavailable_provider_formats_advance_without_waiting_for_downloads(tmp_path):
    page = _HudPage()

    def operate(_page):
        return [
            SimpleNamespace(
                selected=[],
                missed=["kicad", "model", "altium"],
                submitted=False,
                blocked=False,
            )
        ]

    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = ProviderHudSpec(
        provider_label="SnapMagic",
        author_route="SnapMagic",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=("KiCad", "STEP", "Altium"),
        required_formats=("kicad", "model", "altium"),
    )
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        provider_key="snapmagic",
    )
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://www.snapeda.com/parts/MPN-A-7/Exact-Manufacturer/view-part/",
        broker,
        hud=spec,
        timeout_s=10,
        poll_interval_s=0.01,
        settle_seconds=0,
        operate_controls=operate,
    )

    assert result.status == "try_another"
    assert result.files == ()
    assert page.waits == 0


def test_submitted_unavailable_report_waits_for_late_download_event(monkeypatch, tmp_path):
    page = _HudPage()
    calls = 0

    def operate(_page):
        nonlocal calls
        calls += 1
        return [
            SimpleNamespace(
                selected=["kicad"],
                missed=["kicad"],
                submitted=True,
                blocked=False,
                requires_user_clearance=False,
            )
        ]

    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = ProviderHudSpec(
        provider_label="Provider",
        author_route="Provider",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=("KiCad",),
        required_formats=("kicad",),
    )
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = SimpleNamespace(new_page=lambda: page)
    monkeypatch.setattr(browser_module, "_OPERATOR_SUBMISSION_WINDOW_SECONDS", 0.05)

    started = time.monotonic()
    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        hud=spec,
        timeout_s=1,
        poll_interval_s=0.005,
        operate_controls=operate,
    )
    elapsed = time.monotonic() - started

    assert result.status == "try_another"
    assert result.files == ()
    assert elapsed >= 0.04
    assert calls == 1


def test_user_capture_resumes_automatically_after_a_detected_download(tmp_path):
    """One archive carrying every required format resumes without a click."""

    class Download:
        suggested_filename = "complete-cad.zip"
        url = "https://vendor.example.test/files/complete-cad.zip"

        def save_as(self, destination: str) -> None:
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("Part.kicad_sym", "symbol")
                archive.writestr("Part.pretty/Part.kicad_mod", "footprint")
                archive.writestr("Part.step", "model")
                archive.writestr("Part.SchLib", "symbol")
                archive.writestr("Part.PcbLib", "footprint")

    page = _HudPage()
    page.on_goto = lambda: page.handlers[0](Download())

    result, broker = _hud_capture(
        tmp_path,
        page,
        auto_finish_seconds=0,
        auto_finish_idle_seconds=0,
    )

    assert result.status == "completed"
    assert len(broker.receipts) == 1
    assert zipfile.is_zipfile(broker.receipts[0].path)
    assert page.waits == 0


def test_user_capture_reloads_a_blank_provider_fragment_at_most_twice(tmp_path):
    class Download:
        suggested_filename = "complete-cad.zip"
        url = "https://vendor.example.test/files/complete-cad.zip"

        def save_as(self, destination: str) -> None:
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("Part.kicad_sym", "symbol")
                archive.writestr("Part.pretty/Part.kicad_mod", "footprint")
                archive.writestr("Part.step", "model")

    class BlankThenReadyPage(_HudPage):
        def __init__(self) -> None:
            super().__init__()
            self.reloads = 0

        def reload(self, **options) -> None:
            assert options == {"wait_until": "commit", "timeout": 1_000}
            self.reloads += 1
            if self.reloads == 2:
                self.handlers[0](Download())

    page = BlankThenReadyPage()
    staging = tmp_path / "Staging"
    staging.mkdir()
    spec = _provider_hud_spec()
    broker = DownloadBroker(DownloadTask("part-a", spec.manufacturer, spec.mpn, staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        hud=spec,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
        auto_finish_seconds=0,
        retryable_render_issue=lambda _page: "provider row is blank",
        max_render_reloads=2,
        render_reload_delay_seconds=0,
        operate_controls=lambda _page: setattr(
            page, "operator_runs", getattr(page, "operator_runs", 0) + 1
        ),
    )

    assert result.status == "completed"
    assert page.reloads == 2
    assert page.operator_runs == 3
    assert len(result.files) == 1


def test_download_survives_provider_navigation_abort(tmp_path):
    class Download:
        suggested_filename = "complete.zip"
        url = "https://vendor.example.test/files/complete.zip"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"complete-cad-archive")

    class AbortingPage(_HudPage):
        def goto(self, url: str, **options) -> None:
            super().goto(url, **options)
            self.handlers[0](Download())
            raise RuntimeError("download response aborted the page navigation")

    result, broker = _hud_capture(tmp_path, AbortingPage())

    assert result.status == "completed"
    assert len(broker.receipts) == 1
    assert broker.receipts[0].path.read_bytes() == b"complete-cad-archive"


def test_finish_request_survives_provider_navigation_failure(tmp_path):
    """A task-bound manual file handoff must not wait for provider page readiness."""

    finish_requested = False

    class FailingPage(_EventPage):
        url = "about:blank"

        def __init__(self) -> None:
            super().__init__()
            self.waits = 0

        def goto(self, url: str, **options) -> None:
            assert options["wait_until"] == "commit"
            assert options["timeout"] == 10_000
            self.url = url
            assert self.handlers, "download interception must be wired before navigation"
            raise RuntimeError("provider never reached a stable document lifecycle")

        def wait_for_timeout(self, _milliseconds: int) -> None:
            nonlocal finish_requested
            self.waits += 1
            finish_requested = True

        def is_closed(self) -> bool:
            return False

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    page = FailingPage()
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A",
        broker,
        should_finish=lambda: finish_requested,
        timeout_s=600,
    )

    assert result.status == "completed"
    assert result.files == ()
    assert page.waits == 1


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("finish", "completed"),
        ("try_another", "try_another"),
        ("cancel", "cancelled"),
    ],
)
def test_user_capture_hud_actions_drive_distinct_result_statuses(
    tmp_path,
    action,
    expected_status,
):
    page = _HudPage()
    # Recorded rather than asserted in place: capture_user_downloads treats any exception out of
    # goto as a navigation failure, so an assertion raised from this callback was swallowed and
    # every outcome below silently passed through the goto-failure path instead.
    outcomes: list[bool] = []

    def act_once() -> None:
        outcomes.append(page.invoke_hud_action(action, token="not-the-hud-token"))
        outcomes.append(page.invoke_hud_action(action))
        outcomes.append(page.invoke_hud_action(action))

    page.on_goto = act_once
    result, _broker = _hud_capture(tmp_path, page)

    assert result.status == expected_status
    assert outcomes == [False, True, True]


def test_user_capture_hud_rejects_identity_that_is_not_its_bound_task(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = SimpleNamespace(new_page=lambda: _HudPage())
    mismatched = ProviderHudSpec(
        provider_label="Provider",
        author_route="CAD Author",
        manufacturer="Different Manufacturer",
        mpn="MPN-A",
        required_file_labels=("KiCad symbol",),
    )

    with pytest.raises(CaptureBrowserError, match="exactly match"):
        browser.capture_user_downloads(
            "https://vendor.example.test/search?query=MPN-A",
            broker,
            hud=mismatched,
            timeout_s=1,
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


def test_embedded_task_page_reuses_the_nonblank_stockroom_webview(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    stockroom_page = _EventPage()
    stockroom_page.url = "http://127.0.0.1:49152/components"
    stale_provider_popup = _EventPage()
    stale_provider_popup.url = "https://www.digikey.com/en/models/stale"
    context = _PageContext()
    context.pages.extend((stale_provider_popup, stockroom_page))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
        native_surface=SimpleNamespace(current_url=lambda: stockroom_page.url),
    )
    browser._context = context

    with browser.task_page(broker) as page:
        assert page.raw_page is stockroom_page

    assert context.pages == [stale_provider_popup, stockroom_page]
    assert stockroom_page.closed is False
    assert browser._page_brokers == []
    assert browser._wired_pages == []


def test_detached_provider_navigation_reconnects_only_after_native_page_is_ready(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []
    states = iter(
        (
            {"ready": True, "challenge": True, "provider_ready": False},
            {"ready": True, "challenge": False, "provider_ready": True},
            {"ready": True, "challenge": False, "provider_ready": True},
            {"ready": True, "challenge": False, "provider_ready": True},
        )
    )

    class Runtime:
        generation = 4

        def close(self) -> None:
            events.append("detach")

        def get(self):
            events.append("reconnect")
            return object()

    class NativeSurface:
        def show(self) -> None:
            events.append("show")

        def navigate(self, url: str) -> None:
            events.append(f"navigate:{url}")

        def document_state(self, **_options):
            state = next(states)
            events.append(f"state:{state['challenge']}:{state['provider_ready']}")
            return state

    class ReconnectedContext:
        def __init__(self, page) -> None:
            self.pages = [page]

        def on(self, event: str, _callback) -> None:
            assert event == "page"

    old_page = _EventPage()
    old_page.url = "about:blank"
    replacement = _EventPage()
    replacement.url = "https://www.snapeda.com/parts/MPN/Maker/view-part/"
    context = ReconnectedContext(replacement)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="snapmagic",
    )
    browser._context = object()
    page = _ReconnectablePage(old_page)
    monkeypatch.setattr(browser, "_launch_playwright", lambda _pw: (context, object()))
    monkeypatch.setattr("stockroom.capture.browser.time.sleep", lambda _seconds: None)

    browser.navigate_provider(
        page,
        replacement.url,
        detached=True,
        ready_selectors=('a[name="download-modal"]',),
    )

    assert page.raw_page is replacement
    assert events == [
        "show",
        "detach",
        f"navigate:{replacement.url}",
        "state:True:False",
        "state:False:True",
        "state:False:True",
        "state:False:True",
        "reconnect",
    ]


def test_detached_provider_navigation_returns_immediately_on_terminal_provider_error(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Runtime:
        generation = 4

        def close(self) -> None:
            events.append("detach")

        def get(self):
            events.append("reconnect")
            return object()

    class NativeSurface:
        def show(self) -> None:
            events.append("show")

        def navigate(self, url: str) -> None:
            events.append(f"navigate:{url}")

        def document_state(self, **_options):
            events.append("state:provider-error")
            return {
                "ready": True,
                "challenge": False,
                "provider_error": True,
                "provider_ready": False,
            }

    class ReconnectedContext:
        def __init__(self, page) -> None:
            self.pages = [page]

        def on(self, event: str, _callback) -> None:
            assert event == "page"

    old_page = _EventPage()
    old_page.url = "about:blank"
    replacement = _EventPage()
    replacement.url = "https://www.snapeda.com/error/"
    context = ReconnectedContext(replacement)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="snapmagic",
    )
    browser._context = object()
    page = _ReconnectablePage(old_page)
    monkeypatch.setattr(browser, "_launch_playwright", lambda _pw: (context, object()))
    monkeypatch.setattr("stockroom.capture.browser.time.sleep", lambda _seconds: None)

    with pytest.raises(CaptureBrowserError, match="terminal page error"):
        browser.navigate_provider(
            page,
            replacement.url,
            detached=True,
            ready_selectors=('a[name="download-modal"]',),
            timeout_s=600,
        )

    assert events == [
        "show",
        "detach",
        f"navigate:{replacement.url}",
        "state:provider-error",
        "reconnect",
    ]


def test_embedded_user_capture_detaches_for_navigation_and_any_later_security_gate(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Page(_EventPage):
        url = "http://127.0.0.1:49152/components"

        def goto(self, _url: str, **_options) -> None:
            raise AssertionError("embedded person-driven navigation must not keep CDP attached")

        def wait_for_timeout(self, _milliseconds: int) -> None:
            events.append("wait")

        def is_closed(self) -> bool:
            return False

    class Runtime:
        generation = 1

    challenge_states = iter((True, False))

    class NativeSurface:
        def current_url(self) -> str:
            return page.url

        def navigate(self, _url: str) -> None:
            raise AssertionError("the patched navigation contract owns this test")

        def document_state(self, **_options):
            return {"ready": True, "challenge": False, "provider_ready": True}

        def security_state(self):
            return {"ready": True, "challenge": next(challenge_states)}

    page = Page()
    context = _PageContext()
    context.pages.append(page)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="digikey",
    )
    browser._context = context

    def detached_navigation(page_handle, url, **options) -> None:
        events.append(f"navigate:{options['detached']}:{url}")
        page_handle.raw_page.url = url

    def detach_security(_page_handle, **_options) -> bool:
        events.append("detach-security")
        return True

    monkeypatch.setattr(browser, "navigate_provider", detached_navigation)
    monkeypatch.setattr(browser, "_detach_until_security_clears", detach_security)

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    result = browser.capture_user_downloads(
        "https://www.digikey.com/en/models/123",
        broker,
        operate_controls=lambda _page: events.append("operate"),
        should_finish=lambda: True,
        settle_seconds=0,
        timeout_s=1,
    )

    assert result.status == "completed"
    assert events == [
        "navigate:True:https://www.digikey.com/en/models/123",
        "operate",
        "detach-security",
        "operate",
    ]


def test_embedded_user_capture_advances_immediately_from_terminal_provider_page(
    monkeypatch,
    tmp_path,
):
    class Page(_EventPage):
        url = "https://www.snapeda.com/parts/MPN-A/Maker/view-part/"

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("a terminal provider page must not spend the route timeout")

        def is_closed(self) -> bool:
            return False

    class Runtime:
        generation = 1

    class NativeSurface:
        def navigate(self, _url: str) -> None:
            raise AssertionError("the patched navigation contract owns this test")

        def document_state(self, **_options):
            return {"ready": True, "challenge": False, "provider_ready": True}

    page = Page()
    context = _PageContext()
    context.pages.append(page)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="digikey",
    )
    browser._context = context

    def terminal_navigation(_page_handle, _url, **_options) -> None:
        raise ProviderPageTerminalError("provider rendered its terminal error document")

    monkeypatch.setattr(browser, "navigate_provider", terminal_navigation)
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))

    result = browser.capture_user_downloads(
        page.url,
        broker,
        timeout_s=600,
    )

    assert result.status == "try_another"
    assert result.files == ()


def test_embedded_user_capture_returns_immediately_for_account_verification(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Page(_EventPage):
        url = "https://www.snapeda.com/parts/MPN-A/Maker/view-part/"

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("account verification must not spend the route timeout")

        def is_closed(self) -> bool:
            return False

    class Runtime:
        generation = 1

        def close(self) -> None:
            events.append("detach")

    class NativeSurface:
        def current_url(self) -> str:
            return "https://www.snapeda.com/profiles/verify/"

        def navigate(self, _url: str) -> None:
            raise AssertionError("the patched navigation contract owns this test")

        def document_state(self, **_options):
            return {"ready": True, "challenge": False, "provider_ready": True}

        def security_state(self):
            return {
                "ready": True,
                "challenge": True,
                "account_verification": True,
            }

    page = Page()
    context = _PageContext()
    context.pages.append(page)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="digikey",
    )
    browser._context = context

    def detached_navigation(page_handle, url, **options) -> None:
        events.append(f"navigate:{options['detached']}:{url}")
        page_handle.raw_page.url = url

    monkeypatch.setattr(browser, "navigate_provider", detached_navigation)
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))

    result = browser.capture_user_downloads(
        "https://www.digikey.com/en/models/123",
        broker,
        timeout_s=600,
    )

    assert result.status == "timed_out"
    assert result.final_url == "https://www.snapeda.com/profiles/verify/"
    assert result.files == ()
    assert events == [
        "navigate:True:https://www.digikey.com/en/models/123",
        "detach",
    ]


def test_embedded_user_capture_returns_when_account_verification_appears_after_detach(
    monkeypatch,
    tmp_path,
):
    events: list[str] = []

    class Page(_EventPage):
        url = "https://www.snapeda.com/parts/MPN-A/Maker/view-part/"

        def wait_for_timeout(self, _milliseconds: int) -> None:
            raise AssertionError("late account verification must not spend the route timeout")

        def is_closed(self) -> bool:
            return False

    class Runtime:
        generation = 1

        def close(self) -> None:
            events.append("detach")

    security_calls = 0

    class NativeSurface:
        def current_url(self) -> str:
            return "https://www.snapeda.com/profiles/verify/"

        def navigate(self, _url: str) -> None:
            raise AssertionError("the patched navigation contract owns this test")

        def document_state(self, **_options):
            return {"ready": True, "challenge": False, "provider_ready": True}

        def security_state(self):
            nonlocal security_calls
            security_calls += 1
            if security_calls == 1:
                return {
                    "ready": True,
                    "challenge": True,
                    "account_verification": False,
                }
            return {
                "ready": True,
                "challenge": True,
                "account_verification": True,
            }

    page = Page()
    context = _PageContext()
    context.pages.append(page)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
        playwright_runtime=Runtime(),
        native_surface=NativeSurface(),
        provider_key="digikey",
    )
    browser._context = context

    def detached_navigation(page_handle, url, **options) -> None:
        events.append(f"navigate:{options['detached']}:{url}")
        page_handle.raw_page.url = url

    monkeypatch.setattr(browser, "navigate_provider", detached_navigation)
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))

    result = browser.capture_user_downloads(
        "https://www.digikey.com/en/models/123",
        broker,
        poll_interval_s=0.001,
        timeout_s=600,
    )

    assert result.status == "timed_out"
    assert result.final_url == "https://www.snapeda.com/profiles/verify/"
    assert result.files == ()
    assert security_calls == 2
    assert events == [
        "navigate:True:https://www.digikey.com/en/models/123",
        "detach",
    ]


def test_user_capture_wires_before_navigation_and_collects_every_download_without_dom_actions(
    tmp_path,
):
    actions: list[str] = []
    finished = False

    class Download:
        def __init__(self, name: str):
            self.suggested_filename = name
            self.url = f"https://vendor.example.test/files/{name}"

        def save_as(self, destination: str) -> None:
            Path(destination).write_text(self.suggested_filename, encoding="utf-8")

    class UserPage(_EventPage):
        url = "about:blank"

        def on(self, event: str, handler) -> None:
            actions.append(f"on:{event}")
            super().on(event, handler)

        def goto(self, url: str, **_options) -> None:
            nonlocal finished
            actions.append(f"goto:{url}")
            self.url = url
            assert self.handlers, "download interception must be wired before navigation"
            for name in ("symbol.kicad_sym", "footprint.kicad_mod", "model.step"):
                self.handlers[0](Download(name))
            finished = False

        def wait_for_timeout(self, _milliseconds: int) -> None:
            nonlocal finished
            actions.append("wait")
            finished = True

        def is_closed(self) -> bool:
            return False

    page = UserPage()

    class Context:
        def new_page(self):
            return page

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = Context()

    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A",
        broker,
        should_finish=lambda: finished,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
    )

    assert result.status == "completed"
    assert [receipt.suggested_name for receipt in result.files] == [
        "symbol.kicad_sym",
        "footprint.kicad_mod",
        "model.step",
    ]
    assert [receipt.path.read_text(encoding="utf-8") for receipt in result.files] == [
        "symbol.kicad_sym",
        "footprint.kicad_mod",
        "model.step",
    ]
    assert actions[0] == "on:download"
    assert actions[1] == "goto:https://vendor.example.test/search?query=MPN-A"
    assert actions[2:] == ["wait"]


def test_user_capture_cancel_is_bounded_and_does_not_require_a_download(tmp_path):
    class IdlePage(_EventPage):
        url = "about:blank"

        def __init__(self):
            super().__init__()
            self.waits = 0

        def goto(self, url: str, **_options) -> None:
            self.url = url

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits += 1
            time.sleep(milliseconds / 1000)

        def is_closed(self) -> bool:
            return False

    page = IdlePage()
    context = SimpleNamespace(new_page=lambda: page)
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = context

    started = time.monotonic()
    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A",
        broker,
        should_cancel=lambda: page.waits >= 1,
        timeout_s=1,
        poll_interval_s=0.01,
    )
    elapsed = time.monotonic() - started

    assert result.status == "cancelled"
    assert result.files == ()
    assert page.waits == 1
    assert elapsed < 0.5


def test_user_capture_timeout_is_bounded_and_returns_files_received_so_far(tmp_path):
    class Download:
        suggested_filename = "symbol.kicad_sym"
        url = "https://vendor.example.test/files/symbol.kicad_sym"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"partial-capture")

    class IdlePage(_EventPage):
        url = "about:blank"

        def __init__(self):
            super().__init__()
            self.waits = 0

        def goto(self, url: str, **_options) -> None:
            self.url = url
            self.handlers[0](Download())

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits += 1
            time.sleep(milliseconds / 1000)

        def is_closed(self) -> bool:
            return False

    page = IdlePage()
    context = SimpleNamespace(new_page=lambda: page)
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = context

    started = time.monotonic()
    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A",
        broker,
        timeout_s=0.03,
        poll_interval_s=0.01,
    )
    elapsed = time.monotonic() - started

    assert result.status == "timed_out"
    assert len(result.files) == 1
    assert result.files[0].path.read_bytes() == b"partial-capture"
    assert 1 <= page.waits <= 5
    assert elapsed < 0.5


def test_user_capture_timeout_waits_for_recent_operator_submission(monkeypatch, tmp_path):
    class IdlePage(_EventPage):
        url = "about:blank"

        def goto(self, url: str, **_options) -> None:
            self.url = url

        def wait_for_timeout(self, milliseconds: int) -> None:
            time.sleep(milliseconds / 1000)

        def is_closed(self) -> bool:
            return False

    page = IdlePage()
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = SimpleNamespace(new_page=lambda: page)
    monkeypatch.setattr(browser_module, "_OPERATOR_SUBMISSION_WINDOW_SECONDS", 0.05)

    started = time.monotonic()
    result = browser.capture_user_downloads(
        "https://vendor.example.test/search?query=MPN-A",
        broker,
        operate_controls=lambda _page: [
            SimpleNamespace(submitted=True, blocked=False, requires_user_clearance=False, missed=[])
        ],
        timeout_s=0.01,
        poll_interval_s=0.005,
    )
    elapsed = time.monotonic() - started

    assert result.status == "timed_out"
    assert result.files == ()
    assert elapsed >= 0.04
    assert browser._embedded_finalized_generations == {1}


def test_navigation_terminal_drains_a_late_native_download(tmp_path):
    source = tmp_path / "native-navigation.step"
    source.write_text("ISO-10303-21;", encoding="utf-8")
    events = (
        SimpleNamespace(
            sequence=1,
            operation_id="native-navigation",
            phase="started",
            state="in_progress",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name="Exact.step",
            result_file_path=str(source),
        ),
        SimpleNamespace(
            sequence=2,
            operation_id="native-navigation",
            phase="terminal",
            state="completed",
            uri="https://provider.example.test/Exact.step",
            suggested_file_name="Exact.step",
            result_file_path=str(source),
        ),
    )

    class Surface:
        def __init__(self) -> None:
            self.polls = 0

        def download_events(self, *, after_sequence=0):
            self.polls += 1
            if self.polls == 1:
                return ()
            return tuple(item for item in events if item.sequence > after_sequence)

    class ClosedPage(_EventPage):
        url = "about:blank"

        def goto(self, _url: str, **_options) -> None:
            self.closed = True
            raise RuntimeError("navigation was replaced by a download")

        def is_closed(self) -> bool:
            return self.closed

    surface = Surface()
    page = ClosedPage()
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        native_surface=surface,
    )
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://provider.example.test/Exact.step",
        broker,
        settle_seconds=0,
        poll_interval_s=0.01,
        timeout_s=1,
    )

    assert result.status == "completed"
    assert [receipt.suggested_name for receipt in result.files] == ["Exact.step"]
    assert result.files[0].path.read_text(encoding="utf-8") == "ISO-10303-21;"
    assert surface.polls >= 2


def test_visible_operator_waits_for_every_expected_download(tmp_path):
    class Download:
        def __init__(self, index: int) -> None:
            self.suggested_filename = f"Part-{index}.step"
            self.url = f"https://provider.example.test/Part-{index}.step"
            self.index = index

        def save_as(self, destination: str) -> None:
            Path(destination).write_text(f"payload-{self.index}", encoding="utf-8")

    page = _HudPage()
    operates = 0

    def operate(_page):
        nonlocal operates
        operates += 1
        return [
            SimpleNamespace(
                submitted=True,
                expected_downloads=3,
                blocked=False,
                requires_user_clearance=False,
                missed=[],
            )
        ]

    def deliver(wait_number: int) -> None:
        if 1 <= wait_number <= 3:
            page.handlers[0](Download(wait_number))

    page.on_wait = deliver
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads")
    browser._context = SimpleNamespace(new_page=lambda: page)

    result = browser.capture_user_downloads(
        "https://provider.example.test/export",
        broker,
        operate_controls=operate,
        auto_finish_seconds=0,
        poll_interval_s=0.01,
        timeout_s=1,
    )

    assert result.status == "completed"
    assert len(result.files) == 3
    assert operates == 1


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


def test_noopener_download_window_still_attaches_to_the_active_task(tmp_path):
    """A provider download control that opens a rel=noopener tab must still attach its file.

    Chromium reports no opener for such a window, so the opener walk cannot reach the task
    page. The file was saved to the legacy download directory and never added to the task
    receipts, which surfaced as "the vendor download did not produce a file" while the HUD
    count stayed at zero and Resume Now stayed permanently disabled.
    """

    class Orphan(_EventPage):
        def opener(self):
            return None

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    context = _PageContext()
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        cdp_endpoint="http://127.0.0.1:43127",
    )
    browser._context = context

    with browser.task_page(broker) as page:
        assert page is not None
        orphan = Orphan()
        context.pages.append(orphan)
        browser._wire_downloads(orphan)
        orphan.handlers[0](_Download())

    assert len(broker.receipts) == 1
    assert broker.receipts[0].path.parent == staging / "part-a"
    assert orphan.closed is True


def test_auto_finish_waits_for_every_required_file_before_completing(tmp_path):
    """Auto-finish must not end a capture that is still missing required formats.

    The HUD names three required files. Completing a bounded quiet period after the first
    one truncates the capture, and the partial set then fails downstream binding, so a real
    download is discarded rather than attached.
    """

    class Download:
        def __init__(self, name: str):
            self.suggested_filename = name
            self.url = f"https://vendor.example.test/{name}"

        def save_as(self, destination: str) -> None:
            Path(destination).write_text(self.suggested_filename, encoding="utf-8")

    page = _HudPage()
    page.on_goto = lambda: page.handlers[0](Download("symbol.kicad_sym"))

    def deliver(count: int) -> None:
        time.sleep(0.02)
        if count == 6:
            page.handlers[0](Download("footprint.kicad_mod"))
            page.handlers[0](Download("model.step"))

    page.on_wait = deliver

    class Context:
        def new_page(self):
            return page

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Exact Manufacturer", "MPN-A/7", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = Context()

    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        hud=_provider_hud_spec(),
        timeout_s=5,
        poll_interval_s=0.01,
        settle_seconds=0,
        auto_finish_seconds=0.05,
        auto_finish_idle_seconds=0,
    )

    assert result.status == "completed"
    assert len(result.files) == 3


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


def test_a_failed_companion_download_keeps_every_staged_file(tmp_path):
    """One failing companion download must not discard files already staged.

    The error check raised out of the capture block, so UserCaptureResult was never built and
    every receipt staged before the failure was lost. The caller then reported a plain error
    and attached nothing, which is exactly the loss the capture contract forbids.
    """

    class Good:
        suggested_filename = "symbol.kicad_sym"
        url = "https://vendor.example.test/files/symbol.kicad_sym"

        def save_as(self, destination: str) -> None:
            Path(destination).write_bytes(b"captured-symbol")

    class Bad:
        suggested_filename = "footprint.kicad_mod"
        url = "https://vendor.example.test/files/footprint.kicad_mod"

        def save_as(self, destination: str) -> None:
            raise OSError("connection reset by peer")

    class UserPage(_EventPage):
        url = "about:blank"

        def goto(self, url: str, **_options) -> None:
            self.url = url
            self.handlers[0](Good())
            self.handlers[0](Bad())

        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

        def is_closed(self) -> bool:
            return False

    page = UserPage()

    class Context:
        def new_page(self):
            return page

    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(DownloadTask("part-a", "Manufacturer", "MPN-A", staging))
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Legacy")
    browser._context = Context()

    result = browser.capture_user_downloads(
        "https://vendor.example.test/part",
        broker,
        timeout_s=1,
        poll_interval_s=0.01,
        settle_seconds=0,
        auto_finish_seconds=0,
    )

    assert len(result.files) == 1
    assert result.files[0].path.read_bytes() == b"captured-symbol"


def test_repeating_one_hud_action_is_accepted_but_a_conflicting_one_is_not():
    """Clicking the same HUD control twice must not report a Stockroom failure.

    One state is shared across every page bound to a task, and the HUD remounts with a fresh
    pending flag on each provider navigation, so a person can legitimately click the same
    control again before Python acts on the first request. Rejecting the repeat surfaced
    "Stockroom could not accept that action" for a request that had already been accepted.
    """

    state = _ProviderHudState(_provider_hud_spec())
    token = state.action_token

    assert state.request_action("finish", token) is True
    assert state.request_action("finish", token) is True
    assert state.request_action("cancel", token) is False
    assert state.action == "finish"
    assert state.request_action("finish", "wrong-token") is False


def test_provider_hud_state_read_back_is_guarded_by_its_own_token():
    """A remounting HUD reads the live count through a binding held to the same discipline.

    The bootstrap payload embeds the count as it stood when the page was bound, so every
    navigation remounted the panel claiming zero captured files. The read-back needs its own
    namespace and secret exactly like the security handoff's state binding.
    """

    state = _ProviderHudState(_provider_hud_spec())
    state.update_download_count(4)

    assert state.state_binding.startswith("__stockroom_capture_state_")
    assert state.state_binding != state.action_binding
    assert state.state_token != state.action_token
    assert state.read_state(state.state_token) == {
        "downloadCount": 4,
        "completedFormats": [],
        "unavailableFormats": [],
        "securityHold": False,
    }
    assert state.read_state(state.action_token) == {}
    assert state.read_state("wrong-token") == {}
    assert state.read_state(None) == {}


def test_provider_hud_binds_a_state_read_back_before_provider_navigation(tmp_path):
    page = _HudPage()

    result, _broker = _hud_capture(tmp_path, page, action="finish")

    assert result.status == "completed"
    _bootstrap, payload = page.evaluations[0]
    assert payload["stateBinding"] in page.bindings
    assert payload["actionBinding"] in page.bindings
    goto_index = page.events.index("goto:https://vendor.example.test/search?query=MPN-A%2F7")
    assert page.events.count("expose-binding") == 2
    assert [index for index, event in enumerate(page.events) if event == "expose-binding"][
        -1
    ] < goto_index
    assert page.read_hud_state()["downloadCount"] == 0
    assert page.read_hud_state(token="not-the-state-token") == {}


_HUD_SHADOW_PROBE = r"""
() => {
  const attachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (options) {
    const root = attachShadow.call(this, { ...options, mode: "open" });
    // Stockroom now attaches THREE closed roots (the tab bar, panel, and outline surface), so the probe
    // keeps every one and each read below names the surface it means.
    (globalThis.__stockroom_probe_shadows ||= []).push(root);
    globalThis.__stockroom_probe_shadow = root;
    return root;
  };
}
"""

_HUD_PROBE_ROOT = r"""
  const surface = (selector) =>
    (globalThis.__stockroom_probe_shadows || []).find((root) => root.querySelector(selector));
"""

_HUD_SHADOW_READ = (
    r"""
() => {
"""
    + _HUD_PROBE_ROOT
    + r"""
  const root = surface(".panel");
  if (!root) return null;
  const spoken = root.querySelectorAll(".sr-only");
  const finish = root.querySelector(".finish");
  return {
    count: root.querySelector(".mode").textContent,
    countLabel: root.querySelector(".mode").getAttribute("aria-label"),
    automated: root.querySelector(".state-value").textContent,
    live: spoken[0].textContent,
    announced: spoken[1].textContent,
    finishLabel: finish.textContent,
    finishDisabled: finish.disabled,
    finishTitle: finish.title,
    anotherDisabled: root.querySelector(".another").disabled,
    cancelDisabled: root.querySelector(".cancel").disabled,
  };
}
"""
)

_HUD_CHECKLIST_READ = (
    r"""
() => {
"""
    + _HUD_PROBE_ROOT
    + r"""
  const root = surface(".panel");
  if (!root) return null;
  const instruction = root.querySelector(".instruction");
  const outstanding = root.querySelector(".outstanding");
  const hintState = root.querySelector(".hint-state");
  return {
    instruction: instruction ? instruction.textContent : null,
    steps: [...root.querySelectorAll(".checklist .step")].map((step) => ({
      className: step.className,
      mark: step.querySelector(".step-mark").textContent,
      state: step.querySelector(".step-state").textContent,
      text: step.querySelector(".step-text").textContent,
    })),
    outstanding: outstanding ? outstanding.textContent : null,
    outstandingClass: outstanding ? outstanding.className : null,
    hintState: hintState ? hintState.textContent : null,
  };
}
"""
)

_HUD_OVERLAY_READ = (
    r"""
() => {
"""
    + _HUD_PROBE_ROOT
    + r"""
  const root = surface(".overlay");
  if (!root) return null;
  return [...root.querySelectorAll(".outline")].map((box) => ({
    label: box.querySelector(".outline-tag").textContent,
    pointerEvents: getComputedStyle(box).pointerEvents,
    left: Math.round(box.getBoundingClientRect().left),
    top: Math.round(box.getBoundingClientRect().top),
    width: Math.round(box.getBoundingClientRect().width),
    height: Math.round(box.getBoundingClientRect().height),
  }));
}
"""
)

_HUD_CLICK_FINISH = (
    r"""
() => {
"""
    + _HUD_PROBE_ROOT
    + r"""
  surface(".panel").querySelector(".finish").click();
}
"""
)

_INERT_PROVIDER_BODY = b"<!doctype html><title>provider</title><p>provider page</p>"


@contextmanager
def _static_page_server(body: bytes = _INERT_PROVIDER_BODY):
    """Serve one inert document so a real navigation can remount the HUD."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def _real_provider_hud(tmp_path, *, spec: ProviderHudSpec | None = None, url: str | None = None):
    """Mount the real HUD in real Chromium and expose its closed shadow root for reading.

    The panel is deliberately unreadable from page scripts, so the probe reopens only the shadow
    Stockroom itself attaches. Nothing here touches provider content; the fake document is inert.
    """

    from stockroom.capture.browser import chromium_unavailable_reason

    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile",
        provider_key="provider-hud-probe",
        headless=True,
        engine="chromium",
    )
    state = _ProviderHudState(spec if spec is not None else _provider_hud_spec())
    with browser.session() as page:
        # Registered before the HUD's own init script so every remount is observable too.
        page.add_init_script(f"({_HUD_SHADOW_PROBE})();")
        page.evaluate(_HUD_SHADOW_PROBE)
        if url is not None:
            page.goto(url, wait_until="domcontentloaded")
        browser._bind_provider_hud(page, state)
        page.wait_for_timeout(150)
        yield browser, page, state


@pytest.mark.timeout(90)
def test_provider_hud_keeps_tracking_captured_files_after_an_accepted_action(tmp_path):
    """An accepted click must not freeze the panel state that reports captured files.

    The pending flag was never cleared once Python accepted an action, and it gated the finish
    button and the automated-step line. Python can stay busy for the rest of the session, so the
    panel then reported a stale capture reality while files kept landing.
    """

    with _real_provider_hud(tmp_path) as (browser, page, state):
        browser._update_provider_hud(state, 1)
        before = page.evaluate(_HUD_SHADOW_READ)
        page.evaluate(_HUD_CLICK_FINISH)
        page.wait_for_timeout(200)
        pending = page.evaluate(_HUD_SHADOW_READ)
        browser._update_provider_hud(state, 3)
        after = page.evaluate(_HUD_SHADOW_READ)

    assert state.action == "finish"
    assert before["finishDisabled"] is False
    assert before["automated"] == (
        "1 file captured. Stockroom will resume automatically after downloads settle."
    )

    assert after["count"] == "3 FILES"
    assert after["countLabel"] == "Downloads captured: 3"
    assert after["live"] == "3 files captured in this task."
    assert after["finishDisabled"] is False
    assert after["finishTitle"] == "Finish this route after its downloads settle"

    # The pending affordance withdraws only the controls that would conflict with the request
    # Stockroom already accepted; it never withdraws what the capture count reports.
    assert pending["anotherDisabled"] is True
    assert pending["cancelDisabled"] is True
    assert pending["automated"] == "Finishing capture after downloaded files settle."


@pytest.mark.timeout(90)
def test_provider_hud_announces_the_control_label_it_shows(tmp_path):
    """The spoken confirmation must name the control the person actually pressed."""

    with _real_provider_hud(tmp_path) as (browser, page, state):
        browser._update_provider_hud(state, 1)
        page.evaluate(_HUD_CLICK_FINISH)
        page.wait_for_timeout(200)
        pending = page.evaluate(_HUD_SHADOW_READ)

    assert state.action == "finish"
    assert pending["finishLabel"] == "Resume Now"
    assert pending["announced"] == f"{pending['finishLabel']} requested."


@pytest.mark.timeout(90)
def test_a_remounted_provider_hud_reads_the_live_count_not_its_bind_time_snapshot(tmp_path):
    """Every provider navigation remounts the HUD from the init script registered at bind time.

    That payload froze the count at zero, so a freshly mounted panel claimed no files had been
    captured until Python's next push - and on the navigation-failure path there is no next push.
    """

    with _real_provider_hud(tmp_path) as (browser, page, state), _static_page_server() as url:
        browser._update_provider_hud(state, 2)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(200)
        remounted = page.evaluate(_HUD_SHADOW_READ)

    assert remounted is not None
    assert remounted["count"] == "2 FILES"
    assert remounted["countLabel"] == "Downloads captured: 2"
    assert remounted["live"] == "2 files captured in this task."
    assert remounted["finishDisabled"] is False
    assert remounted["automated"] == (
        "2 files captured. Stockroom will resume automatically after downloads settle."
    )


# ---------------------------------------------------------------------------
# Tier 1: the live guided checklist, built only from Stockroom-owned data.
# ---------------------------------------------------------------------------


def _hinted_hud_spec(*hints: ProviderControlHint) -> ProviderHudSpec:
    return ProviderHudSpec(
        provider_label="Exact Provider",
        author_route="Exact CAD Author",
        manufacturer="Exact Manufacturer",
        mpn="MPN-A/7",
        required_file_labels=(
            "KiCad symbol and footprint",
            "STEP model",
            "Native Altium symbol and footprint",
        ),
        required_formats=("kicad", "model", "altium"),
        provider_instruction="Open the export panel and start one export.",
        control_hints=tuple(hints),
    )


@pytest.mark.timeout(90)
def test_provider_hud_checklist_reports_formats_verified_inside_downloads(tmp_path):
    """One ZIP is not one CAD role; only content classification may tick a format."""

    with _real_provider_hud(tmp_path, spec=_hinted_hud_spec()) as (browser, page, state):
        nothing_yet = page.evaluate(_HUD_CHECKLIST_READ)
        browser._update_provider_hud(state, 1, ("kicad",))
        page.wait_for_timeout(100)
        partway = page.evaluate(_HUD_CHECKLIST_READ)
        browser._update_provider_hud(state, 2, ("kicad", "model", "altium"))
        page.wait_for_timeout(100)
        complete = page.evaluate(_HUD_CHECKLIST_READ)

    assert nothing_yet is not None
    assert nothing_yet["instruction"] == "Open the export panel and start one export."
    assert [step["text"] for step in nothing_yet["steps"]] == [
        "KiCad symbol and footprint",
        "STEP model",
        "Native Altium symbol and footprint",
    ]
    assert [step["state"] for step in nothing_yet["steps"]] == [
        "Required",
        "Required",
        "Required",
    ]
    assert nothing_yet["outstanding"] == (
        "No download received yet. Required: KiCad symbol and footprint, STEP model, "
        "Native Altium symbol and footprint."
    )

    assert [step["state"] for step in partway["steps"]] == [
        "Verified in download",
        "Required",
        "Required",
    ]
    assert partway["steps"][0]["mark"] == "✓"
    assert partway["outstanding"] == (
        "1 package safely received. Still missing from its contents: STEP model, Native Altium "
        "symbol and footprint. Download another package if this provider offers it, or let "
        "Stockroom try the next provider."
    )

    assert [step["state"] for step in complete["steps"]] == [
        "Verified in download",
        "Verified in download",
        "Verified in download",
    ]
    assert complete["outstandingClass"] == "outstanding done"
    assert complete["outstanding"] == (
        "All 3 required formats are present in the downloaded package. Stockroom resumes "
        "automatically."
    )


def test_provider_hud_payload_carries_the_provider_instruction_and_its_control_hints():
    """Tier 1 context and Tier 2 hints are Stockroom-owned data on the HUD spec."""

    hint = ProviderControlHint(
        label="Export",
        selectors=("#submit-export",),
        source="vendors.py UltraLibrarianAdapter._export_button",
    )
    payload = _ProviderHudState(_hinted_hud_spec(hint)).payload()

    assert payload["providerInstruction"] == "Open the export panel and start one export."
    assert payload["controlHints"] == [{"label": "Export", "selectors": ["#submit-export"]}]
    # The measured provenance is for reviewers, not for the provider page.
    assert "source" not in json.dumps(payload["controlHints"])


def test_provider_hud_reads_its_instruction_and_hints_from_the_vendor_registry():
    """`guided.py` builds the spec from identity alone, so the registry supplies the guidance.

    Explicit spec fields still win; the registry is the fallback keyed on the exact provider
    label the capability itself declares.
    """

    from stockroom.capture.vendors import UltraLibrarianAdapter

    capability = UltraLibrarianAdapter.capability
    payload = _ProviderHudState(
        ProviderHudSpec(
            provider_label=capability.label,
            author_route=capability.label,
            manufacturer="Exact Manufacturer",
            mpn="MPN-A/7",
            required_file_labels=("KiCad 6 or later",),
        )
    ).payload()

    assert payload["providerInstruction"] == capability.instruction
    assert [hint["selectors"] for hint in payload["controlHints"]] == [
        list(hint.selectors) for hint in capability.control_hints
    ]
    assert payload["controlHints"], "Ultra Librarian has measured control hints"


def _every_hinted_capability():
    from stockroom.capture.vendors import all_adapters

    seen: dict[str, object] = {}
    for adapter in all_adapters():
        candidates = [adapter]
        routes = getattr(adapter, "capture_routes", None)
        if callable(routes):
            candidates.extend(routes())
        for candidate in candidates:
            seen[candidate.capability.label] = candidate.capability
    return seen


def test_every_declared_control_hint_names_a_measured_source_and_a_plain_selector():
    """A hint may only point at something this repo measured, with a plain CSS selector.

    Playwright's own pseudo-classes (`:visible`, `:has-text`) are not CSS and would either throw
    in the page or, worse, match on TEXT - which is exactly the content the narrowed contract
    forbids the overlay from touching.
    """

    for label, capability in _every_hinted_capability().items():
        for hint in capability.control_hints:
            assert hint.source.strip(), f"{label} hint {hint.label!r} names no measured source"
            assert hint.label == hint.label.strip() and hint.label
            for selector in hint.selectors:
                assert ":visible" not in selector, f"{label} hint uses a Playwright pseudo-class"
                assert ":has-text" not in selector, f"{label} hint matches on page text"
                assert ":checked" not in selector, f"{label} hint reads a form value"


def test_control_hints_are_derived_from_the_measured_pins_and_routes_not_invented():
    """Every outlined selector traces back to data an automated path already measured."""

    from stockroom.capture.vendors import (
        _DIGIKEY_MANUFACTURER_ROUTE,
        _DIGIKEY_ULTRALIBRARIAN_ROUTE,
        SnapMagicAdapter,
        UltraLibrarianAdapter,
        _export_selectors,
        get_adapter,
    )

    ultra = UltraLibrarianAdapter.capability
    ultra_hints = {hint.label: hint.selectors for hint in ultra.control_hints}
    assert ultra_hints["KiCad v6+ export"] == _export_selectors(
        "kicad", ultra.version_pins["kicad"]
    )
    assert ultra_hints["3D STEP model export"] == _export_selectors(
        "model", ultra.version_pins["model"]
    )
    # The two remaining Ultra Librarian selectors are the exact strings its own driver uses.
    assert ultra_hints["Provider consent"] == ("input[type=checkbox][id^=consent-]",)
    assert ultra_hints["Download export"] == ("#submit-export",)

    snap = SnapMagicAdapter.capability
    snap_selectors = [selector for hint in snap.control_hints for selector in hint.selectors]
    assert 'a[name="download-modal"]' in snap_selectors
    for pin in snap.version_pins.values():
        assert f'[data-format="{pin}"]' in snap_selectors

    digikey = get_adapter("digikey")
    parent = {hint.label: hint.selectors for hint in digikey.capability.control_hints}
    route = _DIGIKEY_ULTRALIBRARIAN_ROUTE
    assert parent[f"{route.label} row"] == (f"#{route.row_ids[0]}",)
    assert parent[f"Download from {route.label}"] == (f'#{route.modal_id} [id^="btn-download-"]',)

    by_label = {
        candidate.capability.label: candidate.capability for candidate in digikey.capture_routes()
    }
    manufacturer = by_label["DigiKey · Manufacturer Provided"]
    mfr_hints = {hint.label: hint.selectors for hint in manufacturer.control_hints}
    assert mfr_hints["Download from Manufacturer Provided"] == (
        f"#{_DIGIKEY_MANUFACTURER_ROUTE.modal_id} #btn-download-mfr",
    )

    # CADENAS remains observation-only until a live download contract is measured.
    cadenas = by_label["DigiKey · CADENAS"]
    assert all("Download" not in hint.label for hint in cadenas.control_hints)


def test_a_provider_without_a_measured_control_is_left_hint_less():
    """SamacSys is person-driven and this repo has measured none of its controls."""

    from stockroom.capture.vendors import SamacSysAssistedAdapter

    assert SamacSysAssistedAdapter.capability.control_hints == ()


# ---------------------------------------------------------------------------
# Tier 2: position-only outlines over the real controls.
# ---------------------------------------------------------------------------

_EXPORT_CONTROL_BODY = (
    b"<!doctype html><title>provider</title>"
    b"<style>#submit-export{position:absolute;left:40px;top:120px;width:160px;height:44px}</style>"
    b"<button id='submit-export'>Download</button>"
)
_NO_CONTROL_BODY = b"<!doctype html><title>provider</title><p>no export panel here</p>"
_CHALLENGE_BODY = (
    b"<!doctype html><title>Just a moment...</title>"
    b"<style>#submit-export{position:absolute;left:40px;top:120px;width:160px;height:44px}"
    b".cf-turnstile{position:absolute;left:20px;top:20px;width:300px;height:65px}</style>"
    b"<div class='cf-turnstile'></div>"
    b"<button id='submit-export'>Download</button>"
)
_AMBIGUOUS_BODY = (
    b"<!doctype html><title>provider</title>"
    b"<style>.row{position:absolute;left:40px;width:160px;height:44px}</style>"
    b"<button class='row' id='btn-download-a' style='top:120px'>Download</button>"
    b"<button class='row' id='btn-download-b' style='top:200px'>Download</button>"
)

_EXPORT_HINT = ProviderControlHint(
    label="Export",
    selectors=("#submit-export",),
    source="vendors.py UltraLibrarianAdapter._export_button",
)


@pytest.mark.timeout(90)
def test_provider_hud_outlines_the_one_control_a_hint_uniquely_matches(tmp_path):
    """A box is drawn at the element's own rect, and never intercepts the person's click."""

    with (
        _static_page_server(_EXPORT_CONTROL_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(_EXPORT_HINT),
            url=url,
        ) as (_browser, page, _state),
    ):
        page.wait_for_timeout(250)
        boxes = page.evaluate(_HUD_OVERLAY_READ)
        panel = page.evaluate(_HUD_CHECKLIST_READ)
        rect = page.evaluate(
            "() => { const r = document.querySelector('#submit-export')"
            ".getBoundingClientRect();"
            " return { left: Math.round(r.left), top: Math.round(r.top),"
            " width: Math.round(r.width), height: Math.round(r.height) }; }"
        )

    assert boxes is not None
    assert len(boxes) == 1
    assert boxes[0]["label"] == "1. Export"
    assert boxes[0]["pointerEvents"] == "none"
    assert abs(boxes[0]["left"] - rect["left"]) <= 4
    assert abs(boxes[0]["top"] - rect["top"]) <= 4
    assert abs(boxes[0]["width"] - rect["width"]) <= 8
    assert abs(boxes[0]["height"] - rect["height"]) <= 8
    assert panel["hintState"] == "Outlined on this page: Export."


@pytest.mark.timeout(90)
def test_outlines_keep_the_declared_order_and_mark_only_the_first_as_next(tmp_path):
    """The route ahead is shown in order, and only the leading control is emphasised.

    Which earlier control is already satisfied cannot be known without reading its state, which is
    exactly the page content this surface may not touch, so the ordering is declared rather than
    inferred.
    """

    body = (
        b"<!doctype html><title>provider</title>"
        b"<style>button{position:absolute;left:40px;width:160px;height:40px}</style>"
        b"<button id='KiCADv6' style='top:60px'>KiCad</button>"
        b"<button id='submit-export' style='top:140px'>Download</button>"
    )
    hints = (
        ProviderControlHint(
            label="KiCad v6+ export",
            selectors=("#KiCADv6",),
            source="vendors.py version_pins['kicad']",
        ),
        _EXPORT_HINT,
    )
    with (
        _static_page_server(body) as url,
        _real_provider_hud(tmp_path, spec=_hinted_hud_spec(*hints), url=url) as (
            _browser,
            page,
            _state,
        ),
    ):
        page.wait_for_timeout(250)
        boxes = page.evaluate(_HUD_OVERLAY_READ)
        classes = page.evaluate(
            """
            () => {
              const surface = (selector) =>
                (globalThis.__stockroom_probe_shadows || []).find((root) =>
                  root.querySelector(selector),
                );
              return [...surface(".overlay").querySelectorAll(".outline")].map(
                (box) => box.className,
              );
            }
            """
        )
        panel = page.evaluate(_HUD_CHECKLIST_READ)

    assert [box["label"] for box in boxes] == ["1. KiCad v6+ export", "2. Export"]
    assert classes == ["outline next", "outline"]
    assert panel["hintState"] == "Outlined on this page: KiCad v6+ export, Export."


@pytest.mark.timeout(90)
def test_a_control_hint_that_matches_nothing_draws_no_box_and_falls_back_to_text(tmp_path):
    """Degrade, never guess. A box over the wrong control is worse than no box at all."""

    with (
        _static_page_server(_NO_CONTROL_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(_EXPORT_HINT),
            url=url,
        ) as (_browser, page, _state),
    ):
        page.wait_for_timeout(250)
        boxes = page.evaluate(_HUD_OVERLAY_READ)
        panel = page.evaluate(_HUD_CHECKLIST_READ)

    assert boxes == []
    assert panel["hintState"] == (
        "No provider control could be outlined here; follow the checklist above."
    )
    assert [step["text"] for step in panel["steps"]] == [
        "KiCad symbol and footprint",
        "STEP model",
        "Native Altium symbol and footprint",
    ]


@pytest.mark.timeout(90)
def test_a_hint_matching_more_than_one_visible_element_draws_no_box(tmp_path):
    """`[id^="btn-download-"]` is real and can match several rows; ambiguity draws nothing."""

    ambiguous = ProviderControlHint(
        label="Download",
        selectors=('[id^="btn-download-"]',),
        source="vendors.py DigiKeyUltraLibrarianAdapter._download_route_format",
    )
    with (
        _static_page_server(_AMBIGUOUS_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(ambiguous),
            url=url,
        ) as (_browser, page, _state),
    ):
        page.wait_for_timeout(250)
        boxes = page.evaluate(_HUD_OVERLAY_READ)

    assert boxes == []


@pytest.mark.timeout(90)
def test_a_security_challenge_on_the_page_suppresses_every_outline(tmp_path):
    """A challenge/CAPTCHA/login state defers to the person-handoff and outlines nothing.

    The export control on this page matches its hint exactly, so the ONLY reason no box is drawn
    is the visible challenge widget beside it.
    """

    with (
        _static_page_server(_CHALLENGE_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(_EXPORT_HINT),
            url=url,
        ) as (_browser, page, _state),
    ):
        page.wait_for_timeout(250)
        boxes = page.evaluate(_HUD_OVERLAY_READ)
        panel = page.evaluate(_HUD_CHECKLIST_READ)

    assert boxes == []
    assert panel["hintState"] == (
        "This page is showing a security check. Stockroom outlines nothing until you clear it."
    )


@pytest.mark.timeout(90)
def test_a_stockroom_security_handoff_suppresses_every_outline(tmp_path):
    """`user_clearance_issue` already decides this; the overlay only obeys it."""

    with (
        _static_page_server(_EXPORT_CONTROL_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(_EXPORT_HINT),
            url=url,
        ) as (browser, page, state),
    ):
        page.wait_for_timeout(250)
        drawn = page.evaluate(_HUD_OVERLAY_READ)
        state.set_security_hold(True)
        browser._update_provider_hud(state, 0)
        page.wait_for_timeout(250)
        held = page.evaluate(_HUD_OVERLAY_READ)
        state.set_security_hold(False)
        browser._update_provider_hud(state, 0)
        page.wait_for_timeout(250)
        released = page.evaluate(_HUD_OVERLAY_READ)

    assert len(drawn) == 1
    assert held == []
    assert len(released) == 1


@pytest.mark.timeout(90)
def test_outlines_stop_once_every_required_file_has_landed(tmp_path):
    """There is nothing left to point at once the route is complete."""

    with (
        _static_page_server(_EXPORT_CONTROL_BODY) as url,
        _real_provider_hud(
            tmp_path,
            spec=_hinted_hud_spec(_EXPORT_HINT),
            url=url,
        ) as (browser, page, state),
    ):
        page.wait_for_timeout(250)
        during = page.evaluate(_HUD_OVERLAY_READ)
        browser._update_provider_hud(state, 2, ("kicad", "model", "altium"))
        page.wait_for_timeout(250)
        after = page.evaluate(_HUD_OVERLAY_READ)

    assert len(during) == 1
    assert after == []


def test_the_provider_hud_state_read_back_reports_the_security_hold():
    state = _ProviderHudState(_provider_hud_spec())

    assert state.read_state(state.state_token) == {
        "downloadCount": 0,
        "completedFormats": [],
        "unavailableFormats": [],
        "securityHold": False,
    }
    state.set_security_hold(True)
    assert state.read_state(state.state_token) == {
        "downloadCount": 0,
        "completedFormats": [],
        "unavailableFormats": [],
        "securityHold": True,
    }
    assert state.read_state("wrong-token") == {}


def test_the_overlay_code_path_never_calls_a_page_action_primitive():
    """Position only, never act. The person performs every provider interaction.

    Anything that would operate, focus, scroll, or fill a provider control - or read its content -
    is forbidden in the one script Stockroom injects.
    """

    from stockroom.capture.browser import _PROVIDER_HUD_BOOTSTRAP

    forbidden = (
        ".click()",
        ".focus()",
        ".blur()",
        ".submit()",
        ".select()",
        ".check()",
        ".scrollIntoView",
        "dispatchEvent",
        "execCommand",
        ".value =",
        ".checked =",
        "requestSubmit",
    )
    found = [primitive for primitive in forbidden if primitive in _PROVIDER_HUD_BOOTSTRAP]
    assert found == [], f"the injected HUD can act on provider controls: {found}"
