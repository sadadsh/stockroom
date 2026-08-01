"""Authorized Ultra Librarian automation stays exact, bounded, and interruptible."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from stockroom.capture import guided, runner
from stockroom.capture.access_policy import (
    machine_access_authorized,
    machine_access_policy,
)
from stockroom.capture.browser import PlaywrightCaptureBrowser, chromium_unavailable_reason
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.pacing import DurableSlidingWindowLimiter
from stockroom.capture.vendors import (
    DriveReport,
    SnapMagicAdapter,
    UltraLibrarianAdapter,
    _challenge_issue,
    _exact_result_href,
    _is_global_blockage,
    _provider_url_allowed,
    _security_verification_issue,
    get_adapter,
)
from stockroom.credentials import MemoryCredentialStore
from stockroom.store.machine_config import MachineConfig

from .vendor_fixture_server import FIXTURES, route_fixture_vendor, serve_fixture_vendor


class _ResultNode:
    def __init__(self, href: str, text: str) -> None:
        self.href = href
        self.text = text

    def get_attribute(self, name: str):
        return self.href if name == "href" else None

    def inner_text(self):
        return self.text


class _Results:
    def __init__(self, *nodes: _ResultNode) -> None:
        self.nodes = nodes

    def count(self):
        return len(self.nodes)

    def nth(self, index: int):
        return self.nodes[index]


def test_private_evaluation_policy_is_default_off_and_both_kill_switches_win():
    policy = machine_access_policy("ultralibrarian")
    assert policy is not None
    assert policy.exception_code == "UL-PRIVATE-EVALUATION-2026-07-28"
    assert policy.max_concurrency == 1
    assert (policy.starts_per_window, policy.window_seconds) == (1, 2.0)

    off = SimpleNamespace(ul_private_evaluation_automation=False)
    on = SimpleNamespace(ul_private_evaluation_automation=True)
    assert machine_access_authorized("ultralibrarian", config=off, environ={}) is False
    assert machine_access_authorized("ultralibrarian", config=on, environ={}) is True
    assert (
        machine_access_authorized(
            "ultralibrarian",
            config=on,
            environ={"STOCKROOM_DISABLE_PROVIDER_AUTOMATION": "1"},
        )
        is False
    )
    assert (
        machine_access_authorized(
            "ultralibrarian",
            config=on,
            environ={"STOCKROOM_DISABLE_ULTRALIBRARIAN_AUTOMATION": "true"},
        )
        is False
    )


@pytest.mark.parametrize(
    ("enabled", "environment", "expected"),
    [
        (False, {}, []),
        (True, {}, ["ultralibrarian"]),
        (True, {"STOCKROOM_DISABLE_PROVIDER_AUTOMATION": "1"}, []),
        (True, {"STOCKROOM_DISABLE_ULTRALIBRARIAN_AUTOMATION": "yes"}, []),
    ],
)
def test_runner_and_coverage_include_ul_only_under_current_machine_authorization(
    monkeypatch,
    tmp_path,
    enabled,
    environment,
    expected,
):
    config = SimpleNamespace(ul_private_evaluation_automation=enabled)
    monkeypatch.setattr(
        runner,
        "machine_access_authorized",
        lambda key: machine_access_authorized(
            key,
            config=config,
            environ=environment,
        ),
    )
    monkeypatch.setattr(runner, "build_sources", lambda _ctx, **_options: [])

    assert runner._automatic_provider_keys(None) == expected
    ctx = SimpleNamespace(
        profile=SimpleNamespace(
            library=SimpleNamespace(parts_dir=tmp_path),
        )
    )
    report = runner.coverage(ctx)
    assert report["sources"] == expected
    assert ("ultralibrarian" in report["assisted_sources"]) is (not expected)


def test_machine_authorization_flag_round_trips_as_public_config(tmp_path):
    path = tmp_path / "config.json"
    store = MemoryCredentialStore("stockroom-ul-policy-test")
    config = MachineConfig(
        ul_username="owner@example.test",
        ul_password="credential-manager-only",
        ul_private_evaluation_automation=True,
    )
    config.save(path, credential_store=store)

    payload = json.loads(path.read_text(encoding="utf-8"))
    loaded = MachineConfig.load(path, credential_store=store)
    assert payload["ul_private_evaluation_automation"] is True
    assert "ul_password" not in payload
    assert loaded.ul_private_evaluation_automation is True
    assert loaded.ul_password == "credential-manager-only"
    assert "credential-manager-only" not in repr(loaded)


def test_provider_spacing_survives_limiter_reconstruction_and_is_cancellable(tmp_path):
    now = [1_000.0]
    slept: list[float] = []

    def sleep(seconds: float):
        slept.append(seconds)
        now[0] += seconds

    ledger = tmp_path / "Ultra Librarian" / "Starts.json"
    first_run = DurableSlidingWindowLimiter(
        ledger,
        1,
        2,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    assert first_run.acquire() is True

    restarted_run = DurableSlidingWindowLimiter(
        ledger,
        1,
        2,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    assert restarted_run.acquire() is True
    assert sum(slept) >= 2.0

    assert restarted_run.acquire(should_cancel=lambda: True) is False


def test_ultra_drive_requires_exact_identity_before_touching_the_page():
    class UntouchedPage:
        def locator(self, _selector):
            raise AssertionError("provider page must not be inspected without exact identity")

    report = UltraLibrarianAdapter().drive(
        UntouchedPage(),
        ["kicad", "model", "altium"],
    )

    assert report.blocked is True
    assert report.missed == ["kicad", "model", "altium"]
    assert "exact expected manufacturer and MPN" in report.message


def test_resolver_url_is_exact_and_official_before_browser_navigation():
    adapter = get_adapter("ultralibrarian")
    assert adapter is not None
    record = SimpleNamespace(manufacturer="Acme", mpn="ABC-1")

    assert (
        guided._resolved_provider_url_issue(
            adapter,
            "https://app.ultralibrarian.com/search?queryText=ABC-1",
            record,
        )
        == ""
    )
    assert "exact requested MPN" in guided._resolved_provider_url_issue(
        adapter,
        "https://app.ultralibrarian.com/search?queryText=ABC-10",
        record,
    )
    assert "outside its official provider origin" in guided._resolved_provider_url_issue(
        adapter,
        "https://lookalike.example/search?queryText=ABC-1",
        record,
    )


def test_guided_machine_mode_rejects_user_only_and_unchecked_adapters(tmp_path):
    snapmagic = get_adapter("snapmagic")
    ultra = get_adapter("ultralibrarian")
    assert snapmagic is not None
    assert ultra is not None

    machine_source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="snapmagic",
        download_root=tmp_path,
        user_driven=False,
    )
    assert "not authorized for machine-driven capture" in machine_source._machine_access_issue(
        snapmagic
    )

    unchecked_source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path,
        user_driven=False,
    )
    assert "explicit live machine-authorization" in unchecked_source._machine_access_issue(ultra)

    selected_provider_source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="snapmagic",
        download_root=tmp_path,
        operator_authorized=True,
    )
    assert selected_provider_source._machine_access_issue(snapmagic) == ""


def test_ultra_result_gate_requires_the_exact_manufacturer_and_mpn():
    exact = "/details/catalogue/Acme/ABC-1?uid=right"
    href, error = _exact_result_href(
        _Results(
            _ResultNode("/details/catalogue/Other/ABC-1?uid=wrong", "ABC-1"),
            _ResultNode(exact, "ABC-1"),
            _ResultNode("/details/catalogue/Acme/ABC-10?uid=near", "ABC-10"),
        ),
        "ABC-1",
        expected_manufacturer="Acme",
        vendor_key="ultralibrarian",
    )
    assert (href, error) == (exact, "")

    href, error = _exact_result_href(
        _Results(_ResultNode("/details/catalogue/Other/ABC-1", "ABC-1")),
        "ABC-1",
        expected_manufacturer="Acme",
        vendor_key="ultralibrarian",
    )
    assert href == ""
    assert "different manufacturer" in error
    assert "no near-match was selected" in error


class _NoNodes:
    @property
    def first(self):
        return self

    def count(self):
        return 0


class _OneNode(_NoNodes):
    def count(self):
        return 1

    def is_visible(self):
        return True


class _OneHiddenNode(_OneNode):
    """Present in the document, not shown. Ultra Librarian ships a collapsed sign-in form."""

    def is_visible(self):
        return False


class _Frame:
    def get_attribute(self, name: str):
        return "https://challenges.cloudflare.com/turnstile" if name == "src" else None

    def is_visible(self):
        return True


class _Frames:
    @property
    def first(self):
        return self

    def count(self):
        return 1

    def nth(self, index: int):
        assert index == 0
        return _Frame()


class _ChallengePage:
    url = "https://app.ultralibrarian.com/search?queryText=ABC-1"

    def locator(self, selector: str):
        if selector == "iframe":
            return _Frames()
        return _NoNodes()

    def title(self):
        return "Just a moment"

    def inner_text(self, selector: str):
        assert selector == "body"
        return "Verify you are human"


def test_ultra_challenge_is_a_user_handoff_not_an_automation_attempt():
    report = UltraLibrarianAdapter().drive(
        _ChallengePage(),
        ["kicad", "model", "altium"],
        expected_manufacturer="Acme",
        expected_mpn="ABC-1",
    )

    assert report.submitted is False
    assert report.blocked is True
    assert report.requires_user_clearance is True
    assert "confirm you are human" in report.message


def test_snapmagic_challenge_is_a_user_handoff_not_a_closed_browser():
    report = SnapMagicAdapter().drive(
        _ChallengePage(),
        ["kicad"],
        expected_manufacturer="Acme",
        expected_mpn="ABC-1",
    )

    assert report.submitted is False
    assert report.blocked is True
    assert report.requires_user_clearance is True
    assert "confirm you are human" in report.message


@pytest.mark.parametrize(
    "evidence",
    [
        "https://www.google.com/recaptcha/api2/anchor",
        "https://hcaptcha.com/1/api.js",
        "I’m not a robot",
    ],
)
def test_standard_captcha_signals_are_detected_for_handoff(evidence):
    page = _ChallengePage()
    page.title = lambda: evidence
    assert "confirm you are human" in _challenge_issue(page, "Ultra Librarian")


def test_hidden_challenge_integration_does_not_pause_a_normal_result_page():
    class HiddenFrame(_Frame):
        def is_visible(self):
            return False

    class HiddenFrames(_Frames):
        def nth(self, index: int):
            assert index == 0
            return HiddenFrame()

    page = _ChallengePage()
    page.title = lambda: "Search | Ultra Librarian"
    page.inner_text = lambda _selector: "Texas Instruments TPD6E05U06RVZR Models Available"
    page.locator = lambda selector: HiddenFrames() if selector == "iframe" else _NoNodes()

    assert _challenge_issue(page, "Ultra Librarian") == ""


@pytest.mark.parametrize(
    "body",
    [
        "Enter the code from your authenticator app",
        "Use your passkey to verify your identity",
        "Approve sign-in with your security key",
    ],
)
def test_mfa_and_passkey_signals_are_detected_for_handoff(body):
    page = _LoginPage()
    page.inner_text = lambda _selector: body
    issue = _security_verification_issue(page, "Ultra Librarian")
    assert "security verification" in issue
    assert "never operates" in issue


class _LoginPage:
    url = "https://sso.ultralibrarian.com/Account/Login"

    def locator(self, selector: str):
        if selector == "#Username":
            return _OneNode()
        return _NoNodes()

    def title(self):
        return "Sign In"

    def inner_text(self, selector: str):
        assert selector == "body"
        return "Sign in to Ultra Librarian"


class _AuthenticatedPage(_LoginPage):
    url = "https://app.ultralibrarian.com/search?queryText=ABC-1"

    def locator(self, _selector: str):
        return _NoNodes()

    def goto(self, *_args, **_options):
        raise AssertionError("an authenticated persistent profile must not navigate to login")


def test_ultra_sign_in_reuses_an_authenticated_persistent_profile():
    assert (
        UltraLibrarianAdapter().sign_in(
            _AuthenticatedPage(),
            "owner@example.test",
            "saved-secret",
        )
        == ""
    )


def test_ultra_sign_in_hands_off_security_before_form_navigation():
    issue = UltraLibrarianAdapter().sign_in(
        _ChallengePage(),
        "owner@example.test",
        "saved-secret",
    )
    assert "confirm you are human" in issue


def test_ultra_login_or_2fa_state_is_a_handoff_not_a_failed_part():
    report = UltraLibrarianAdapter().drive(
        _LoginPage(),
        ["kicad", "model", "altium"],
        expected_manufacturer="Acme",
        expected_mpn="ABC-1",
    )

    assert report.submitted is False
    assert report.blocked is True
    assert report.requires_user_clearance is True
    assert "CAD format list did not open" in report.message


def test_identity_urls_require_the_official_provider_host():
    assert _provider_url_allowed(
        "ultralibrarian",
        "https://app.ultralibrarian.com/details/Acme/ABC-1",
    )
    assert not _provider_url_allowed(
        "ultralibrarian",
        "https://lookalike.example/details/Acme/ABC-1",
    )


class _Count:
    def __init__(self, count: int) -> None:
        self._count = count

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def wait_for(self, **_options):
        return None


class _RedirectsToWrongPart:
    def __init__(self) -> None:
        self.url = "https://app.ultralibrarian.com/details/Acme/ABC-1"
        self.has_exports = False

    def locator(self, selector: str):
        if selector == "input[name=exports]":
            return _Count(1 if self.has_exports else 0)
        if selector == "iframe":
            return _Count(0)
        return _Count(0)

    def goto(self, _url: str, **_options):
        self.url = "https://app.ultralibrarian.com/details/Other/XYZ?open=exports"
        self.has_exports = True

    def title(self):
        return ""

    def inner_text(self, _selector: str):
        return ""


def test_export_navigation_redirect_to_a_wrong_part_is_rejected_before_selection():
    page = _RedirectsToWrongPart()
    issue = UltraLibrarianAdapter().open_panel(
        page,
        expected_manufacturer="Acme",
        expected_mpn="ABC-1",
    )
    assert "not requested MPN" in issue or "different manufacturer" in issue
    assert page.has_exports is True


def test_guided_drive_hands_security_to_the_user_then_resumes_with_exact_identity(
    monkeypatch,
    tmp_path,
):
    calls: list[tuple[str, str]] = []

    def fake_drive(
        _browser,
        _page,
        _adapter,
        _formats,
        _url,
        _timeout_s=None,
        *,
        expected_manufacturer="",
        expected_mpn="",
    ):
        calls.append((expected_manufacturer, expected_mpn))
        if len(calls) == 1:
            return (
                DriveReport(
                    missed=["kicad", "model", "altium"],
                    blocked=True,
                    requires_user_clearance=True,
                    message="security gate",
                ),
                "security gate",
            )
        return DriveReport(selected=["kicad", "model"], submitted=True), None

    monkeypatch.setattr(guided, "drive_formats", fake_drive)

    class Limiter:
        count = 0

        def acquire(self):
            self.count += 1

    class Browser:
        def __init__(self):
            self.handoffs = 0

        def wait_for_user_clearance(self, _page, **options):
            self.handoffs += 1
            assert options["provider_label"] == "Ultra Librarian"
            assert options["manufacturer"] == "Acme"
            assert options["mpn"] == "ABC-1"
            return True

    limiter = Limiter()
    browser = Browser()
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path,
        rate_limiter=limiter,
        machine_access_check=lambda: True,
    )
    session = guided._Session(browser=browser, ctx_manager=None, page=object())

    report, failure = source._drive_automated(
        session,
        object(),
        UltraLibrarianAdapter(),
        ["kicad", "model", "altium"],
        "https://app.ultralibrarian.com/search?queryText=ABC-1",
        "Acme",
        "ABC-1",
    )

    assert failure is None
    assert report.submitted is True
    assert browser.handoffs == 1
    assert limiter.count == 2
    assert calls == [("Acme", "ABC-1"), ("Acme", "ABC-1")]


def test_saved_credentials_run_before_an_ordinary_signed_out_handoff(monkeypatch, tmp_path):
    state = {"signed_in": False, "sign_ins": 0}

    class Adapter:
        capability = SimpleNamespace(
            key="ultralibrarian",
            label="Ultra Librarian",
            needs_login=True,
        )

        def signed_in(self, _page):
            return state["signed_in"]

        def sign_in(self, _page, _username, _password):
            state["sign_ins"] += 1
            state["signed_in"] = True
            return ""

        def user_clearance_issue(self, _page):
            return "" if state["signed_in"] else "Sign in to Ultra Librarian."

    class Page:
        url = "https://app.ultralibrarian.com/search?queryText=ABC-1"

        def title(self):
            return "Search | Ultra Librarian"

        def inner_text(self, selector):
            assert selector == "body"
            return "Texas Instruments ABC-1 Models Available"

        def locator(self, _selector):
            return _NoNodes()

    class Browser:
        def wait_for_user_clearance(self, *_args, **_kwargs):
            raise AssertionError("ordinary sign-in must use saved credentials before handoff")

    adapter = Adapter()
    monkeypatch.setattr(guided, "get_adapter", lambda _key: adapter)
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path,
        credentials=lambda _key: ("owner@example.test", "saved-secret"),
        machine_access_check=lambda: True,
    )
    session = guided._Session(browser=Browser(), ctx_manager=None, page=Page())

    outcome = source._prepare_sign_in(session, session.page, adapter, "Acme", "ABC-1")

    assert outcome is None
    assert state == {"signed_in": True, "sign_ins": 1}


def test_authorization_revocation_stops_before_the_post_handoff_retry(monkeypatch, tmp_path):
    calls = 0

    def fake_drive(
        _browser,
        _page,
        _adapter,
        _formats,
        _url,
        _timeout_s=None,
        *,
        expected_manufacturer="",
        expected_mpn="",
    ):
        nonlocal calls
        calls += 1
        return (
            DriveReport(
                missed=["kicad"],
                blocked=True,
                requires_user_clearance=True,
                message="security gate",
            ),
            "security gate",
        )

    monkeypatch.setattr(guided, "drive_formats", fake_drive)

    class Browser:
        def wait_for_user_clearance(self, *_args, **_options):
            return True

    checks = iter((True, True, True, False))
    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path,
        machine_access_check=lambda: next(checks),
    )
    session = guided._Session(browser=Browser(), ctx_manager=None, page=object())

    report, failure = source._drive_automated(
        session,
        object(),
        UltraLibrarianAdapter(),
        ["kicad"],
        "https://app.ultralibrarian.com/search?queryText=ABC-1",
        "Acme",
        "ABC-1",
    )

    assert calls == 1
    assert report.blocked is True
    assert "authorization is no longer active" in failure


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_security_handoff_hud_survives_until_the_gate_clears_then_dismisses(tmp_path):
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)
    with browser.session() as page:
        page.set_content(
            """
            <body>Verify you are human</body>
            <script>
              new MutationObserver(() => {
                if (document.querySelector('aside[aria-label="Stockroom security handoff"]')) {
                  document.documentElement.dataset.handoffSeen = "yes";
                }
              }).observe(document.documentElement, {childList: true, subtree: true});
              setTimeout(() => { document.body.textContent = "Exact part page"; }, 250);
            </script>
            """
        )
        cleared = browser.wait_for_user_clearance(
            page,
            provider_label="Ultra Librarian",
            manufacturer="Acme",
            mpn="ABC-1",
            message="Ultra Librarian needs a human check.",
            issue_detector=lambda: _challenge_issue(page, "Ultra Librarian"),
            timeout_s=3,
            poll_interval_s=0.05,
        )
        handoff_seen = page.get_attribute("html", "data-handoff-seen")
        remaining = page.locator('aside[aria-label="Stockroom security handoff"]').count()

    assert cleared is True
    assert handoff_seen == "yes"
    assert remaining == 0


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_exact_native_choice_clears_stale_legacy_state_and_brokers_every_download(tmp_path):
    base, shutdown = serve_fixture_vendor("ul-export-panel-native.html")
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Downloads",
        profile_dir=tmp_path / "Profile",
        provider_key="ultralibrarian",
        headless=True,
    )
    staging = tmp_path / "Staging"
    staging.mkdir()
    broker = DownloadBroker(
        DownloadTask(
            task_id="part-1",
            manufacturer_key="Acme",
            mpn_canonical="ABC-1",
            staging_root=staging,
        )
    )
    try:
        with browser.session():
            with browser.task_page(broker) as page:
                page.goto(
                    route_fixture_vendor(
                        page,
                        base,
                        manufacturer="Acme",
                        mpn="ABC-1",
                    )
                )
                report = UltraLibrarianAdapter().drive(
                    page,
                    ["kicad", "model", "altium"],
                    expected_manufacturer="Acme",
                    expected_mpn="ABC-1",
                )
                broker.wait_for_playwright(
                    page,
                    minimum=3,
                    settle_seconds=0.25,
                )
                checked = page.eval_on_selector_all(
                    "input[name=exports]:checked",
                    "nodes => nodes.map(node => node.id)",
                )
    finally:
        shutdown()

    assert report.selected == ["kicad", "model", "altium"]
    assert report.missed == []
    assert checked == ["KiCADv6", "ThreeDModel", "AltiumNativeCurrent"]
    assert {receipt.suggested_name for receipt in broker.receipts} == {
        "native-kicad.zip",
        "native-altium.zip",
        "native-step.step",
    }
    assert all(receipt.task_id == "part-1" for receipt in broker.receipts)


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_native_unavailable_downloads_kicad_and_step_but_never_legacy_altium(tmp_path):
    base, shutdown = serve_fixture_vendor()
    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)
    try:
        with browser.session() as page:
            page.goto(
                route_fixture_vendor(
                    page,
                    base,
                    manufacturer="Acme",
                    mpn="ABC-1",
                )
            )
            report = UltraLibrarianAdapter().drive(
                page,
                ["kicad", "model", "altium"],
                expected_manufacturer="Acme",
                expected_mpn="ABC-1",
            )
            page.wait_for_timeout(500)
            checked = page.eval_on_selector_all(
                "input[name=exports]:checked",
                "nodes => nodes.map(node => node.id)",
            )
    finally:
        shutdown()

    assert report.selected == ["kicad", "model"]
    assert report.missed == ["altium"]
    assert "does not offer Altium Designer (Native)" in report.message
    assert "legacy Altium script, .lia, and P-CAD exports were not selected" in report.message
    assert sorted(checked) == ["KiCADv6", "MfrThreeDModel"]


# ---------------------------------------------------------------------------
# Ordinary page variation must not end an authorized unattended capture.
#
# Ultra Librarian is the ONE provider allowed to run without a person here, so every avoidable
# driver failure spends the owner's attention on a manual provider window. The three cases below
# were each reproduced against the REAL captured export panel
# (`tests/backend/host/fixtures/ul-export-panel.html`) served at an official-looking Ultra
# Librarian URL, with the Bootstrap rules the captured markup depends on but does not carry.
# ---------------------------------------------------------------------------

_REAL_PANEL = (FIXTURES / "ul-export-panel.html").read_text(encoding="utf-8", errors="replace")

# The captured panel predates Ultra Librarian's 2025-10-16 native Altium export, so the row the
# machine path is pinned to is added here in the panel's own row shape.
_NATIVE_ALTIUM_ROW = """
                <div class="d-flex custom-control custom-checkbox pb-2">
                    <input id="AltiumNativeCurrent" name="exports" type="checkbox" value="60"
                           class="custom-control-input export-option">
                    <label for="AltiumNativeCurrent"
                           class="custom-control-label d-flex align-items-center flex-grow-1">
                        Altium Designer (Native)
                    </label>
                </div>
"""

# The captured HTML references these Bootstrap 4 classes but the stylesheet was not captured.
# Without them every accordion is expanded and every checkbox is an ordinary visible control,
# which is exactly why a fixture-only test cannot see the failures below.
_BOOTSTRAP_RULES = """
<style>
  .collapse { display: none; }
  .collapse.show { display: block; }
  .custom-control-input { position: absolute; z-index: -1; opacity: 0; }
  .custom-control { position: relative; display: block; padding-left: 1.5rem; }
</style>
"""

# Stands in for Ultra Librarian's own submit script, which was not captured and may not be
# redistributed: it enables `#submit-export` once an export is chosen and records that the
# vendor's OWN control actually ran, so a test can tell "clicked" from "exported".
_VENDOR_SUBMIT_JS = """
<script data-stockroom-harness="stands in for the vendor's submit JS; NOT vendor markup">
(function(){
  var submit = document.getElementById('submit-export');
  function sync(){
    submit.classList.toggle(
      'disabled',
      document.querySelectorAll('input[name=exports]:checked').length === 0
    );
  }
  document.addEventListener('change', sync);
  sync();
  submit.addEventListener('click', function(){
    if (submit.classList.contains('disabled')) return;
    window.__ulExported = (window.__ulExported || 0) + 1;
  });
})();
</script>
"""


def _real_panel_page(*, prefix: str = "", suffix: str = "") -> str:
    """The real captured panel, its missing Bootstrap rules, and the native Altium row."""

    anchor = (
        '<div class="d-flex custom-control custom-checkbox pb-2">\n'
        '                    <input id="AltiumDesigner"'
    )
    assert anchor in _REAL_PANEL, "captured panel no longer carries the legacy Altium row"
    panel = _REAL_PANEL.replace(anchor, _NATIVE_ALTIUM_ROW + anchor, 1)
    return _BOOTSTRAP_RULES + prefix + panel + _VENDOR_SUBMIT_JS + suffix


def _drive_real_panel(tmp_path, html: str):
    """Drive the authorized adapter over one served panel and report what the vendor observed."""

    browser = PlaywrightCaptureBrowser(download_dir=tmp_path / "Downloads", headless=True)
    with browser.session() as page:
        page.route(
            "https://app.ultralibrarian.com/**",
            lambda route: route.fulfill(
                status=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                body=html,
            ),
        )
        page.goto("https://app.ultralibrarian.com/details/fixture/Acme/ABC-1?open=exports")
        report = UltraLibrarianAdapter().drive(
            page,
            ["kicad", "model", "altium"],
            expected_manufacturer="Acme",
            expected_mpn="ABC-1",
        )
        exported = page.evaluate("window.__ulExported || 0")
        checked = page.eval_on_selector_all(
            "input[name=exports]:checked",
            "nodes => nodes.map(node => node.id)",
        )
    return report, exported, checked


_COOKIE_BANNER = """
<div id="cookie-wall" style="position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.4)">
  <div style="background:#fff;padding:2rem">
    We use cookies to improve your experience. <button id="cookie-ok">Accept</button>
  </div>
</div>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_ordinary_overlay_does_not_end_the_authorized_capture(tmp_path):
    """A cookie banner is not a reason to send the owner to a manual provider window.

    Expanding a tool accordion is a convenience: the export checkboxes are selected and READ BACK
    through the panel's own controls whether or not their section is open. An ordinary overlay
    that merely intercepts pointer events must therefore cost nothing, rather than burning a
    default 30s actionability timeout per section and then ending the drive.
    """

    report, exported, checked = _drive_real_panel(
        tmp_path,
        _real_panel_page(prefix=_COOKIE_BANNER),
    )

    assert report.selected == ["kicad", "model", "altium"]
    assert report.missed == []
    assert report.submitted is True
    assert exported == 1
    assert sorted(checked) == ["AltiumNativeCurrent", "KiCADv6", "MfrThreeDModel"]


# Ultra Librarian renders the panel's controls before its Download link is attached. Nothing in
# the driver waited for it, so a slow render read as a provider-wide "no Download button" state.
_LATE_DOWNLOAD_BUTTON_JS = """
<script>
(function(){
  var submit = document.getElementById('submit-export');
  var holder = submit.parentNode;
  submit.remove();
  setTimeout(function(){ holder.appendChild(submit); }, 1200);
})();
</script>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_late_download_button_is_awaited_instead_of_tripping_the_batch_breaker(tmp_path):
    """A Download link that attaches a moment later is a render, not a provider-wide blockage.

    `_is_global_blockage` matches "download button is not on this page", so reporting it trips the
    batch circuit breaker and abandons every remaining part in the run - for a part whose formats
    were all successfully selected.
    """

    report, exported, checked = _drive_real_panel(
        tmp_path,
        _real_panel_page(suffix=_LATE_DOWNLOAD_BUTTON_JS),
    )

    assert report.selected == ["kicad", "model", "altium"]
    assert report.submitted is True
    assert report.blocked is False
    assert exported == 1
    assert _is_global_blockage(report.message) is False
    assert sorted(checked) == ["AltiumNativeCurrent", "KiCADv6", "MfrThreeDModel"]


# A real security control, NOT an ordinary banner. Stockroom must never operate one.
_TURNSTILE_OVERLAY = """
<div id="challenge-wall" style="position:fixed;inset:0;z-index:9999;background:#fff">
  <p>Verify you are human</p>
  <iframe src="https://challenges.cloudflare.com/turnstile/v0/api.js" width="300" height="65">
  </iframe>
</div>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_security_challenge_over_the_panel_is_handed_to_the_person_not_clicked_through(tmp_path):
    """Recovering from an intercepted click must never become a way past a security control.

    The fix for an ordinary overlay activates the vendor's own Download control in page context.
    That recovery is gated on there being no security state, so a challenge rendered over the
    export panel hands off to the person and the vendor's export never runs.
    """

    report, exported, _checked = _drive_real_panel(
        tmp_path,
        _real_panel_page(prefix=_TURNSTILE_OVERLAY),
    )

    assert report.submitted is False
    assert report.requires_user_clearance is True
    assert report.blocked is True
    assert "confirm you are human" in report.message
    assert exported == 0


# The captured panel's consent is `class="custom-control-input consentRequest required"`, and
# Ultra Librarian will not export without it.
_UNACCEPTABLE_CONSENT_JS = """
<script>
document.getElementById('consent-TIInfoShare').disabled = true;
</script>
"""


@pytest.mark.skipif(
    chromium_unavailable_reason() is not None,
    reason=str(chromium_unavailable_reason()),
)
def test_a_required_consent_that_will_not_stick_is_named_not_waited_out(tmp_path):
    """Say why the export cannot run instead of clicking a gated control and blaming the vendor.

    Submitting without the required consent produces no download, so the run spends its full
    120s backstop and then reports "Ultra Librarian did not deliver a file" - which points at the
    provider rather than at the consent that was never accepted.
    """

    report, exported, checked = _drive_real_panel(
        tmp_path,
        _real_panel_page(suffix=_UNACCEPTABLE_CONSENT_JS),
    )

    assert report.selected == ["kicad", "model", "altium"]
    assert report.submitted is False
    assert exported == 0
    assert "requires a consent this page would not accept" in report.message
    assert "consent-TIInfoShare" in report.message
    # The formats were genuinely selected; the consent is the only thing missing.
    assert sorted(checked) == ["AltiumNativeCurrent", "KiCADv6", "MfrThreeDModel"]
    # A per-manufacturer consent is not a provider-wide outage: the batch must keep going.
    assert report.blocked is False
    assert _is_global_blockage(report.message) is False


class _PartPage:
    """An ordinary Ultra Librarian part page: the export panel, and the header Sign In anchor.

    Every Ultra Librarian page carries that anchor, signed in or out.
    """

    url = "https://app.ultralibrarian.com/details/abc-1"

    def __init__(self, *, username_node=None):
        self._username_node = username_node

    def locator(self, selector: str):
        if selector == 'a[href*="/Account/Login"]':
            return _OneNode()
        if selector == "#Username" and self._username_node is not None:
            return self._username_node
        return _NoNodes()

    def title(self):
        return "ABC-1 | Ultra Librarian"

    def inner_text(self, selector: str):
        assert selector == "body"
        return "ABC-1\nGet CAD Model\nDownload\nSign In"


def test_a_header_sign_in_link_is_not_a_security_gate():
    """The part page a person is looking at must not be reported as a challenge.

    Counting the header's Sign In anchor paused capture on every ordinary Ultra Librarian page
    and told the person to clear a security check that was never on screen, which is exactly the
    state the automatic route exists to avoid.
    """
    assert UltraLibrarianAdapter().user_clearance_issue(_PartPage()) == ""


def test_a_collapsed_sign_in_form_is_not_a_security_gate():
    page = _PartPage(username_node=_OneHiddenNode())
    assert UltraLibrarianAdapter().user_clearance_issue(page) == ""


def test_a_visible_sign_in_form_is_still_a_security_gate():
    page = _PartPage(username_node=_OneNode())
    issue = UltraLibrarianAdapter().user_clearance_issue(page)
    assert "sign-in" in issue
    assert "never operates" in issue


def test_the_login_destination_is_still_a_security_gate():
    assert "sign-in" in UltraLibrarianAdapter().user_clearance_issue(_LoginPage())
