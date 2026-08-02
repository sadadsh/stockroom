"""The thin pywebview/WebView2 desktop shell.

The shell hosts Stockroom's FastAPI-served frontend, injects the loopback API
base and per-launch token, owns native window lifecycle, exposes the project
folder picker, and provides one separate hidden window to the rendered-DOM
fetcher. Provider acquisition is not a host responsibility: the capture package
owns its isolated Playwright/CloakBrowser sessions, task-bound downloads, and
provider HUD.

pywebview is imported lazily inside the Windows-only entry points so this module
and its pure helpers remain importable on every supported platform.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

_log = logging.getLogger("stockroom.host.window")

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None

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
    token_line = (
        ""
        if token is None
        else f"window.__STOCKROOM_TOKEN__ = {json.dumps(token)};\n"
    )
    return (
        f"window.__API_BASE__ = {base};\n"
        + token_line
        + (
        f"window.__STOCKROOM_UI__ = {prefs};\n"
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

    pywebview configures storage once at ``webview.start``. Provider sessions do
    not share this profile; they use provider-scoped Chromium profiles owned by
    the capture package.
    """

    import inspect

    params = inspect.signature(start_fn).parameters
    kwargs: dict = {}
    if "private_mode" in params:
        kwargs["private_mode"] = False
    if "storage_path" in params:
        kwargs["storage_path"] = str(profile_dir)
    return kwargs


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

    global _ACTIVE_WINDOW
    if not callable(command_loop):
        raise TypeError("command_loop must be callable")
    resolved_profile = Path(profile_dir).resolve()
    resolved_profile.mkdir(parents=True, exist_ok=True)

    _configure_windows_process_identity()
    import webview  # pywebview, WebView2 backend on Windows

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

    global _ACTIVE_WINDOW
    _configure_windows_process_identity()
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

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

    def _spa_is_current() -> bool:
        try:
            current_url = window.get_current_url()
        except Exception:  # noqa: BLE001 - a backend without get_current_url fails closed
            current_url = None
        return should_inject(current_url, base_url)

    startup_recovery = {"remaining": 2}

    def _on_loaded() -> None:
        # Re-authenticate after reload/update, but never inject into remote content.
        if _spa_is_current():
            window.evaluate_js(inject_script(base_url, token))
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

    window.events.loaded += _on_loaded
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
