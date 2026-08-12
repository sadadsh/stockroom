"""The source host's provider controller and in-window navigation safeguards.

These cover ``python -m stockroom.host.run``. The source host retains task-bound provider state
and in-window navigation safety but mounts no global tabs or page controls.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import stockroom.host.window as host_window
from stockroom.host.window import (
    _NATIVE_DOWNLOAD_EVENTS,
    _begin_native_webview_download_lease,
    _discard_native_webview_downloads,
    _end_native_webview_download_lease,
    _install_in_window_new_window_handler,
    _install_silent_webview2_download_handler,
)
from stockroom.host.window_chrome import (
    MAXIMUM_TAB_LENGTH,
    PROVIDER_TAB_FALLBACK,
    ProviderChromeState,
    WindowChrome,
    new_window_url_allowed,
    resolve_provider_tab_label,
)

APP = "http://127.0.0.1:53119"


# --- the two-tab model ----------------------------------------------------------------------


def test_a_window_with_no_provider_route_shows_the_stockroom_tab_alone():
    state = ProviderChromeState()

    assert state.is_stockroom_selected is True
    assert state.has_provider_tab is False
    assert state.is_provider_selected is False
    # Nothing dead-but-clickable: with no page open the page controls are not on screen.
    assert state.controls_visible is False
    assert state.back_enabled is False
    assert state.forward_enabled is False
    assert state.refresh_enabled is False


def test_page_controls_stay_absent_even_when_a_page_reports_history():
    state = ProviderChromeState()

    state.set_history(can_go_back=True, can_go_forward=True)

    assert state.back_enabled is False
    assert state.forward_enabled is False


def test_a_provider_route_adds_one_tab_without_stealing_the_selection():
    state = ProviderChromeState()

    state.open_provider("DigiKey")

    assert state.has_provider_tab is True
    assert state.provider_tab_text == "DigiKey"
    assert state.is_stockroom_selected is True
    assert state.is_provider_selected is False
    assert state.controls_visible is False


def test_selecting_each_tab_selects_exactly_that_tab():
    state = ProviderChromeState()
    state.open_provider("Ultra Librarian")

    state.select_provider()
    assert state.is_provider_selected is True
    assert state.is_stockroom_selected is False

    state.select_stockroom()
    assert state.is_stockroom_selected is True
    assert state.is_provider_selected is False


def test_page_controls_belong_to_the_selected_provider_tab():
    state = ProviderChromeState()
    state.open_provider("SamacSys")
    state.set_history(can_go_back=True, can_go_forward=False)

    state.select_provider()

    assert state.controls_visible is True
    assert state.refresh_enabled is True
    assert state.back_enabled is True
    assert state.forward_enabled is False

    state.select_stockroom()
    assert state.controls_visible is False
    assert state.back_enabled is False
    assert state.refresh_enabled is False


def test_closing_the_route_removes_the_tab_and_leaves_stockroom_selected():
    state = ProviderChromeState()
    state.open_provider("DigiKey")
    state.select_provider()
    state.set_url("https://www.digikey.com/en/products")
    state.set_status("Loading")
    state.set_history(can_go_back=True, can_go_forward=True)

    state.close_provider()

    assert state.has_provider_tab is False
    assert state.is_stockroom_selected is True
    assert state.url == ""
    assert state.status == ""
    assert state.back_enabled is False
    assert state.controls_visible is False


def test_selecting_a_provider_tab_that_does_not_exist_falls_back_to_stockroom():
    state = ProviderChromeState()

    state.select_provider()

    assert state.is_stockroom_selected is True


def test_a_transient_about_document_does_not_blank_the_address():
    state = ProviderChromeState()
    state.open_provider("DigiKey")
    state.set_url("https://www.digikey.com/en/products/detail/x")

    state.set_url("about:blank")

    assert state.url == "https://www.digikey.com/en/products/detail/x"


# --- the tab's name -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "title", "provider_id", "expected"),
    [
        ("https://www.digikey.com/en/products", "Ignored Title", "", "DigiKey"),
        ("", "", "ultralibrarian", "Ultra Librarian"),
        ("", "", "cadenas", "CADENAS"),
        ("", "", "newvendor", "newvendor"),
        ("https://www.mouser.com/c/", "", "", "Mouser"),
        ("https://componentsearchengine.com/x", "", "", "SamacSys"),
        ("https://example.invalid/x", "  Some   Page  Title ", "", "Some Page Title"),
        ("https://example.invalid/x", "", "", "example.invalid"),
        ("https://www.example.invalid/x", "", "", "example.invalid"),
        ("", "", "", PROVIDER_TAB_FALLBACK),
        (None, None, None, PROVIDER_TAB_FALLBACK),
    ],
)
def test_the_tab_is_named_for_the_provider_then_the_page_then_the_host(
    url,
    title,
    provider_id,
    expected,
):
    assert resolve_provider_tab_label(url, title, provider_id) == expected


def test_the_tab_name_stays_short_enough_to_leave_room_for_the_address():
    resolved = resolve_provider_tab_label(
        url="https://example.invalid/x",
        document_title="a" * 200,
    )

    assert len(resolved) == MAXIMUM_TAB_LENGTH
    assert resolved.endswith("…")


def test_mount_keeps_the_provider_controller_without_global_window_controls():
    chrome = WindowChrome()
    form = object()

    assert chrome.mount(form) is True
    assert chrome.mounted is True
    source = inspect.getsource(WindowChrome.mount)
    assert "WinForms" not in source
    assert "Controls.Add" not in source


# --- nothing reaches the operating system's browser -----------------------------------------


class _Edge:
    """Stands in for pywebview's EdgeChrome, whose own handler opens the default browser."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.loaded = []

    def load_url(self, url):
        self.loaded.append(url)

    def on_new_window_request(self, _sender, args):
        type(self).escaped.append(str(args.Uri))


class _Args:
    def __init__(self, uri: str) -> None:
        self.Uri = uri
        self.Handled = False

    def get_Uri(self):
        return self.Uri

    def set_Handled(self, value):
        self.Handled = bool(value)


def _edge_double():
    return type("Edge", (_Edge,), {"escaped": []})


@pytest.fixture()
def app_origin(monkeypatch):
    monkeypatch.setattr(host_window, "_APP_ORIGIN", APP)
    return APP


def test_a_provider_link_opens_in_this_window_and_never_in_the_default_browser(app_origin):
    edge = _edge_double()
    _install_in_window_new_window_handler(edge)
    browser = edge("https://www.digikey.com/en/products/detail/x")
    args = _Args("https://www.digikey.com/en/models/9876")

    browser.on_new_window_request(
        SimpleNamespace(Source="https://www.digikey.com/en/products/detail/x"),
        args,
    )

    assert args.Handled is True
    assert browser.loaded == ["https://www.digikey.com/en/models/9876"]
    assert edge.escaped == []


def test_a_provider_link_to_another_scheme_is_refused_rather_than_redirected(app_origin):
    edge = _edge_double()
    _install_in_window_new_window_handler(edge)
    browser = edge("https://www.digikey.com/en/products/detail/x")

    for uri in (
        "http://www.digikey.com/insecure",
        "ms-windows-store://pdp",
        "file:///C:/Windows/System32/calc.exe",
        "https://user:secret@www.digikey.com/x",
        "https:///nohost",
        "",
    ):
        args = _Args(uri)
        browser.on_new_window_request(SimpleNamespace(Source=browser.url), args)
        assert args.Handled is True, uri

    assert browser.loaded == []
    assert edge.escaped == []


def test_stockroom_own_links_keep_the_existing_behaviour(app_origin):
    edge = _edge_double()
    _install_in_window_new_window_handler(edge)
    browser = edge(f"{APP}/components")
    args = _Args("https://www.st.com/datasheet.pdf")

    browser.on_new_window_request(SimpleNamespace(Source=f"{APP}/components"), args)

    # Stockroom's own surfaces still hand a datasheet to the person's browser on purpose.
    assert edge.escaped == ["https://www.st.com/datasheet.pdf"]
    assert browser.loaded == []


def test_an_unknown_document_fails_closed_into_this_window(monkeypatch):
    monkeypatch.setattr(host_window, "_APP_ORIGIN", "")
    edge = _edge_double()
    _install_in_window_new_window_handler(edge)
    browser = edge("")
    args = _Args("https://www.digikey.com/en/models/1")

    browser.on_new_window_request(SimpleNamespace(Source=None), args)

    assert browser.loaded == ["https://www.digikey.com/en/models/1"]
    assert edge.escaped == []


def test_the_new_window_hook_is_idempotent():
    edge = _edge_double()

    _install_in_window_new_window_handler(edge)
    installed = edge.on_new_window_request
    _install_in_window_new_window_handler(edge)

    assert edge.on_new_window_request is installed


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.digikey.com/x", True),
        ("https://componentsearchengine.com", True),
        ("http://www.digikey.com/x", False),
        ("https://user@www.digikey.com/x", False),
        ("about:blank", False),
        ("javascript:alert(1)", False),
        (" https://www.digikey.com/x", False),
        (None, False),
    ],
)
def test_only_an_https_page_with_a_real_host_and_no_credentials_may_be_opened(url, allowed):
    assert new_window_url_allowed(url) is allowed


# --- the download pipeline is untouched by any of it ----------------------------------------


class _Operation:
    def __init__(self) -> None:
        self.State = "InProgress"
        self.Uri = "https://componentsearchengine.com/parts/Part.zip"
        self.ContentDisposition = 'attachment; filename="LM317.zip"'
        self.StateChanged = _Hook()


class _Hook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self, sender):
        for handler in list(self.handlers):
            handler(sender, None)


class _DownloadArgs:
    def __init__(self) -> None:
        self.Cancel = False
        self.Handled = False
        self.ResultFilePath = r"C:\Staging\lease\browser-domain-guid"
        self.DownloadOperation = _Operation()


class _Core:
    def __init__(self) -> None:
        self.closed_download_dialog = 0

    def CloseDefaultDownloadDialog(self):
        self.closed_download_dialog += 1


def test_a_download_still_lands_in_staging_after_the_new_window_change(app_origin):
    """The new-window fix must not touch DownloadStarting, staging, or the journal."""

    edge = _edge_double()
    edge.on_download_starting = _Edge.__dict__.get("on_download_starting", lambda *_: None)
    _install_silent_webview2_download_handler(
        SimpleNamespace(settings={"ALLOW_DOWNLOADS": True}),
        edge,
    )
    _install_in_window_new_window_handler(edge)
    browser = edge("https://componentsearchengine.com/parts/LM317")
    args = _DownloadArgs()
    core = _Core()
    lease_token = _begin_native_webview_download_lease()
    try:
        # A link that wants a new window, then the download that page starts. Both in one window.
        browser.on_new_window_request(SimpleNamespace(Source=browser.url), _Args(
            "https://componentsearchengine.com/parts/LM317/download"
        ))
        browser.on_download_starting(core, args)
        args.DownloadOperation.State = "Completed"
        args.DownloadOperation.StateChanged.fire(args.DownloadOperation)

        # The browser-domain broker's own path is preserved verbatim, and the journal still
        # carries the exact start/terminal pair capture waits for.
        assert args.Cancel is False
        assert args.Handled is True
        assert args.ResultFilePath == r"C:\Staging\lease\browser-domain-guid"
        assert core.closed_download_dialog == 1
        assert [(event.phase, event.state) for event in _NATIVE_DOWNLOAD_EVENTS] == [
            ("started", "in_progress"),
            ("terminal", "completed"),
        ]
        assert _NATIVE_DOWNLOAD_EVENTS[-1].suggested_file_name == "LM317.zip"
        assert _NATIVE_DOWNLOAD_EVENTS[-1].result_file_path == args.ResultFilePath
        assert edge.escaped == []
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


# --- the strip as the window mounts it -------------------------------------------------------


class _FakeControl:
    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


def test_chrome_without_a_winforms_surface_still_tracks_the_route():
    """Chrome is never a launch blocker: no surface means no strip, not a broken window."""

    chrome = WindowChrome()
    switches = []

    assert chrome.mounted is False
    chrome.open_provider_route(
        label="DigiKey",
        show=lambda: switches.append("show"),
        hide=lambda: switches.append("hide"),
    )
    chrome.provider_shown()

    assert chrome.state.has_provider_tab is True
    assert chrome.state.is_provider_selected is True

    chrome._on_stockroom_tab_click(None, None)
    assert switches == ["hide"]
    assert chrome.state.is_stockroom_selected is True

    chrome._on_provider_tab_click(None, None)
    assert switches == ["hide", "show"]
    assert chrome.state.is_provider_selected is True

    chrome.close_provider_route()
    assert chrome.state.has_provider_tab is False


def test_back_and_forward_read_the_real_page_and_refuse_an_empty_history():
    chrome = WindowChrome()
    core = _FakeControl(
        CanGoBack=False,
        CanGoForward=False,
        Source="https://www.digikey.com/en/products/detail/x",
        went=[],
    )
    core.GoBack = lambda: core.went.append("back")
    core.GoForward = lambda: core.went.append("forward")
    chrome._core = core
    chrome.open_provider_route(label="DigiKey", show=lambda: None, hide=lambda: None)
    chrome.provider_shown()

    assert chrome.state.back_enabled is False
    chrome.go_back()
    assert core.went == []

    core.CanGoBack = True
    chrome.refresh_page_state()
    assert chrome.state.back_enabled is True
    chrome.go_back()
    assert core.went == ["back"]

    # Looking at Stockroom means there is no page for these controls to act on.
    chrome.provider_hidden()
    chrome.go_back()
    chrome.go_forward()
    assert core.went == ["back"]


def test_alt_left_and_alt_right_drive_the_provider_history():
    chrome = WindowChrome()
    core = _FakeControl(CanGoBack=True, CanGoForward=True, Source="https://x.invalid/", went=[])
    core.GoBack = lambda: core.went.append("back")
    core.GoForward = lambda: core.went.append("forward")
    chrome._core = core
    chrome.open_provider_route(label="DigiKey", show=lambda: None, hide=lambda: None)
    chrome.provider_shown()

    alt_left = _FakeControl(KeyEventKind="SystemKeyDown", VirtualKey=0x25, Handled=False)
    alt_right = _FakeControl(KeyEventKind="SystemKeyDown", VirtualKey=0x27, Handled=False)
    plain_left = _FakeControl(KeyEventKind="KeyDown", VirtualKey=0x25, Handled=False)

    chrome._on_accelerator_key(core, alt_left)
    chrome._on_accelerator_key(core, alt_right)
    chrome._on_accelerator_key(core, plain_left)

    assert core.went == ["back", "forward"]
    assert alt_left.Handled is True
    assert alt_right.Handled is True
    assert plain_left.Handled is False


def test_the_status_says_loading_while_a_page_loads_and_names_a_real_failure():
    chrome = WindowChrome()
    core = _FakeControl(CanGoBack=False, CanGoForward=False, Source="https://x.invalid/", DocumentTitle="")
    chrome._core = core
    chrome.open_provider_route(label="DigiKey", show=lambda: None, hide=lambda: None)
    chrome.provider_shown()

    chrome._on_navigation_starting(core, None)
    assert chrome.state.status == "Loading"

    chrome._on_navigation_completed(core, _FakeControl(IsSuccess=True, WebErrorStatus="Unknown"))
    assert chrome.state.status == ""

    chrome._on_navigation_starting(core, None)
    chrome._on_navigation_completed(
        core,
        _FakeControl(IsSuccess=False, WebErrorStatus="HostNameNotResolved"),
    )
    assert chrome.state.status == "Page Failed To Load"

    # Leaving a page mid-load is the person's own doing, not a failure to report to them.
    chrome._on_navigation_starting(core, None)
    chrome._on_navigation_completed(
        core,
        _FakeControl(IsSuccess=False, WebErrorStatus="ConnectionAborted"),
    )
    assert chrome.state.status == ""


def test_the_tab_follows_the_provider_the_person_browses_to():
    chrome = WindowChrome()
    core = _FakeControl(
        CanGoBack=False,
        CanGoForward=False,
        Source="https://www.digikey.com/en/products/detail/x",
        DocumentTitle="Cart | DigiKey",
    )
    chrome._core = core
    chrome.open_provider_route(label="Provider", show=lambda: None, hide=lambda: None)
    chrome.provider_shown()

    chrome._on_source_changed(core, None)
    assert chrome.state.provider_tab_text == "DigiKey"

    core.Source = "https://app.ultralibrarian.com/search"
    core.DocumentTitle = "Ultra Librarian"
    chrome._on_source_changed(core, None)
    assert chrome.state.provider_tab_text == "Ultra Librarian"


def test_the_address_and_status_follow_the_page_only_while_it_is_selected():
    chrome = WindowChrome()
    core = _FakeControl(
        CanGoBack=True,
        CanGoForward=False,
        Source="https://www.digikey.com/en/products/detail/x",
    )
    chrome._core = core
    chrome.open_provider_route(label="DigiKey", show=lambda: None, hide=lambda: None)
    chrome.provider_shown()

    assert chrome.state.url == "https://www.digikey.com/en/products/detail/x"
    assert chrome.state.controls_visible is True

    chrome.close_provider_route()
    assert chrome.state.url == ""
    assert chrome.state.controls_visible is False
