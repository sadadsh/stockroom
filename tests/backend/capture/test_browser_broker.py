"""Windows production browser policy and provider-profile ownership."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import quote

import pytest

from stockroom.capture.browser import (
    CaptureBrowserError,
    PlaywrightCaptureBrowser,
    ProviderHudSpec,
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
            remembered = page.evaluate(
                "localStorage.getItem('stockroom-session-probe')"
            )

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

    def invoke_hud_action(self, action: str, *, token: str | None = None) -> bool:
        assert len(self.bindings) == 1
        assert self.evaluations
        callback = next(iter(self.bindings.values()))
        return callback(
            SimpleNamespace(page=self),
            action,
            token if token is not None else self.evaluations[0][1]["actionToken"],
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
    )
    return result, broker


def test_user_capture_hud_is_injected_before_navigation_and_survives_without_dom_inspection(
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
    assert '"Resume Stockroom"' in bootstrap
    assert '"Use Another Provider"' in bootstrap
    assert '"Close Capture"' in bootstrap

    # The only page code Stockroom installs creates and updates its own closed-shadow surface.
    # The fake deliberately has no locator/query APIs, and the script carries no provider-content,
    # credential, or storage inspection primitive.
    provider_inspection_primitives = (
        "querySelector",
        "getElementsBy",
        "document.body",
        "innerHTML",
        "innerText",
        "document.cookie",
        "localStorage",
        "sessionStorage",
        "navigator.credentials",
        'input[type="password"]',
    )
    assert all(value not in bootstrap for value in provider_inspection_primitives)


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

    def act_once() -> None:
        assert page.invoke_hud_action(action, token="not-the-hud-token") is False
        assert page.invoke_hud_action(action) is True
        assert page.invoke_hud_action(action) is False

    page.on_goto = act_once
    result, _broker = _hud_capture(tmp_path, page)

    assert result.status == expected_status


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
