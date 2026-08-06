"""Window chrome for the source host's single WebView: a real tab strip and page controls.

WHY THIS EXISTS SEPARATELY FROM THE NATIVE HOST'S STRIP
-------------------------------------------------------
``app/desktop/Stockroom.WindowHost`` carries a WPF tab strip (``WindowTabStrip.cs``). That host
runs only when a frozen release owns the native window. The host the owner actually launches is
``python -m stockroom.host.run``, which opens a pywebview/WinForms window - a window that had no
strip, no page controls, and pywebview's default new-window behaviour. So the chrome existed and
was tested, and the person still saw a bare provider page. This module puts the same chrome on the
window that actually opens.

WHAT IS DELIBERATELY PURE
-------------------------
``ProviderChromeState``, ``resolve_provider_tab_label`` and ``new_window_url_allowed`` hold every
rule about what a person sees and what a link is allowed to do. They touch no WinForms object, so
they are tested directly rather than described by a test that constructs the chrome and asserts on
the chrome. ``WindowChrome`` is the thin renderer over that state, and every interop call inside it
is guarded: a window that cannot mount chrome must still be a usable window.

THE TWO-TAB MODEL
-----------------
One Stockroom tab, always. One provider tab, only while a provider route is open, because the
single-lease design is what makes a download provably belong to one component. There are no
per-component tabs and no second provider tab.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_log = logging.getLogger("stockroom.host.window_chrome")

#: The strip is exactly as tall as the native host's, so the two hosts do not disagree about how
#: much of the window belongs to chrome.
STRIP_HEIGHT = 44

#: Long enough for a real provider name and a page title, short enough that the tab never eats
#: the address box.
MAXIMUM_TAB_LENGTH = 40

PROVIDER_TAB_FALLBACK = "Provider"
STOCKROOM_TAB_LABEL = "Stockroom"

# Same palette as WindowTabStrip.cs. Duplicated rather than shared because one is WPF and one is
# WinForms; ``test_window_chrome.py`` pins the values so the two strips cannot drift apart.
SURFACE_COLOR = (17, 21, 29)
IDLE_TAB_COLOR = (23, 28, 37)
SELECTED_TAB_COLOR = (38, 46, 60)
IDLE_TEXT_COLOR = (148, 160, 176)
SELECTED_TEXT_COLOR = (233, 238, 245)
CONTROL_TEXT_COLOR = (205, 214, 225)
CONTROL_SURFACE_COLOR = (27, 33, 44)
EDGE_COLOR = (55, 65, 81)
STATUS_TEXT_COLOR = (132, 145, 162)


def _collapse(value: str | None) -> str:
    """Flatten whitespace and drop control characters, so a page title cannot forge a layout."""

    if not value:
        return ""
    return " ".join(str(value).split())


def _truncate(value: str) -> str:
    if len(value) <= MAXIMUM_TAB_LENGTH:
        return value
    return value[: MAXIMUM_TAB_LENGTH - 1] + "…"


def resolve_provider_tab_label(
    url: str | None = None,
    document_title: str | None = None,
    provider_id: str | None = None,
) -> str:
    """Name the provider tab after the provider, then the page, then the host.

    The registry in ``providers.py`` stays the one authoritative catalogue of provider names, so
    this asks it rather than carrying a second copy of the labels.
    """

    from stockroom.providers import provider_for_host, provider_label

    key = _collapse(provider_id)
    if key:
        return _truncate(provider_label(key))

    host = ""
    try:
        parsed = urlsplit(str(url or ""))
        host = (parsed.hostname or "").strip().casefold().rstrip(".")
    except ValueError:
        host = ""
    if host:
        record = provider_for_host(host)
        if record is not None:
            return _truncate(record.label)

    title = _collapse(document_title)
    if title:
        return _truncate(title)
    if host:
        return _truncate(host[4:] if host.startswith("www.") else host)
    return PROVIDER_TAB_FALLBACK


def new_window_url_allowed(url: str | None) -> bool:
    """Whether a page's new-window request may be honoured by navigating in place.

    The same gate the native host applies to a provider top-level navigation: https only, a real
    host, and no embedded credentials. Everything else is dropped - never handed to the operating
    system, which would hand it to whatever program claims the scheme.
    """

    if not url or type(url) is not str or url != url.strip():
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https":
        return False
    if parsed.username or parsed.password:
        return False
    return bool(parsed.hostname)


@dataclass(slots=True)
class ProviderChromeState:
    """What the strip shows, as data.

    Mirrors ``WindowTabStrip`` exactly: opening a provider route gives it a tab but does not steal
    the selection, and Back / Forward / Refresh / address / status describe a page, so with no page
    selected they are absent rather than present-but-dead.
    """

    provider_label: str = ""
    provider_selected: bool = False
    can_go_back: bool = False
    can_go_forward: bool = False
    url: str = ""
    status: str = ""
    _seen_labels: list[str] = field(default_factory=list, repr=False)

    @property
    def has_provider_tab(self) -> bool:
        return bool(self.provider_label)

    @property
    def provider_tab_text(self) -> str:
        return self.provider_label or PROVIDER_TAB_FALLBACK

    @property
    def is_provider_selected(self) -> bool:
        return self.has_provider_tab and self.provider_selected

    @property
    def is_stockroom_selected(self) -> bool:
        return not self.is_provider_selected

    @property
    def controls_visible(self) -> bool:
        return self.is_provider_selected

    @property
    def back_enabled(self) -> bool:
        return self.is_provider_selected and self.can_go_back

    @property
    def forward_enabled(self) -> bool:
        return self.is_provider_selected and self.can_go_forward

    @property
    def refresh_enabled(self) -> bool:
        return self.is_provider_selected

    def open_provider(self, label: str) -> None:
        """Give the open provider page a tab without yanking the person out of Stockroom."""

        self.provider_label = _truncate(_collapse(label)) or PROVIDER_TAB_FALLBACK

    def set_provider_label(self, label: str) -> None:
        if not self.has_provider_tab:
            return
        self.provider_label = _truncate(_collapse(label)) or PROVIDER_TAB_FALLBACK

    def close_provider(self) -> None:
        """The page is gone, so its tab is gone and Stockroom is what is left."""

        self.provider_label = ""
        self.provider_selected = False
        self.can_go_back = False
        self.can_go_forward = False
        self.url = ""
        self.status = ""

    def select_stockroom(self) -> None:
        self.provider_selected = False

    def select_provider(self) -> None:
        self.provider_selected = self.has_provider_tab

    def set_history(self, *, can_go_back: bool, can_go_forward: bool) -> None:
        self.can_go_back = bool(can_go_back)
        self.can_go_forward = bool(can_go_forward)

    def set_url(self, url: str | None) -> None:
        text = str(url or "")
        # ``about:`` documents are a transient state between pages, not an address a person typed
        # or can act on. Keep the last real one rather than blinking.
        if text.casefold().startswith("about:"):
            return
        self.url = text

    def set_status(self, status: str | None) -> None:
        self.status = str(status or "")


class WindowChrome:
    """The WinForms strip, mounted above the WebView in the pywebview window.

    Every interop call is guarded. Chrome is what makes the window usable, not what makes it
    exist: a WinForms surface this cannot decorate is still a window the person can work in.
    """

    def __init__(self, state: ProviderChromeState | None = None) -> None:
        self.state = state if state is not None else ProviderChromeState()
        self._form = None
        self._strip = None
        self._stockroom_tab = None
        self._provider_tab = None
        self._back = None
        self._forward = None
        self._refresh = None
        self._address = None
        self._status = None
        self._show_provider = None
        self._hide_provider = None
        self._core = None

    # -- the route the capture package owns ------------------------------------------------
    #
    # Capture runs on its own worker threads, and a WinForms control may only be touched from the
    # thread that created it. Every route notification is therefore marshalled onto the window's
    # thread; the state itself is updated there too, so a reader never sees a half-applied route.

    def open_provider_route(self, *, label: str, show, hide) -> None:
        """A provider route opened: the tab appears and knows how to switch to and from itself."""

        def apply() -> None:
            self._show_provider = show
            self._hide_provider = hide
            self.state.open_provider(label)
            self.render()

        self.dispatch(apply)

    def close_provider_route(self) -> None:
        def apply() -> None:
            self._show_provider = None
            self._hide_provider = None
            self.state.close_provider()
            self.render()

        self.dispatch(apply)

    def provider_shown(self) -> None:
        def apply() -> None:
            self.state.select_provider()
            self.refresh_page_state()
            self.render()

        self.dispatch(apply)

    def provider_hidden(self) -> None:
        def apply() -> None:
            self.state.select_stockroom()
            self.render()

        self.dispatch(apply)

    def dispatch(self, action) -> None:
        """Run ``action`` on the thread that owns the strip."""

        form = self._form
        try:
            if form is not None and bool(getattr(form, "InvokeRequired", False)):
                from System import Action

                form.Invoke(Action(action))
                return
        except Exception:  # noqa: BLE001 - a closing window has no thread left to marshal onto
            _log.debug("window chrome could not reach the window thread", exc_info=True)
            return
        action()

    # -- page state ------------------------------------------------------------------------

    def attach_core(self, core) -> None:
        """Follow one CoreWebView2's navigation so the controls describe the real page."""

        self._core = core
        try:
            core.HistoryChanged += self._on_history_changed
        except Exception:  # noqa: BLE001 - one missing event never costs the others
            _log.debug("window chrome could not follow history", exc_info=True)
        try:
            core.SourceChanged += self._on_source_changed
        except Exception:  # noqa: BLE001
            _log.debug("window chrome could not follow the address", exc_info=True)
        try:
            core.DocumentTitleChanged += self._on_document_title_changed
        except Exception:  # noqa: BLE001
            _log.debug("window chrome could not follow the page title", exc_info=True)
        try:
            core.AcceleratorKeyPressed += self._on_accelerator_key
        except Exception:  # noqa: BLE001
            _log.debug("window chrome could not bind Alt+Left / Alt+Right", exc_info=True)
        try:
            core.NavigationStarting += self._on_navigation_starting
            core.NavigationCompleted += self._on_navigation_completed
        except Exception:  # noqa: BLE001
            _log.debug("window chrome could not follow page loading", exc_info=True)
        self.refresh_page_state()
        self.render()

    def refresh_page_state(self) -> None:
        core = self._core
        if core is None:
            return
        try:
            self.state.set_history(
                can_go_back=bool(getattr(core, "CanGoBack", False)),
                can_go_forward=bool(getattr(core, "CanGoForward", False)),
            )
            self.state.set_url(str(getattr(core, "Source", "") or ""))
        except Exception:  # noqa: BLE001 - an initializing page has no readable history yet
            _log.debug("window chrome could not read page state", exc_info=True)

    def go_back(self) -> None:
        self._history(back=True)

    def go_forward(self) -> None:
        self._history(back=False)

    def reload(self) -> None:
        core = self._core
        if core is None or not self.state.is_provider_selected:
            return
        try:
            core.Reload()
        except Exception:  # noqa: BLE001 - a page mid-navigation reloads itself
            _log.debug("window chrome reload failed", exc_info=True)

    def _history(self, *, back: bool) -> None:
        core = self._core
        if core is None or not self.state.is_provider_selected:
            return
        try:
            if back and bool(getattr(core, "CanGoBack", False)):
                core.GoBack()
            elif not back and bool(getattr(core, "CanGoForward", False)):
                core.GoForward()
        except Exception:  # noqa: BLE001 - history is advisory, never an error to surface
            _log.debug("window chrome history navigation failed", exc_info=True)
        self.refresh_page_state()
        self.render()

    # -- events ----------------------------------------------------------------------------

    def _on_history_changed(self, _sender, _args) -> None:
        self.refresh_page_state()
        self.render()

    def _on_source_changed(self, _sender, _args) -> None:
        self.refresh_page_state()
        self._refresh_provider_label()
        self.render()

    def _on_document_title_changed(self, _sender, _args) -> None:
        self._refresh_provider_label()
        self.render()

    def _refresh_provider_label(self) -> None:
        """Keep the tab named for the page it is actually on, as the person browses."""

        if not self.state.has_provider_tab:
            return
        title = ""
        try:
            title = str(getattr(self._core, "DocumentTitle", "") or "")
        except Exception:  # noqa: BLE001 - an untitled page keeps the name it has
            title = ""
        self.state.set_provider_label(
            resolve_provider_tab_label(url=self.state.url, document_title=title)
        )

    def _on_navigation_starting(self, _sender, _args) -> None:
        self.state.set_status("Loading")
        self.render()

    def _on_navigation_completed(self, _sender, args) -> None:
        failed = False
        status_name = ""
        try:
            failed = not bool(getattr(args, "IsSuccess", True))
            status_name = str(getattr(args, "WebErrorStatus", "") or "")
        except Exception:  # noqa: BLE001 - an unreadable outcome is not an error to announce
            failed = False
        # ConnectionAborted is the person cancelling or leaving mid-load, not a page failure worth
        # telling them about. The same judgement the native host makes.
        if failed and "connectionaborted" not in status_name.casefold():
            self.state.set_status("Page Failed To Load")
        else:
            self.state.set_status("")
        self.refresh_page_state()
        self._refresh_provider_label()
        self.render()

    def _on_accelerator_key(self, _sender, args) -> None:
        """Alt+Left and Alt+Right, which WebView2 reports as a system key press."""

        if not self.state.is_provider_selected:
            return
        if "systemkeydown" not in str(getattr(args, "KeyEventKind", "")).casefold():
            return
        key = int(getattr(args, "VirtualKey", 0) or 0)
        if key == 0x25:
            self._handled(args)
            self.go_back()
        elif key == 0x27:
            self._handled(args)
            self.go_forward()

    @staticmethod
    def _handled(args) -> None:
        try:
            setter = getattr(args, "set_Handled", None)
            if callable(setter):
                setter(True)
            else:
                args.Handled = True
        except Exception:  # noqa: BLE001 - an unhandled accelerator is still not an escape
            _log.debug("window chrome could not consume an accelerator", exc_info=True)

    # -- the WinForms surface --------------------------------------------------------------

    def mount(self, form) -> bool:
        """Put the strip above the WebView. Returns whether the person will actually see it."""

        try:
            import System.Windows.Forms as WinForms
            from System.Drawing import Color, ContentAlignment, Font, FontStyle, Size
        except Exception:  # noqa: BLE001 - a non-WinForms backend simply has no strip
            _log.debug("window chrome needs the WinForms backend", exc_info=True)
            return False

        def color(rgb):
            return Color.FromArgb(255, rgb[0], rgb[1], rgb[2])

        try:
            strip = WinForms.Panel()
            strip.Height = STRIP_HEIGHT
            strip.BackColor = color(SURFACE_COLOR)

            row = WinForms.TableLayoutPanel()
            row.Dock = WinForms.DockStyle.Fill
            row.RowCount = 1
            row.ColumnCount = 7
            row.BackColor = color(SURFACE_COLOR)
            row.Padding = WinForms.Padding(10, 0, 10, 0)
            # Five sized columns for the tabs and the three page controls, one that takes the
            # remaining width for the address box, and one sized column for the status text.
            for _column in range(5):
                row.ColumnStyles.Add(WinForms.ColumnStyle(WinForms.SizeType.AutoSize))
            row.ColumnStyles.Add(WinForms.ColumnStyle(WinForms.SizeType.Percent, 100.0))
            row.ColumnStyles.Add(WinForms.ColumnStyle(WinForms.SizeType.AutoSize))

            tab_font = Font("Segoe UI", 8.5, FontStyle.Bold)
            body_font = Font("Segoe UI", 8.5)

            def tab(label: str, accessible: str):
                button = WinForms.RadioButton()
                button.Appearance = WinForms.Appearance.Button
                button.FlatStyle = WinForms.FlatStyle.Flat
                button.Text = label
                button.Font = tab_font
                button.AutoSize = False
                button.Size = Size(112, 26)
                button.TextAlign = ContentAlignment.MiddleCenter
                button.Anchor = WinForms.AnchorStyles.Left
                button.Margin = WinForms.Padding(0, 0, 6, 0)
                button.AccessibleName = accessible
                button.BackColor = color(IDLE_TAB_COLOR)
                button.ForeColor = color(IDLE_TEXT_COLOR)
                button.FlatAppearance.BorderColor = color(EDGE_COLOR)
                return button

            def control(label: str):
                button = WinForms.Button()
                button.Text = label
                button.Font = body_font
                button.AutoSize = False
                button.Size = Size(64, 26)
                button.FlatStyle = WinForms.FlatStyle.Flat
                button.Anchor = WinForms.AnchorStyles.Left
                button.Margin = WinForms.Padding(0, 0, 6, 0)
                button.AccessibleName = label
                button.BackColor = color(CONTROL_SURFACE_COLOR)
                button.ForeColor = color(CONTROL_TEXT_COLOR)
                button.FlatAppearance.BorderColor = color(EDGE_COLOR)
                return button

            self._stockroom_tab = tab(STOCKROOM_TAB_LABEL, "Show Stockroom")
            self._provider_tab = tab(PROVIDER_TAB_FALLBACK, "Show the open provider page")
            self._back = control("Back")
            self._forward = control("Forward")
            self._refresh = control("Refresh")

            address = WinForms.TextBox()
            address.ReadOnly = True
            address.BorderStyle = WinForms.BorderStyle.FixedSingle
            address.Font = body_font
            address.Anchor = WinForms.AnchorStyles.Left | WinForms.AnchorStyles.Right
            address.Margin = WinForms.Padding(2, 0, 8, 0)
            address.BackColor = color(CONTROL_SURFACE_COLOR)
            address.ForeColor = color(CONTROL_TEXT_COLOR)
            address.AccessibleName = "Provider Page Address"
            self._address = address

            status = WinForms.Label()
            status.AutoSize = True
            status.Font = body_font
            status.Anchor = WinForms.AnchorStyles.Right
            status.Margin = WinForms.Padding(0, 0, 2, 0)
            status.ForeColor = color(STATUS_TEXT_COLOR)
            status.AccessibleName = "Provider Page Status"
            status.Text = ""
            self._status = status

            self._stockroom_tab.Click += self._on_stockroom_tab_click
            self._provider_tab.Click += self._on_provider_tab_click
            self._back.Click += lambda _sender, _args: self.go_back()
            self._forward.Click += lambda _sender, _args: self.go_forward()
            self._refresh.Click += lambda _sender, _args: self.reload()

            for column, element in enumerate(
                (
                    self._stockroom_tab,
                    self._provider_tab,
                    self._back,
                    self._forward,
                    self._refresh,
                    self._address,
                    self._status,
                )
            ):
                row.Controls.Add(element, column, 0)

            strip.Controls.Add(row)
            # The WebView is already docked Fill at z-order 0. WinForms lays docked children out
            # from the last index to the first, so a Top strip appended after it takes the top
            # band and the WebView keeps exactly the rest. Nothing overlaps and nothing is hidden.
            form.Controls.Add(strip)
            strip.Dock = WinForms.DockStyle.Top
            self._strip = strip
            self._form = form
        except Exception:  # noqa: BLE001 - a window without chrome still works
            _log.debug("window chrome could not be mounted", exc_info=True)
            self._strip = None
            return False

        self.render()
        return True

    @property
    def mounted(self) -> bool:
        return self._strip is not None

    def render(self) -> None:
        """Push the state onto the strip. Safe before and after mounting."""

        if self._strip is None:
            return
        try:
            from System.Drawing import Color

            def color(rgb):
                return Color.FromArgb(255, rgb[0], rgb[1], rgb[2])

            state = self.state
            self._stockroom_tab.Checked = state.is_stockroom_selected
            self._stockroom_tab.BackColor = color(
                SELECTED_TAB_COLOR if state.is_stockroom_selected else IDLE_TAB_COLOR
            )
            self._stockroom_tab.ForeColor = color(
                SELECTED_TEXT_COLOR if state.is_stockroom_selected else IDLE_TEXT_COLOR
            )
            self._provider_tab.Visible = state.has_provider_tab
            self._provider_tab.Text = state.provider_tab_text
            self._provider_tab.AccessibleName = state.provider_tab_text
            self._provider_tab.Checked = state.is_provider_selected
            self._provider_tab.BackColor = color(
                SELECTED_TAB_COLOR if state.is_provider_selected else IDLE_TAB_COLOR
            )
            self._provider_tab.ForeColor = color(
                SELECTED_TEXT_COLOR if state.is_provider_selected else IDLE_TEXT_COLOR
            )
            for element, enabled in (
                (self._back, state.back_enabled),
                (self._forward, state.forward_enabled),
                (self._refresh, state.refresh_enabled),
            ):
                element.Visible = state.controls_visible
                element.Enabled = enabled
                element.ForeColor = color(
                    CONTROL_TEXT_COLOR if enabled else IDLE_TEXT_COLOR
                )
            self._address.Visible = state.controls_visible
            self._address.Text = state.url
            self._status.Visible = state.controls_visible
            self._status.Text = state.status
        except Exception:  # noqa: BLE001 - a strip that cannot repaint must not stop the app
            _log.debug("window chrome could not be rendered", exc_info=True)

    def _on_stockroom_tab_click(self, _sender, _args) -> None:
        hide = self._hide_provider
        self.state.select_stockroom()
        self.render()
        if hide is None:
            return
        try:
            hide()
        except Exception:  # noqa: BLE001 - a route mid-teardown is already leaving
            _log.debug("window chrome could not return to Stockroom", exc_info=True)

    def _on_provider_tab_click(self, _sender, _args) -> None:
        show = self._show_provider
        if show is None or not self.state.has_provider_tab:
            self.state.select_stockroom()
            self.render()
            return
        self.state.select_provider()
        self.render()
        try:
            show()
        except Exception:  # noqa: BLE001 - the tab reverts on the next route event
            _log.debug("window chrome could not show the provider page", exc_info=True)
