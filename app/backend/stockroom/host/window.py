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
from pathlib import Path
from urllib.parse import urlsplit

_log = logging.getLogger("stockroom.host.window")

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None


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


def inject_script(base_url: str, token: str, ui: dict | None = None) -> str:
    """Build the synchronous renderer bootstrap for API auth and UI preferences."""

    base = json.dumps(base_url)
    tok = json.dumps(token)
    # ``</script>`` inside a JSON string would otherwise close the injected element.
    prefs = json.dumps(ui or {}).replace("</", "<\\/")
    return (
        f"window.__API_BASE__ = {base};\n"
        f"window.__STOCKROOM_TOKEN__ = {tok};\n"
        f"window.__STOCKROOM_UI__ = {prefs};\n"
        "if ('serviceWorker' in navigator) {\n"
        "  navigator.serviceWorker.getRegistrations().then(function (rs) {\n"
        "    rs.forEach(function (r) { r.unregister(); });\n"
        "  });\n"
        "}\n"
    )


class _HostApi:
    """The narrow native shell API exposed only to the loopback renderer."""

    def pick_project_folder(self) -> list[str]:
        """Pick one Git repository or EDA project folder for the Projects linker."""

        import webview

        window = active_window()
        if window is None:
            return []
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
        )
        return list(result) if result else []


def _apply_window_icon(window_title: str) -> None:
    """Apply Stockroom's icon to the native window and taskbar, best effort."""

    if os.name != "nt":  # pragma: no cover - Windows-only cosmetic path
        return
    try:  # pragma: no cover - exercised only on the real Windows host
        import ctypes

        icon_path = Path(__file__).resolve().parent / "assets" / "stockroom.ico"
        if not icon_path.is_file():
            return
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            return
        load_from_file, image_icon = 0x0010, 1
        set_icon, icon_small, icon_big = 0x0080, 0, 1
        for size, which in ((16, icon_small), (32, icon_big)):
            icon = user32.LoadImageW(
                None,
                str(icon_path),
                image_icon,
                size,
                size,
                load_from_file,
            )
            if icon:
                user32.SendMessageW(hwnd, set_icon, which, icon)
    except Exception:  # noqa: BLE001 - cosmetic only; never block or crash the host
        _log.debug("window icon apply failed", exc_info=True)


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


def run_window(base_url: str, token: str) -> None:
    """Open Stockroom's visible WebView2 shell and block until it closes."""

    global _ACTIVE_WINDOW
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

    def _on_loaded() -> None:
        # Re-authenticate after reload/update, but never inject into remote content.
        if _spa_is_current():
            window.evaluate_js(inject_script(base_url, token))

    window.events.loaded += _on_loaded
    window.events.loaded += lambda: _apply_window_icon("Stockroom")

    profile_dir = config_dir() / "webview-profile"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # profile persistence is optional; launch is not
    try:
        webview.start(**_webview_start_kwargs(webview.start, profile_dir))
    finally:
        _ACTIVE_WINDOW = None
