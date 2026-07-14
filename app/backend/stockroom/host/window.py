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

    def _on_loaded():
        # Re-inject on every SPA load (after a self-update reload or route change the
        # renderer must always carry the base + token), but ONLY when the loaded page
        # is the loopback SPA origin (never a remote page), so the token can never leak
        # to remote web content (defense in depth on top of the dedicated fetch window).
        try:
            current = window.get_current_url()
        except Exception:  # noqa: BLE001 - a backend without get_current_url fails closed
            current = None
        if should_inject(current, base_url):
            window.evaluate_js(inject_script(base_url, token))

    window.events.loaded += _on_loaded
    # Adding a vendor ZIP goes through the native file picker exposed as
    # window.pywebview.api.pick_ingest_files (js_api above): the frontend Ingest page gets real
    # filesystem paths and runs its normal inspect flow. Plain-DOM drag-drop is NOT relied on:
    # pywebview only injects a dropped file's full path when a drop handler is registered through
    # its own Python DOM API, so a browser-style window.addEventListener('drop') yields no paths.
    try:
        webview.start()  # blocks until the window closes
    finally:
        _ACTIVE_WINDOW = None
