"""The pywebview WebView2 window (spec section 3.7; knowledge-transfer section 2).

pywebview is NOT Qt; it hosts the FastAPI-served frontend in a native WebView2. It
injects the API base + per-launch token into the renderer so the SPA authenticates
every request, disables service workers (stale-bundle risk after a self-update),
exposes a native file picker to Ingest via js_api (window.pywebview.api.pick_ingest_files,
so a vendor zip skips an HTTP upload), and stops uvicorn on close (the host supervisor that started
the server thread does the stop after run_window returns). pywebview is imported
lazily inside run_window, so this module imports on Linux without it; the pure
helpers (inject_script, dropped_paths_to_inspect_body, active_window) are Linux-tested."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None


def active_window():
    return _ACTIVE_WINDOW


def fetch_window():
    """A DEDICATED hidden window for the RenderedDomFetcher, separate from the SPA
    window. Created lazily on first use (Windows). It is distinct from active_window()
    by construction and never gets the token-injecting `loaded` handler, so navigating
    it to a bot-protected vendor page can neither leak the per-launch token to that
    remote content nor hijack the user's visible app view."""
    global _FETCH_WINDOW
    if _FETCH_WINDOW is None:
        import webview  # pywebview, WebView2 on Windows; lazy so Linux imports

        _FETCH_WINDOW = webview.create_window("stockroom-fetch", hidden=True)
    return _FETCH_WINDOW


def should_inject(current_url: str | None, base_url: str) -> bool:
    """Inject the token ONLY when the loaded page is the loopback SPA origin, never a
    remote vendor page. The token is the sole guard on the local API (loopback + token,
    defense in depth), so it must never be handed to remote web content. Fails CLOSED:
    an unknown/blank current URL does not receive the token."""
    if not current_url:
        return False
    a, b = urlsplit(current_url), urlsplit(base_url)
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def dropped_paths_to_inspect_body(paths: list[str]) -> dict:
    """Native drag/drop delivers full filesystem paths; turn them into the exact
    /api/ingest/inspect body so a dropped zip skips an HTTP upload (spec section 3.7)."""
    return {"paths": list(paths), "lcsc_ids": []}


def native_drop_paths(event) -> list[str]:
    """The real filesystem paths from a pywebview DOM drop event. WebView2 exposes
    a dropped file's path (pywebviewFullPath) ONLY to handlers registered through
    pywebview's DOM API, so this is the one channel that ever sees them. Defensive
    against any malformed event shape: junk yields [], never a crash."""
    try:
        files = (event or {}).get("dataTransfer", {}).get("files") or []
    except AttributeError:
        return []
    paths: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        path = f.get("pywebviewFullPath")
        if isinstance(path, str) and path:
            paths.append(path)
    return paths


def drop_forward_js(paths: list[str]) -> str:
    """The renderer call that hands native drop paths to the SPA's ingest queue.
    Guarded so a renderer that has not registered the hook is a no-op, and
    JSON-encoded so a quote or backslash in a path cannot break out of the script."""
    encoded = json.dumps(list(paths))
    return (
        "window.__STOCKROOM_NATIVE_DROP__ && "
        f"window.__STOCKROOM_NATIVE_DROP__({encoded});"
    )


def inject_script(base_url: str, token: str) -> str:
    """The renderer bootstrap: set the two globals the SPA actually reads: the
    frontend's runtime.ts reads window.__API_BASE__ and window.__STOCKROOM_TOKEN__,
    so the SPA authenticates every request, and unregister any service worker so a
    self-update never serves a stale bundle. Values are JSON-encoded so a token with a
    quote or backslash cannot break out of the JS string (defense in depth)."""
    base = json.dumps(base_url)
    tok = json.dumps(token)
    return (
        f"window.__API_BASE__ = {base};\n"
        f"window.__STOCKROOM_TOKEN__ = {tok};\n"
        "if ('serviceWorker' in navigator) {\n"
        "  navigator.serviceWorker.getRegistrations().then(function (rs) {\n"
        "    rs.forEach(function (r) { r.unregister(); });\n"
        "  });\n"
        "}\n"
    )


class _HostApi:
    """The js_api pywebview exposes to the renderer as `window.pywebview.api`. It gives Ingest a
    NATIVE file picker for vendor ZIPs, so adding a part never depends on pywebview's drag-drop
    path injection (which only fires when a drop handler is registered through pywebview's own
    Python DOM API, and otherwise silently yields NO paths in WebView2). Returns real filesystem
    paths straight to the frontend, which runs its normal inspect flow."""

    def pick_ingest_files(self) -> list[str]:
        import webview

        win = active_window()
        if win is None:
            return []
        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Vendor packages (*.zip)", "All files (*.*)"),
        )
        return list(result) if result else []


def run_window(base_url: str, token: str) -> None:
    """Open the WebView2 window onto the FastAPI-served frontend and block until it
    closes. Injects the base+token on every load (so an SPA reload after self-update
    re-authenticates). The uvicorn server is owned + stopped by the host supervisor
    that called run_window (stockroom.host.run), which shuts it down once this returns."""
    global _ACTIVE_WINDOW
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    window = webview.create_window(
        "Stockroom", url=base_url, width=1400, height=900, js_api=_HostApi()
    )
    _ACTIVE_WINDOW = window

    def _spa_is_current() -> bool:
        try:
            current = window.get_current_url()
        except Exception:  # noqa: BLE001 - a backend without get_current_url fails closed
            current = None
        return should_inject(current, base_url)

    def _on_native_drop(event) -> None:
        # Forward the dropped files' real paths into the SPA's ingest queue, but only
        # while the loopback SPA is the loaded page (never a remote page).
        if not _spa_is_current():
            return
        paths = native_drop_paths(event)
        if paths:
            window.evaluate_js(drop_forward_js(paths))

    drop_bound = {"value": False}

    def _bind_native_drop() -> None:
        # WebView2 exposes dropped-file paths ONLY to handlers registered through
        # pywebview's DOM API; the frontend's window.addEventListener('drop') gets File
        # objects with NO path. So the host registers the real handler here and hands
        # the paths to the SPA via the guarded __STOCKROOM_NATIVE_DROP__ hook. Bound
        # once (loaded fires on every SPA reload). Degrades honestly: on a pywebview
        # without DOM events the native file picker still covers adding parts.
        if drop_bound["value"]:
            return
        try:
            from webview.dom import DOMEventHandler

            window.dom.document.events.dragover += DOMEventHandler(
                lambda e: None, prevent_default=True, stop_propagation=False, debounce=500
            )
            window.dom.document.events.drop += DOMEventHandler(
                _on_native_drop, prevent_default=True, stop_propagation=False
            )
            drop_bound["value"] = True
        except Exception:  # noqa: BLE001 - drag-drop is an enhancement over the picker
            pass

    def _on_loaded():
        # Re-inject on every SPA load (after a self-update reload or route change the
        # renderer must always carry the base + token), but ONLY when the loaded page
        # is the loopback SPA origin (never a remote page), so the token can never leak
        # to remote web content (defense in depth on top of the dedicated fetch window).
        if not _spa_is_current():
            return
        window.evaluate_js(inject_script(base_url, token))
        _bind_native_drop()

    window.events.loaded += _on_loaded
    # Adding a vendor ZIP also works through the native file picker exposed as
    # window.pywebview.api.pick_ingest_files (js_api above), the fallback path that
    # never depends on the drag-drop DOM registration above.
    try:
        webview.start()  # blocks until the window closes
    finally:
        _ACTIVE_WINDOW = None
