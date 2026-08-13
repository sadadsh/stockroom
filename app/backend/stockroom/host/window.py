"""The thin pywebview/WebView2 desktop shell.

The shell hosts Stockroom's FastAPI-served frontend, injects the loopback API
base and per-launch token, owns native window lifecycle, exposes the project
folder picker, and provides separate WebViews for rendered-DOM fetching and the
in-app provider modal. Provider acquisition owns task-bound downloads and status;
the host only supplies the human-operated provider surface.

pywebview is imported lazily inside the Windows-only entry points so this module
and its pure helpers remain importable on every supported platform.
"""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

_log = logging.getLogger("stockroom.host.window")

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None
_PROVIDER_WINDOW = None
#: The loopback SPA origin of the running host, known before the window opens. A new-window
#: request from a document on this origin is Stockroom's own; anything else is a provider page.
_APP_ORIGIN = ""
#: The source host's provider-route controller, once bound to the window thread.
_WINDOW_CHROME = None
_PROVIDER_SURFACE = None
_NATIVE_DOWNLOAD_GUARD = threading.RLock()
_NATIVE_DOWNLOAD_LEASE: str | None = None
_NATIVE_DOWNLOAD_SEQUENCE = 0
_NATIVE_DOWNLOAD_EVENTS: list["InAppProviderDownloadEvent"] = []

UNPACKAGED_APP_USER_MODEL_ID = "Stockroom.Desktop.Unpackaged"

_APP_MODEL_ERROR_NO_PACKAGE = 15_700
_ERROR_INSUFFICIENT_BUFFER = 122
_LR_LOAD_FROM_FILE = 0x0010
_IMAGE_ICON = 1
_WM_SETICON = 0x0080
_WM_CLOSE = 0x0010
_ICON_SMALL = 0
_ICON_BIG = 1
_SM_CXICON = 11
_SM_CYICON = 12
_SM_CXSMICON = 49
_SM_CYSMICON = 50
_DEFAULT_DPI = 96


def _is_windows() -> bool:
    return os.name == "nt"


def active_window():
    return _ACTIVE_WINDOW


def window_chrome():
    """The bound provider-route controller, or None before the window opens."""

    return _WINDOW_CHROME


@dataclass(slots=True)
class InAppProviderDownloadEvent:
    sequence: int
    operation_id: str
    phase: str
    state: str
    uri: str
    suggested_file_name: str
    result_file_path: str


@dataclass(slots=True)
class InAppProviderBrowserLease:
    """One task-bound lease of Stockroom's dedicated provider WebView.

    Nothing is attached to it. Provider pages and their downloads do not escape into Chrome,
    Vivaldi, or the primary Stockroom WebView, and capture observes them only through the download
    events below.
    """

    _show: Callable[[], None]
    _hide: Callable[[], None]
    _navigate: Callable[[str], None]
    _current_url: Callable[[], str]
    _security_state: Callable[[], dict[str, object]]
    _document_state: Callable[[tuple[str, ...], tuple[str, ...]], dict[str, object]]
    _download_events: Callable[[int], tuple[InAppProviderDownloadEvent, ...]]

    def show(self) -> None:
        self._show()

    def hide(self) -> None:
        """Return to the Stockroom SPA without ending the active capture route."""

        self._hide()

    def current_url(self) -> str:
        """Return only the native WebView's current URL while automation is detached."""

        return self._current_url()

    def navigate(self, url: str) -> None:
        """Navigate the native WebView while no automation transport is connected."""

        self._navigate(url)

    def security_state(self) -> dict[str, object]:
        """Read the minimum native page state needed to wait out a visible security gate.

        This deliberately does not expose provider controls or page content.  It answers only
        whether the document is ready and whether a common visible browser-verification surface
        remains, so Playwright can stay completely disconnected while the person owns the gate.
        """

        return self._security_state()

    def document_state(
        self,
        *,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Return only native readiness/security signals for a detached navigation."""

        return self._document_state(ready_selectors, ready_texts)

    def download_events(
        self,
        *,
        after_sequence: int = 0,
    ) -> tuple[InAppProviderDownloadEvent, ...]:
        return self._download_events(after_sequence)


class InAppProviderBrowserSurface:
    """Own the dedicated native provider WebView without navigating Stockroom."""

    def __init__(
        self,
        app_url: str,
        *,
        provider_window: Callable[[], object] | None = None,
    ) -> None:
        global _PROVIDER_SURFACE
        if not should_inject(app_url, app_url):
            raise ValueError("app_url must have a complete origin")
        self._app_url = app_url
        self._provider_window = provider_window or provider_window_surface
        self._lock = threading.RLock()
        self._active_show: Callable[[], None] | None = None
        self._active_provider_window = None
        self._active_component_id: str | None = None
        self._last_provider_viewport: dict[str, object] | None = None
        _PROVIDER_SURFACE = self

    def set_provider_viewport(self, viewport: dict[str, object]) -> bool:
        """Place the provider-only window over the React modal's content rectangle."""

        if type(viewport) is not dict or set(viewport) != {
            "componentId",
            "visible",
            "x",
            "y",
            "width",
            "height",
        }:
            return False
        component_id = viewport["componentId"]
        visible = viewport["visible"]
        values = tuple(viewport[key] for key in ("x", "y", "width", "height"))
        if (
            type(component_id) is not str
            or not component_id
            or type(visible) is not bool
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
        ):
            return False
        provider = self._active_provider_window
        app = active_window()
        if not visible:
            self._last_provider_viewport = None
            if provider is not None:
                provider.hide()
            return True
        x, y, width, height = (float(value) for value in values)
        if x < 0 or y < 0 or width < 320 or height < 240 or provider is None or app is None:
            return False
        if self._active_component_id is None:
            self._active_component_id = component_id
        if component_id != self._active_component_id:
            self._last_provider_viewport = None
            provider.hide()
            return False
        self._last_provider_viewport = dict(viewport)
        return self._apply_provider_viewport(viewport, focus=True)

    def _apply_provider_viewport(
        self,
        viewport: dict[str, object],
        *,
        focus: bool,
    ) -> bool:
        provider = self._active_provider_window
        app = active_window()
        if provider is None or app is None:
            return False
        x = float(viewport["x"])
        y = float(viewport["y"])
        width = float(viewport["width"])
        height = float(viewport["height"])
        app_x = int(getattr(app, "x", 0) or 0)
        app_y = int(getattr(app, "y", 0) or 0)
        provider.move(round(app_x + x), round(app_y + y))
        provider.resize(round(width), round(height))
        provider.show()
        if focus:
            provider.focus()
        return True

    def reapply_provider_viewport(self) -> bool:
        """Follow a moved or resized Stockroom window without stealing focus."""

        viewport = self._last_provider_viewport
        return bool(viewport and self._apply_provider_viewport(viewport, focus=False))

    def provider_command(self, request: dict[str, object]) -> bool:
        """Apply one allowlisted browser command to the active provider document."""

        if type(request) is not dict:
            return False
        command = request.get("command")
        expected = (
            {"componentId", "command", "url"}
            if command == "navigate"
            else {"componentId", "command"}
        )
        if set(request) != expected:
            return False
        component_id = request["componentId"]
        provider = self._active_provider_window
        if (
            type(component_id) is not str
            or component_id != self._active_component_id
            or command not in {"back", "forward", "reload", "close", "navigate"}
            or provider is None
        ):
            return False
        if command == "close":
            provider.hide()
            return True
        if command == "navigate":
            target = request["url"]
            if type(target) is not str:
                return False
            parsed = urlsplit(target)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return False
            provider.load_url(target)
            return True
        script = {
            "back": "history.back()",
            "forward": "history.forward()",
            "reload": "location.reload()",
        }[command]
        provider.evaluate_js(script)
        return True

    def __call__(self):
        """Open one provider lease; keeps the surface itself available to the API."""

        return self.lease()

    def show_active_provider_browser(self) -> None:
        """Restore the provider route hidden by Return to Stockroom."""

        show = self._active_show
        if show is None:
            raise RuntimeError("there is no active provider route")
        show()

    @contextmanager
    def lease(self):
        """Yield one observed provider lease and always hide its native surface afterward."""

        with self._lock:
            if active_window() is None:
                raise RuntimeError("the Stockroom provider browser is not ready")
            window = self._provider_window()
            if window is None:
                raise RuntimeError("the Stockroom provider browser is not ready")
            lease_token = _begin_native_webview_download_lease()
            self._active_provider_window = window
            self._active_component_id = None
            self._last_provider_viewport = None

            chrome = window_chrome()

            def show() -> None:
                # Visibility belongs to the React modal's measured viewport. Showing here would
                # flash a free-standing provider window before the modal can publish its bounds.
                if chrome is not None:
                    chrome.provider_shown()

            def hide() -> None:
                if chrome is not None:
                    chrome.provider_hidden()
                try:
                    window.hide()
                except Exception:  # noqa: BLE001 - a navigating WebView retries from its tab
                    _log.exception("could not hide the provider browser")

            def navigate(url: str) -> None:
                if type(url) is not str or not url or url != url.strip():
                    raise ValueError("provider URL must be exact non-empty text")
                window.load_url(url)
                if chrome is not None:
                    # The tab is named after the provider whose page this is, and the page is
                    # what the person is looking at once capture has navigated to it.
                    chrome.open_provider_route(
                        label=_resolve_route_tab_label(url),
                        show=show,
                        hide=hide,
                    )
                    chrome.provider_shown()

            def current_url() -> str:
                try:
                    return str(window.get_current_url() or "")
                except Exception:  # noqa: BLE001 - a navigating page has no stable URL yet
                    return ""

            def document_state(
                ready_selectors: tuple[str, ...],
                ready_texts: tuple[str, ...],
            ) -> dict[str, object]:
                selectors = json.dumps(list(ready_selectors), ensure_ascii=True)
                texts = json.dumps([value.casefold() for value in ready_texts], ensure_ascii=True)
                script = r"""
                (() => {
                  const title = String(document.title || "").toLowerCase();
                  const body = String(document.body?.innerText || "").toLowerCase();
                  const selectors = __STOCKROOM_READY_SELECTORS__;
                  const readyTexts = __STOCKROOM_READY_TEXTS__;
                  const isVisible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden"
                      && Number(style.opacity || "1") > 0 && rect.width > 4 && rect.height > 4;
                  };
                  const challengeFrame = Array.from(document.querySelectorAll(
                    'iframe[src*="challenges.cloudflare.com"], iframe[title*="challenge" i]'
                  )).some(isVisible);
                  const accountVerification = [
                    "verify your phone number",
                    "phone verification is required",
                  ].some((value) => title.includes(value) || body.includes(value));
                  const providerError = [
                    "oh snap! we've experienced an error",
                    "oh snap! we’ve experienced an error",
                  ].some((value) => title.includes(value) || body.includes(value));
                  const challengeText = [
                    "verify you are human",
                    "verifying you are human",
                    "performing security verification",
                    "checking your browser",
                    "security verification",
                  ].some((value) => title.includes(value) || body.includes(value));
                  const selectorReady = selectors.some((selector) => {
                    try { return Array.from(document.querySelectorAll(selector)).some(isVisible); }
                    catch (_) { return false; }
                  });
                  const textReady = readyTexts.some((value) => body.includes(value));
                  return {
                    ready: document.readyState === "interactive" || document.readyState === "complete",
                    challenge: challengeFrame || accountVerification
                      || (challengeText && !(selectorReady || textReady)),
                    accountVerification,
                    providerError,
                    providerReady: selectors.length === 0 && readyTexts.length === 0
                      ? true
                      : selectorReady || textReady,
                  };
                })()
                """
                script = script.replace("__STOCKROOM_READY_SELECTORS__", selectors).replace(
                    "__STOCKROOM_READY_TEXTS__", texts
                )
                try:
                    result = window.evaluate_js(script)
                except Exception:  # noqa: BLE001 - navigation is temporarily unreadable
                    return {"ready": False, "challenge": True}
                if not isinstance(result, dict):
                    return {"ready": False, "challenge": True}
                return {
                    "ready": bool(result.get("ready")),
                    "challenge": bool(result.get("challenge")),
                    "account_verification": bool(result.get("accountVerification")),
                    "provider_error": bool(result.get("providerError")),
                    "provider_ready": bool(result.get("providerReady")),
                }

            def security_state() -> dict[str, object]:
                state = document_state((), ())
                return {
                    "ready": bool(state.get("ready")),
                    "challenge": bool(state.get("challenge")),
                    "account_verification": bool(state.get("account_verification")),
                }

            def download_events(after_sequence: int) -> tuple[InAppProviderDownloadEvent, ...]:
                if type(after_sequence) is not int or after_sequence < 0:
                    raise ValueError("provider download cursor is invalid")
                with _NATIVE_DOWNLOAD_GUARD:
                    return tuple(
                        event
                        for event in _NATIVE_DOWNLOAD_EVENTS
                        if event.sequence > after_sequence
                    )

            try:
                self._active_show = show
                if chrome is not None:
                    # A route is open before its first page loads, so the tab exists from here
                    # under the plain word; the first navigation names it for its provider. It
                    # does not steal the selection: a lease can begin while the person is still
                    # reading Stockroom.
                    chrome.open_provider_route(
                        label=PROVIDER_TAB_FALLBACK,
                        show=show,
                        hide=hide,
                    )
                yield InAppProviderBrowserLease(
                    _show=show,
                    _hide=hide,
                    _navigate=navigate,
                    _current_url=current_url,
                    _security_state=security_state,
                    _document_state=document_state,
                    _download_events=download_events,
                )
            finally:
                self._active_show = None
                self._active_provider_window = None
                self._active_component_id = None
                self._last_provider_viewport = None
                _end_native_webview_download_lease(lease_token)
                if chrome is not None:
                    chrome.close_provider_route()
                try:
                    window.hide()
                except Exception:  # noqa: BLE001 - teardown must not mask capture evidence
                    _log.exception("could not hide the provider browser after capture")


#: The word a provider tab wears before its first page has named it.
PROVIDER_TAB_FALLBACK = "Provider"


def _resolve_route_tab_label(url: str) -> str:
    """Name the provider tab from the page the route is on."""

    from stockroom.host.window_chrome import resolve_provider_tab_label

    return resolve_provider_tab_label(url=url)


def fetch_window():
    """Return the dedicated hidden window owned by the rendered-DOM fetcher.

    It is distinct from the visible SPA window and never receives the SPA's
    token-injecting loaded handler. Navigating it to a remote enrichment source
    therefore cannot leak the per-launch token or replace the user's app view.
    """

    global _FETCH_WINDOW
    if _FETCH_WINDOW is None:
        import webview  # pywebview, WebView2 on Windows; lazy so Linux imports

        _FETCH_WINDOW = webview.create_window("stockroom-fetch", hidden=True)
    return _FETCH_WINDOW


def provider_window_surface():
    """Return the provider-only pywebview window; never the Stockroom window."""

    global _PROVIDER_WINDOW
    if _PROVIDER_WINDOW is None:
        import webview  # pywebview, WebView2 on Windows; lazy so Linux imports

        _PROVIDER_WINDOW = webview.create_window(
            "Stockroom Provider",
            url="about:blank#stockroom-provider-proof",
            width=960,
            height=640,
            min_size=(320, 240),
            hidden=True,
            frameless=True,
            easy_drag=False,
        )
    return _PROVIDER_WINDOW


def should_inject(current_url: str | None, base_url: str) -> bool:
    """Return whether ``current_url`` is the exact loopback SPA origin.

    The token is the sole guard on the local API in addition to its loopback
    binding, so unknown and remote URLs fail closed.
    """

    if not current_url:
        return False
    current, base = urlsplit(current_url), urlsplit(base_url)
    return (current.scheme, current.hostname, current.port) == (
        base.scheme,
        base.hostname,
        base.port,
    )


def inject_script(
    base_url: str,
    token: str | None,
    ui: dict | None = None,
) -> str:
    """Build the renderer bootstrap, optionally retaining legacy JS auth."""

    base = json.dumps(base_url)
    # ``</script>`` inside a JSON string would otherwise close the injected element.
    prefs = json.dumps(ui or {}).replace("</", "<\\/")
    token_line = "" if token is None else f"window.__STOCKROOM_TOKEN__ = {json.dumps(token)};\n"
    return (
        f"window.__API_BASE__ = {base};\n"
        + token_line
        + (
            f"window.__STOCKROOM_UI__ = {prefs};\n"
            "window.__STOCKROOM_HOST__ = Object.assign(window.__STOCKROOM_HOST__ || {}, {\n"
            "  setProviderViewport: function (viewport) {\n"
            "    return window.pywebview.api.set_provider_viewport(viewport);\n"
            "  },\n"
            "  providerCommand: function (request) {\n"
            "    return window.pywebview.api.provider_command(request);\n"
            "  }\n"
            "});\n"
            "if ('serviceWorker' in navigator) {\n"
            "  navigator.serviceWorker.getRegistrations().then(function (rs) {\n"
            "    rs.forEach(function (r) { r.unregister(); });\n"
            "  });\n"
            "}\n"
        )
    )


class _HostApi:
    """The narrow native shell API exposed only to the loopback renderer."""

    def pick_folder(self, purpose: str) -> list[str]:
        """Pick one folder for an allowlisted Stockroom workflow."""

        if purpose not in {"project", "stm-cubemx"}:
            return []

        import webview

        window = active_window()
        if window is None:
            return []
        dialog_types = getattr(webview, "FileDialog", None)
        folder_dialog = getattr(dialog_types, "FOLDER", None)
        if folder_dialog is None:
            folder_dialog = webview.FOLDER_DIALOG
        result = window.create_file_dialog(
            folder_dialog,
            allow_multiple=False,
        )
        return list(result) if result else []

    def pick_project_folder(self) -> list[str]:
        """Compatibility bridge for a renderer that predates the purpose-based picker."""

        return self.pick_folder("project")

    def pick_files(self, purpose: str) -> list[str]:
        """Pick recovery CAD files without granting the renderer arbitrary filesystem access."""

        if purpose != "cad-recovery":
            return []
        import webview

        window = active_window()
        if window is None:
            return []
        dialog_types = getattr(webview, "FileDialog", None)
        open_dialog = getattr(dialog_types, "OPEN", None)
        if open_dialog is None:
            open_dialog = webview.OPEN_DIALOG
        result = window.create_file_dialog(
            open_dialog,
            allow_multiple=True,
            file_types=(
                "CAD Files (*.zip;*.kicad_sym;*.kicad_mod;*.step;*.stp;*.SchLib;*.PcbLib)",
                "All Files (*.*)",
            ),
        )
        return list(result) if result else []

    def set_provider_viewport(self, viewport: dict[str, object]) -> bool:
        """Place or hide the dedicated provider WebView inside Stockroom's modal."""

        surface = _PROVIDER_SURFACE
        return bool(surface and surface.set_provider_viewport(viewport))

    def provider_command(self, request: dict[str, object]) -> bool:
        """Apply one allowlisted command to the dedicated provider WebView."""

        surface = _PROVIDER_SURFACE
        return bool(surface and surface.provider_command(request))


def _set_signature(function, argument_types, result_type) -> None:
    """Declare a ctypes Win32 signature when ``function`` is a real DLL export."""

    try:
        function.argtypes = argument_types
        function.restype = result_type
    except (AttributeError, TypeError):
        # Unit-test doubles are ordinary Python callables and need no ctypes
        # signature. Keeping that seam injectable lets identity logic be
        # verified without opening a native window.
        return


def _process_has_package_identity(kernel32=None) -> bool:
    """Whether Windows assigned the current process an MSIX package identity.

    The size-query form of ``GetCurrentPackageFullName`` returns
    ``ERROR_INSUFFICIENT_BUFFER`` for a packaged process and
    ``APPMODEL_ERROR_NO_PACKAGE`` for an unpackaged process. Any other result
    fails safe as packaged: an uncertain package query must never be followed
    by overriding the shell-provided AppUserModelID.
    """

    if not _is_windows():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        api = kernel32 or ctypes.windll.kernel32
        query = api.GetCurrentPackageFullName
        _set_signature(
            query,
            [ctypes.POINTER(ctypes.c_uint32), wintypes.LPWSTR],
            wintypes.LONG,
        )
        length = ctypes.c_uint32(0)
        result = int(query(ctypes.byref(length), None))
        if result == _APP_MODEL_ERROR_NO_PACKAGE:
            return False
        if result not in {0, _ERROR_INSUFFICIENT_BUFFER}:
            _log.debug(
                "unexpected package identity query result %s; preserving shell identity",
                result,
            )
        return True
    except Exception:  # noqa: BLE001 - uncertainty must preserve a possible package identity
        _log.debug("package identity query failed; preserving shell identity", exc_info=True)
        return True


def _configure_windows_process_identity(*, kernel32=None, shell32=None) -> bool:
    """Set Stockroom's stable AUMID only for an unpackaged Windows process.

    MSIX owns the installed application's AUMID. Overriding it would split
    taskbar grouping and Start/notification identity, so packaged processes
    deliberately retain the shell-assigned value.
    """

    if not _is_windows() or _process_has_package_identity(kernel32):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        api = shell32 or ctypes.windll.shell32
        setter = api.SetCurrentProcessExplicitAppUserModelID
        _set_signature(setter, [wintypes.LPCWSTR], ctypes.c_long)
        result = int(setter(UNPACKAGED_APP_USER_MODEL_ID))
        if result != 0:
            _log.warning(
                "Windows rejected Stockroom's unpackaged AppUserModelID (HRESULT %#x)",
                result,
            )
            return False
        return True
    except Exception:  # noqa: BLE001 - identity decoration must not prevent startup
        _log.debug("unpackaged AppUserModelID setup failed", exc_info=True)
        return False


def _native_window_handle(window) -> int | None:
    """Return the exact HWND attached by pywebview's WinForms backend."""

    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    for adapter in ("ToInt64", "ToInt32"):
        convert = getattr(handle, adapter, None)
        if callable(convert):
            try:
                value = int(convert())
            except (TypeError, ValueError, OverflowError):
                continue
            return value if value > 0 else None
    try:
        value = int(handle)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def _current_process_window_handle(window, user32=None, process_id: int | None = None) -> int | None:
    """Return ``window``'s HWND only when Windows confirms current-process ownership."""

    if not _is_windows():
        return None
    hwnd = _native_window_handle(window)
    if hwnd is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        api = user32 or ctypes.windll.user32
        is_window = api.IsWindow
        owner = api.GetWindowThreadProcessId
        _set_signature(is_window, [wintypes.HWND], wintypes.BOOL)
        _set_signature(
            owner,
            [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
            wintypes.DWORD,
        )
        if not bool(is_window(hwnd)):
            return None
        actual_process_id = wintypes.DWORD(0)
        if not owner(hwnd, ctypes.byref(actual_process_id)):
            return None
        expected_process_id = os.getpid() if process_id is None else int(process_id)
        return hwnd if actual_process_id.value == expected_process_id else None
    except Exception:  # noqa: BLE001 - an unverified handle must fail closed
        _log.debug("native Stockroom window handle verification failed", exc_info=True)
        return None


def _current_process_named_window_handle(
    title: str,
    *,
    user32=None,
    process_id: int | None = None,
) -> int | None:
    """Find an exact titled top-level window owned by this process."""

    if not _is_windows():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        api = user32 or ctypes.windll.user32
        expected_process_id = os.getpid() if process_id is None else int(process_id)
        matches: list[int] = []
        enum_callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        @enum_callback
        def _visit(hwnd, _lparam):
            actual_process_id = wintypes.DWORD(0)
            if not api.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(actual_process_id),
            ):
                return True
            if actual_process_id.value != expected_process_id:
                return True
            length = int(api.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            api.GetWindowTextW(hwnd, buffer, len(buffer))
            if buffer.value == title:
                matches.append(int(hwnd))
                return False
            return True

        api.EnumWindows(_visit, 0)
        return matches[0] if matches else None
    except Exception:  # noqa: BLE001 - discovery is a fallback, never unverified authority
        _log.debug("native Stockroom window discovery failed", exc_info=True)
        return None


def request_window_close(
    window=None,
    *,
    user32=None,
    process_id: int | None = None,
    timeout: float = 5.0,
) -> bool:
    """Close Stockroom from any host thread through its verified native HWND.

    ``pywebview.Window.destroy`` is not a reliable cross-thread handoff on the
    WinForms backend. Posting ``WM_CLOSE`` asks the owning UI thread to perform
    the normal close sequence. The exact HWND is accepted only when Windows
    confirms that it belongs to this process; test doubles and older backends
    retain the direct-destroy fallback.
    """

    target = window if window is not None else active_window()
    hwnd = (
        _current_process_window_handle(
            target,
            user32=user32,
            process_id=process_id,
        )
        if target is not None
        else None
    )
    if hwnd is None:
        hwnd = _current_process_named_window_handle(
            "Stockroom",
            user32=user32,
            process_id=process_id,
        )
    if hwnd is not None:
        try:
            import ctypes
            from ctypes import wintypes

            api = user32 or ctypes.windll.user32
            post = api.PostMessageW
            _set_signature(
                post,
                [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ],
                wintypes.BOOL,
            )
            if bool(post(hwnd, _WM_CLOSE, 0, 0)):
                deadline = time.monotonic() + max(0.0, float(timeout))
                while bool(api.IsWindow(hwnd)) and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not bool(api.IsWindow(hwnd)):
                    return True
        except Exception:  # noqa: BLE001 - direct destroy remains a safe fallback
            _log.debug("native Stockroom close request failed", exc_info=True)
    if target is None:
        return False
    try:
        target.destroy()
        return True
    except Exception:  # noqa: BLE001 - caller must retain activation for retry
        _log.debug("managed Stockroom destroy request failed", exc_info=True)
        return False


def _apply_saved_window_geometry(window_handle: int, config=None):
    """Apply persisted physical-pixel placement while a candidate stays hidden."""

    from stockroom.host.window_geometry import (
        apply_window_geometry,
        window_geometry_from_machine_config,
    )
    from stockroom.store.machine_config import MachineConfig

    machine_config = config
    if machine_config is None:
        machine_config = MachineConfig.load(migrate_credentials=False)
    geometry = window_geometry_from_machine_config(machine_config)
    if geometry is None:
        return None
    return apply_window_geometry(
        window_handle,
        geometry,
        show=False,
    )


def _window_icon_dimensions(user32, hwnd: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return per-window-DPI small and large shell icon dimensions."""

    import ctypes
    from ctypes import wintypes

    try:
        get_dpi = user32.GetDpiForWindow
        _set_signature(get_dpi, [wintypes.HWND], wintypes.UINT)
        dpi = int(get_dpi(hwnd)) or _DEFAULT_DPI
    except (AttributeError, OSError, TypeError, ValueError):
        dpi = _DEFAULT_DPI

    metrics_for_dpi = getattr(user32, "GetSystemMetricsForDpi", None)
    if callable(metrics_for_dpi):
        try:
            _set_signature(
                metrics_for_dpi,
                [ctypes.c_int, wintypes.UINT],
                ctypes.c_int,
            )
            small = (
                int(metrics_for_dpi(_SM_CXSMICON, dpi)),
                int(metrics_for_dpi(_SM_CYSMICON, dpi)),
            )
            large = (
                int(metrics_for_dpi(_SM_CXICON, dpi)),
                int(metrics_for_dpi(_SM_CYICON, dpi)),
            )
            if min(*small, *large) > 0:
                return small, large
        except (OSError, TypeError, ValueError):
            pass

    get_metric = user32.GetSystemMetrics
    _set_signature(get_metric, [ctypes.c_int], ctypes.c_int)
    small = (int(get_metric(_SM_CXSMICON)), int(get_metric(_SM_CYSMICON)))
    large = (int(get_metric(_SM_CXICON)), int(get_metric(_SM_CYICON)))
    if min(*small, *large) <= 0:
        return ((16, 16), (32, 32))
    return small, large


def _release_window_icons(window, user32=None) -> None:
    """Release HICONs previously assigned to a pywebview window."""

    owned = dict(getattr(window, "_stockroom_icon_handles", {}))
    setattr(window, "_stockroom_icon_handles", {})
    deferred = set(getattr(window, "_stockroom_deferred_icon_handles", ()))
    setattr(window, "_stockroom_deferred_icon_handles", set())
    handles = tuple(set(owned.values()) | deferred)
    if not handles or not _is_windows():
        return
    try:
        import ctypes
        from ctypes import wintypes

        api = user32 or ctypes.windll.user32
        destroy = api.DestroyIcon
        _set_signature(destroy, [wintypes.HICON], wintypes.BOOL)
        for handle in handles:
            destroy(handle)
    except Exception:  # noqa: BLE001 - cosmetic cleanup must not prevent shutdown
        _log.debug("window icon cleanup failed", exc_info=True)


def _apply_window_icon(window, *, user32=None, icon_path: Path | None = None) -> bool:
    """Apply Stockroom's icon to the exact pywebview HWND, best effort."""

    if not _is_windows():  # pragma: no cover - Windows-only cosmetic path
        return False
    try:  # pragma: no cover - exercised only on the real Windows host
        import ctypes
        from ctypes import wintypes

        icon_path = icon_path or (
            Path(__file__).resolve().parent / "assets" / "stockroom.ico"
        )
        if not icon_path.is_file():
            return False
        api = user32 or ctypes.windll.user32
        hwnd = _current_process_window_handle(window, api)
        if hwnd is None:
            return False
        load_image = api.LoadImageW
        send_message = api.SendMessageW
        _set_signature(
            load_image,
            [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ],
            wintypes.HANDLE,
        )
        _set_signature(
            send_message,
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
            wintypes.LPARAM,
        )
        destroy = api.DestroyIcon
        _set_signature(destroy, [wintypes.HICON], wintypes.BOOL)
        small, large = _window_icon_dimensions(api, hwnd)
        requested = (
            (small, _ICON_SMALL),
            (large, _ICON_BIG),
        )
        loaded: list[int] = []
        for (width, height), _which in requested:
            icon = load_image(
                None,
                str(icon_path),
                _IMAGE_ICON,
                width,
                height,
                _LR_LOAD_FROM_FILE,
            )
            if icon:
                loaded.append(int(icon))
        if len(loaded) != len(requested):
            for icon in loaded:
                destroy(icon)
            return False

        prior_owned = dict(getattr(window, "_stockroom_icon_handles", {}))
        prior_deferred = set(
            getattr(window, "_stockroom_deferred_icon_handles", ())
        )
        attached_owned = dict(prior_owned)
        previous_by_kind: dict[int, int] = {}
        replaced: list[int] = []
        try:
            for ((_dimensions, which), icon) in zip(requested, loaded, strict=True):
                previous_by_kind[which] = int(
                    send_message(hwnd, _WM_SETICON, which, icon) or 0
                )
                attached_owned[which] = icon
                replaced.append(which)
        except Exception:
            # A native call cannot report whether it changed the slot before
            # failing. Assume the attempted icon may be attached, then restore
            # every slot for which the prior handle is known. This guarantees
            # that no HICON is destroyed while the live window may reference it.
            failed_kind = requested[len(replaced)][1]
            attached_owned[failed_kind] = loaded[len(replaced)]
            rollback_kinds = [*reversed(replaced), failed_kind]
            rollback_uncertain = bool(prior_deferred)
            for which in rollback_kinds:
                restore = previous_by_kind.get(which, prior_owned.get(which))
                if restore is None:
                    continue
                try:
                    send_message(hwnd, _WM_SETICON, which, restore)
                except Exception:
                    rollback_uncertain = True
                    continue
                if which in prior_owned:
                    attached_owned[which] = prior_owned[which]
                else:
                    attached_owned.pop(which, None)

            attempted_count = len(replaced) + 1
            owned_handles = (
                set(prior_owned.values())
                | prior_deferred
                | set(loaded[:attempted_count])
            )
            if rollback_uncertain:
                # If a rollback call itself fails, Windows may have changed the
                # slot before ctypes surfaced the error. Retain every possibly
                # attached handle until a later full replacement or window
                # destruction proves it detached; leaking briefly is safer than
                # freeing an HICON still referenced by the live HWND.
                for icon in loaded[attempted_count:]:
                    destroy(icon)
                setattr(window, "_stockroom_icon_handles", attached_owned)
                setattr(window, "_stockroom_deferred_icon_handles", owned_handles)
                return False

            attached_handles = set(attached_owned.values())
            for icon in owned_handles - attached_handles:
                destroy(icon)
            setattr(window, "_stockroom_icon_handles", attached_owned)
            setattr(window, "_stockroom_deferred_icon_handles", set())
            return False

        for icon in (set(prior_owned.values()) | prior_deferred) - set(loaded):
            destroy(icon)
        setattr(
            window,
            "_stockroom_icon_handles",
            {
                which: icon
                for ((_dimensions, which), icon) in zip(
                    requested,
                    loaded,
                    strict=True,
                )
            },
        )
        setattr(window, "_stockroom_deferred_icon_handles", set())
        return True
    except Exception:  # noqa: BLE001 - cosmetic only; never block or crash the host
        _log.debug("window icon apply failed", exc_info=True)
        return False


def _webview_start_kwargs(start_fn, profile_dir) -> dict:
    """Return supported kwargs for the persistent native-shell WebView profile.

    pywebview configures storage once at ``webview.start``. The provider-only
    window uses this same persistent native-shell profile so sign-in survives,
    while rendered-DOM automation remains isolated elsewhere.
    """

    import inspect

    params = inspect.signature(start_fn).parameters
    kwargs: dict = {}
    if "private_mode" in params:
        kwargs["private_mode"] = False
    if "storage_path" in params:
        kwargs["storage_path"] = str(profile_dir)
    return kwargs


def _begin_native_webview_download_lease() -> str:
    """Mark the one WebView whose downloads are owned by the browser-domain broker."""

    global _NATIVE_DOWNLOAD_LEASE, _NATIVE_DOWNLOAD_SEQUENCE
    token = os.urandom(16).hex()
    with _NATIVE_DOWNLOAD_GUARD:
        if _NATIVE_DOWNLOAD_LEASE is not None:
            raise RuntimeError("a native provider download lease is already active")
        _NATIVE_DOWNLOAD_LEASE = token
        _NATIVE_DOWNLOAD_SEQUENCE = 0
        _NATIVE_DOWNLOAD_EVENTS.clear()
    return token


def _end_native_webview_download_lease(lease_token: str) -> None:
    """Release the host-side Save-As suppression for one provider task."""

    global _NATIVE_DOWNLOAD_LEASE
    with _NATIVE_DOWNLOAD_GUARD:
        if _NATIVE_DOWNLOAD_LEASE == lease_token:
            _NATIVE_DOWNLOAD_LEASE = None


def _discard_native_webview_downloads() -> None:
    """Clear provider Save-As suppression during host teardown."""

    global _NATIVE_DOWNLOAD_LEASE
    with _NATIVE_DOWNLOAD_GUARD:
        _NATIVE_DOWNLOAD_LEASE = None
        _NATIVE_DOWNLOAD_EVENTS.clear()


def _record_in_app_download(
    *,
    operation_id: str,
    phase: str,
    state: str,
    uri: str,
    result_file_path: str,
    suggested_file_name: str = "",
) -> None:
    global _NATIVE_DOWNLOAD_SEQUENCE
    with _NATIVE_DOWNLOAD_GUARD:
        if _NATIVE_DOWNLOAD_LEASE is None:
            return
        _NATIVE_DOWNLOAD_SEQUENCE += 1
        _NATIVE_DOWNLOAD_EVENTS.append(
            InAppProviderDownloadEvent(
                sequence=_NATIVE_DOWNLOAD_SEQUENCE,
                operation_id=operation_id,
                phase=phase,
                state=state,
                uri=uri,
                suggested_file_name=suggested_file_name or Path(result_file_path).name,
                result_file_path=result_file_path,
            )
        )


def _in_app_download_state(operation) -> str:
    name = str(getattr(operation, "State", "")).lower()
    if "completed" in name:
        return "completed"
    if "interrupted" in name:
        return "interrupted"
    return "in_progress"


def _in_app_download_name(operation, result_file_path: str) -> str:
    from email.message import Message

    disposition = str(getattr(operation, "ContentDisposition", "") or "")
    if disposition:
        message = Message()
        message["Content-Disposition"] = disposition
        declared = message.get_filename()
        if declared:
            return Path(declared).name
    uri = str(getattr(operation, "Uri", "") or "")
    path_name = Path(unquote(urlsplit(uri).path)).name
    if path_name and Path(path_name).suffix:
        return path_name
    return Path(result_file_path).name or "cad-download"


def _install_silent_webview2_download_handler(
    webview_module,
    edge_cls=None,
) -> None:
    """Suppress pywebview's Save-As dialog while the CDP broker owns downloads.

    The capture browser configures one browser-domain ``allowAndName`` directory and observes
    ``downloadWillBegin`` / ``downloadProgress`` for the exact active task.  The host has one job:
    keep pywebview from opening a competing native Save-As dialog.  It must not choose another
    path or maintain a second completion state machine.
    """

    if edge_cls is None:
        try:
            from webview.platforms.edgechromium import EdgeChrome
        except (ImportError, ModuleNotFoundError):
            # Test doubles and non-Windows pywebview backends do not expose EdgeChrome. They have
            # no WinForms Save As handler to replace; the real Windows WebView2 import remains the
            # only production installation path.
            return

        edge_cls = EdgeChrome
    if bool(getattr(edge_cls, "_stockroom_silent_downloads", False)):
        return

    settings = webview_module.settings
    original_handler = edge_cls.on_download_starting

    def on_download_starting(self, sender, args) -> None:
        with _NATIVE_DOWNLOAD_GUARD:
            lease_token = _NATIVE_DOWNLOAD_LEASE
        if lease_token is None:
            original_handler(self, sender, args)
            return
        if not bool(settings["ALLOW_DOWNLOADS"]):
            args.Cancel = True
            return
        # Do not touch ResultFilePath. Browser.setDownloadBehavior already selected the task's
        # private GUID path, and its terminal event is the single completion authority.
        setter = getattr(args, "set_Handled", None)
        if callable(setter):
            setter(True)
        else:
            args.Handled = True
        # WebView2 can still open its Download Hub even when the host handled the event. The
        # browser-domain broker has already retained the bytes and exposes progress in Stockroom's
        # own HUD, so close that redundant native flyout without taking ownership of the file.
        close_download_dialog = getattr(sender, "CloseDefaultDownloadDialog", None)
        if callable(close_download_dialog):
            try:
                close_download_dialog()
            except Exception:  # noqa: BLE001 - a missing/closing flyout is already the goal
                pass
        operation = getattr(args, "DownloadOperation", None)
        if operation is None:
            return
        operation_id = os.urandom(16).hex()
        result_file_path = str(getattr(args, "ResultFilePath", "") or "")
        uri = str(getattr(operation, "Uri", "") or "")
        _record_in_app_download(
            operation_id=operation_id,
            phase="started",
            state=_in_app_download_state(operation),
            uri=uri,
            result_file_path=result_file_path,
            suggested_file_name=_in_app_download_name(operation, result_file_path),
        )
        terminal_recorded = False

        def state_changed(_sender, _event_args) -> None:
            nonlocal terminal_recorded
            state = _in_app_download_state(operation)
            if state not in {"completed", "interrupted"} or terminal_recorded:
                return
            terminal_recorded = True
            try:
                operation.StateChanged -= state_changed
            except Exception:  # noqa: BLE001 - terminal evidence is already retained
                pass
            _record_in_app_download(
                operation_id=operation_id,
                phase="terminal",
                state=state,
                uri=uri,
                result_file_path=result_file_path,
                suggested_file_name=_in_app_download_name(operation, result_file_path),
            )

        try:
            operation.StateChanged += state_changed
        except Exception:  # noqa: BLE001 - browser-domain events remain the primary path
            return
        state_changed(operation, None)

    edge_cls.on_download_starting = on_download_starting
    setattr(edge_cls, "_stockroom_silent_downloads", True)


def _mark_new_window_handled(args) -> None:
    """Consume the request before deciding anything, so no path can leak to the shell."""

    try:
        setter = getattr(args, "set_Handled", None)
        if callable(setter):
            setter(True)
        else:
            args.Handled = True
    except Exception:  # noqa: BLE001 - an unmarked request is refused below regardless
        _log.debug("could not consume a new-window request", exc_info=True)


def _new_window_request_url(args) -> str:
    getter = getattr(args, "get_Uri", None)
    try:
        return str((getter() if callable(getter) else getattr(args, "Uri", "")) or "")
    except Exception:  # noqa: BLE001 - an unreadable target is not a target
        return ""


def _new_window_document_is_stockroom(browser, sender) -> bool:
    """Whether the page that asked for a new window is Stockroom's own SPA.

    Fails closed: an unknown document is treated as a provider page, so the request stays
    inside this window rather than being handed to whatever program claims the scheme.
    """

    if not _APP_ORIGIN:
        return False
    for candidate in (
        getattr(sender, "Source", None),
        getattr(browser, "url", None),
    ):
        text = str(candidate or "")
        if text:
            return should_inject(text, _APP_ORIGIN)
    return False


def _install_in_window_new_window_handler(edge_cls=None) -> None:
    """Keep a provider page's ``target="_blank"`` inside Stockroom.

    pywebview ships ``OPEN_EXTERNAL_LINKS_IN_BROWSER`` switched on, so its own
    ``on_new_window_request`` hands the URL to ``webbrowser.open`` - the person's default browser,
    outside Stockroom, outside the lease, and outside the download journal that proves a file
    belongs to one component. That is exactly what a provider page must never be able to do.

    A request from a provider page is therefore navigated in this same window under the same
    lease, after the same https/no-credentials gate the native host applies. A request from
    Stockroom's own SPA keeps pywebview's behaviour: those links are Stockroom's, and opening one
    in the person's browser is the deliberate existing outcome.
    """

    if edge_cls is None:
        try:
            from webview.platforms.edgechromium import EdgeChrome
        except (ImportError, ModuleNotFoundError):
            # Test doubles and non-Windows backends expose no EdgeChrome and have no WebView2
            # new-window handler to replace.
            return
        edge_cls = EdgeChrome
    if bool(getattr(edge_cls, "_stockroom_in_window_new_windows", False)):
        return

    from stockroom.host.window_chrome import new_window_url_allowed

    original_handler = edge_cls.on_new_window_request

    def on_new_window_request(self, sender, args) -> None:
        _mark_new_window_handled(args)
        if _new_window_document_is_stockroom(self, sender):
            original_handler(self, sender, args)
            return
        url = _new_window_request_url(args)
        if not new_window_url_allowed(url):
            # Refused rather than redirected. A scheme the operating system would route to
            # another program is not a provider page's decision to make.
            return
        try:
            self.load_url(url)
        except Exception:  # noqa: BLE001 - a window mid-navigation keeps the current page
            _log.debug("could not open a provider link in this window", exc_info=True)

    edge_cls.on_new_window_request = on_new_window_request
    setattr(edge_cls, "_stockroom_in_window_new_windows", True)


def _subscribe_window_event(window, name: str, handler) -> bool:
    """Attach ``handler`` to one pywebview window event when that event exists.

    Older pywebview releases and the window doubles used in tests do not carry every event. A
    missing one costs its own feature and nothing else.
    """

    events = getattr(window, "events", None)
    hook = getattr(events, name, None)
    if hook is None:
        return False
    try:
        setattr(events, name, hook + handler)
    except Exception:  # noqa: BLE001 - an unsubscribable event simply has no subscriber
        _log.debug("could not subscribe to the window %s event", name, exc_info=True)
        return False
    return True


def _mount_window_chrome(window) -> None:
    """Bind provider-route state to the window thread without global controls."""

    global _WINDOW_CHROME
    from stockroom.host.window_chrome import WindowChrome

    form = getattr(window, "native", None)
    if form is None:
        return
    chrome = WindowChrome()
    if not chrome.mount(form):
        return
    _WINDOW_CHROME = chrome


def _attach_window_chrome_page(window) -> None:
    """Follow the WebView's navigation so Back / Forward / the address describe the real page."""

    chrome = _WINDOW_CHROME
    if chrome is None:
        return
    core = None
    try:
        core = window.native.browser.webview.CoreWebView2
    except Exception:  # noqa: BLE001 - a backend without WebView2 simply has no page controls
        _log.debug("window chrome found no WebView2 to follow", exc_info=True)
    if core is None:
        return
    chrome.dispatch(lambda: chrome.attach_core(core))


class ManagedWindowController:
    """Native-only command surface for one replacement WebView window.

    The per-launch API credential received by this controller is retained only
    in this process and overwritten when the controller shuts down.  This
    surface never serializes it into renderer JavaScript, URLs, health reports,
    or object representations.  The legacy server-rendered index still injects
    its own API token until the native WebView2 request-header challenger is
    qualified, so this seam alone is not a security-final host.
    """

    __slots__ = (
        "_api_credential",
        "_base_url",
        "_hidden",
        "_lock",
        "_renderer",
        "_shutdown",
        "_window",
        "_window_handle",
    )

    def __init__(
        self,
        *,
        window,
        base_url: str,
        api_credential: str,
        window_handle: int,
        renderer: str = "edgechromium",
    ) -> None:
        if not should_inject(base_url, base_url):
            raise ValueError("base_url must have a complete origin")
        if type(api_credential) is not str or not api_credential:
            raise ValueError("api_credential must be a non-empty string")
        if len(api_credential.encode("utf-8")) > 16 * 1024:
            raise ValueError("api_credential is too large")
        if type(window_handle) is not int or window_handle <= 0:
            raise ValueError("window_handle must be a positive integer")
        if type(renderer) is not str or not renderer:
            raise ValueError("renderer must be a non-empty string")
        self._window = window
        self._base_url = base_url
        self._api_credential = bytearray(api_credential, "utf-8")
        self._window_handle = window_handle
        self._renderer = renderer
        self._hidden = True
        self._shutdown = False
        self._lock = threading.RLock()

    @property
    def window_handle(self) -> int:
        return self._window_handle

    def _require_live(self) -> None:
        if self._shutdown:
            raise RuntimeError("managed window is shut down")

    def prepare_hidden(self, *, deadline_unix_ms: int) -> None:
        """Keep the candidate hidden before any visible handoff proof."""

        if type(deadline_unix_ms) is not int or deadline_unix_ms <= 0:
            raise ValueError("deadline_unix_ms must be a positive integer")
        if time.time_ns() // 1_000_000 > deadline_unix_ms:
            raise TimeoutError("managed-window prepare deadline expired")
        with self._lock:
            self._require_live()
            self._window.hide()
            self._hidden = True

    def show(self) -> None:
        with self._lock:
            self._require_live()
            self._window.show()
            self._hidden = False

    def focus(self) -> None:
        with self._lock:
            self._require_live()
            if self._hidden:
                raise RuntimeError("cannot focus a hidden managed window")
            restore = getattr(self._window, "restore", None)
            if callable(restore):
                restore()
            if not _is_windows():
                return
            try:
                import ctypes
                from ctypes import wintypes

                api = ctypes.windll.user32
                setter = api.SetForegroundWindow
                _set_signature(setter, [wintypes.HWND], wintypes.BOOL)
                setter(self._window_handle)
            except Exception:  # noqa: BLE001 - visibility proof remains authoritative
                _log.debug("managed window focus request failed", exc_info=True)

    def health(self) -> dict[str, object]:
        """Return the exact non-secret health fields used by the supervisor."""

        with self._lock:
            self._require_live()
            try:
                current_url = self._window.get_current_url()
            except Exception:  # noqa: BLE001 - unknown navigation fails closed
                current_url = None
            if not should_inject(current_url, self._base_url):
                raise RuntimeError("managed window left the Stockroom origin")
            return {
                "hwnd": self._window_handle,
                "current_url": current_url,
                "hidden": self._hidden,
                "visible": not self._hidden,
                "renderer": self._renderer,
            }

    def export_session(self) -> object:
        """Synchronously export the renderer's durable-session candidate."""

        with self._lock:
            self._require_live()
            return self._window.evaluate_js(
                "window.__STOCKROOM_EXPORT_UI_SESSION__"
                " ? window.__STOCKROOM_EXPORT_UI_SESSION__() : null"
            )

    def _zero_credential(self) -> None:
        for index in range(len(self._api_credential)):
            self._api_credential[index] = 0
        self._api_credential.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._hidden = True
            self._zero_credential()
            try:
                self._window.destroy()
            except Exception:  # noqa: BLE001 - an already-closed window is terminal
                _log.debug("managed window destroy request failed", exc_info=True)


def run_managed_window(
    *,
    base_url: str,
    api_credential: str,
    profile_dir: Path,
    command_loop: Callable[[ManagedWindowController], None],
) -> None:
    """Run one hidden-first replacement window until its native HWND closes."""

    global _ACTIVE_WINDOW, _APP_ORIGIN
    if not callable(command_loop):
        raise TypeError("command_loop must be callable")
    resolved_profile = Path(profile_dir).resolve()
    resolved_profile.mkdir(parents=True, exist_ok=True)

    _configure_windows_process_identity()
    import webview  # pywebview, WebView2 backend on Windows

    _install_silent_webview2_download_handler(webview)
    _APP_ORIGIN = base_url
    _install_in_window_new_window_handler()

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001 - older pywebview versions still launch
        pass

    window = webview.create_window(
        "Stockroom",
        url=base_url,
        width=1400,
        height=900,
        min_size=(960, 640),
        hidden=True,
        js_api=_HostApi(),
    )
    if window is None:
        raise RuntimeError("pywebview did not create the managed Stockroom window")

    controller: ManagedWindowController | None = None
    command_thread: threading.Thread | None = None
    command_errors: list[BaseException] = []
    startup_errors: list[BaseException] = []
    startup_lock = threading.Lock()
    startup_attempted = False

    def _run_commands(active: ManagedWindowController) -> None:
        try:
            command_loop(active)
        except BaseException as exc:
            command_errors.append(exc)
        finally:
            active.shutdown()

    def _on_loaded() -> None:
        global _ACTIVE_WINDOW
        nonlocal controller, command_thread, startup_attempted
        with startup_lock:
            if startup_attempted:
                return
            startup_attempted = True
            try:
                current_url = window.get_current_url()
                if not should_inject(current_url, base_url):
                    raise RuntimeError(
                        "managed window did not load the Stockroom origin"
                    )
                window_handle = _current_process_window_handle(window)
                if window_handle is None:
                    raise RuntimeError(
                        "managed window did not expose a verified native HWND"
                    )
                _apply_saved_window_geometry(window_handle)
                controller = ManagedWindowController(
                    window=window,
                    base_url=base_url,
                    api_credential=api_credential,
                    window_handle=window_handle,
                )
                _ACTIVE_WINDOW = window
                _apply_window_icon(window)
                command_thread = threading.Thread(
                    target=_run_commands,
                    args=(controller,),
                    name="Stockroom Window Handoff",
                    daemon=True,
                )
                command_thread.start()
            except BaseException as exc:
                startup_errors.append(exc)
                try:
                    window.destroy()
                except Exception:  # noqa: BLE001 - startup is already terminal
                    pass

    window.events.loaded += _on_loaded
    try:
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(resolved_profile),
        )
    finally:
        if controller is not None:
            controller.shutdown()
        if command_thread is not None:
            command_thread.join(timeout=1.0)
        _release_window_icons(window)
        _ACTIVE_WINDOW = None

    if startup_errors:
        raise RuntimeError("managed Stockroom window failed to become ready") from (
            startup_errors[0]
        )
    if not startup_attempted or controller is None:
        raise RuntimeError("managed Stockroom window closed before readiness")
    if command_errors:
        raise RuntimeError("managed Stockroom command loop failed") from command_errors[0]


def run_window(base_url: str, token: str) -> None:
    """Open Stockroom's visible WebView2 shell and block until it closes."""

    global _ACTIVE_WINDOW, _APP_ORIGIN, _WINDOW_CHROME
    _configure_windows_process_identity()
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    _install_silent_webview2_download_handler(webview)
    # Known before the window exists, so the very first new-window request can already tell
    # Stockroom's own page from a provider's.
    _APP_ORIGIN = base_url
    _install_in_window_new_window_handler()

    from stockroom.store.machine_config import config_dir

    # pywebview blocks downloads by default. Stockroom's own CSV, fabrication,
    # audit, and other Blob/anchor exports must retain the normal WebView2 flow.
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001 - an older pywebview without settings still runs
        pass

    # Development-only visibility for scripts/windrive.py and native UI audits.
    # Production never sets this environment variable.
    cdp_port = os.environ.get("STOCKROOM_CDP_PORT")
    if cdp_port:
        try:
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(cdp_port)
        except Exception:  # noqa: BLE001 - invalid input/older pywebview must not block launch
            pass

    # Real-window measurement found 884 px clean and 744 px structurally broken:
    # the fixed rail and picker left no usable detail-pane width below this floor.
    window = webview.create_window(
        "Stockroom",
        url=base_url,
        width=1400,
        height=900,
        min_size=(960, 640),
        js_api=_HostApi(),
    )
    if window is None:
        raise RuntimeError("pywebview did not create the Stockroom window")
    _ACTIVE_WINDOW = window

    def _follow_stockroom_window(*_arguments) -> None:
        surface = _PROVIDER_SURFACE
        if surface is not None:
            surface.reapply_provider_viewport()

    for event_name in ("moved", "resized"):
        event = getattr(window.events, event_name, None)
        if event is not None:
            event += _follow_stockroom_window

    def _spa_is_current() -> bool:
        try:
            current_url = window.get_current_url()
        except Exception:  # noqa: BLE001 - a backend without get_current_url fails closed
            current_url = None
        return should_inject(current_url, base_url)

    # Recovery belongs only to the initial renderer handoff. Once the Stockroom SPA has loaded,
    # later off-origin navigation can be an intentional provider-browser lease and must remain on
    # that provider until its asynchronous download lands.
    startup_recovery = {"remaining": 2}
    startup_complete = False

    def _on_loaded() -> None:
        nonlocal startup_complete
        # Re-authenticate after reload/update, but never inject into remote content.
        if _spa_is_current():
            startup_complete = True
            window.evaluate_js(inject_script(base_url, token))
            return
        if startup_complete:
            return
        if startup_recovery["remaining"] <= 0:
            return
        startup_recovery["remaining"] -= 1

        def _recover_startup_renderer() -> None:
            # A forced process handoff can briefly overlap the old WebView2
            # renderer releasing this persistent profile. Edge surfaces
            # RESULT_CODE_KILLED, whose built-in Refresh succeeds once release
            # completes. Perform the same explicit navigation automatically.
            time.sleep(3.0)
            if _spa_is_current():
                return
            try:
                separator = "&" if "?" in base_url else "?"
                window.load_url(
                    f"{base_url}{separator}__stockroom_recover={time.time_ns()}"
                )
            except Exception:  # noqa: BLE001 - the next loaded event owns the bounded retry
                _log.debug("Stockroom startup renderer recovery failed", exc_info=True)

        threading.Thread(
            target=_recover_startup_renderer,
            name="stockroom-webview-recovery",
            daemon=True,
        ).start()

    # ``before_show`` is pywebview's one synchronous, window-thread event: the WinForms form
    # exists and no page has painted yet, which is exactly when chrome may be added. ``loaded``
    # runs on a worker thread, so it only marshals the page hookup across.
    _subscribe_window_event(
        window,
        "before_show",
        lambda: _mount_window_chrome(window),
    )
    window.events.loaded += _on_loaded
    window.events.loaded += lambda: _attach_window_chrome_page(window)
    window.events.loaded += lambda: _apply_window_icon(window)

    profile_dir = config_dir() / "webview-profile"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # profile persistence is optional; launch is not
    try:
        webview.start(**_webview_start_kwargs(webview.start, profile_dir))
    finally:
        _release_window_icons(window)
        _ACTIVE_WINDOW = None
        _WINDOW_CHROME = None
