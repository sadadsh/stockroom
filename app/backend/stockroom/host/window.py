"""The pywebview WebView2 window (spec section 3.7; knowledge-transfer section 2).

pywebview is NOT Qt; it hosts the FastAPI-served frontend in a native WebView2. It
injects the API base + per-launch token into the renderer so the SPA authenticates
every request, disables service workers (stale-bundle risk after a self-update),
routes native drag/drop full paths straight into the ingest endpoint (so large zips
skip an HTTP upload), and stops uvicorn on close (the host supervisor that started
the server thread does the stop after run_window returns). pywebview is imported
lazily inside run_window, so this module imports on Linux without it; the pure
helpers (inject_script, dropped_paths_to_inspect_body, active_window) are Linux-tested."""

from __future__ import annotations

import json

_ACTIVE_WINDOW = None


def active_window():
    return _ACTIVE_WINDOW


def dropped_paths_to_inspect_body(paths: list[str]) -> dict:
    """Native drag/drop delivers full filesystem paths; turn them into the exact
    /api/ingest/inspect body so a dropped zip skips an HTTP upload (spec section 3.7)."""
    return {"paths": list(paths), "lcsc_ids": []}


def inject_script(base_url: str, token: str) -> str:
    """The renderer bootstrap: set window.__STOCKROOM__ = {base, token} so the SPA
    authenticates every request, and unregister any service worker so a self-update
    never serves a stale bundle. Values are JSON-encoded so a token with a quote or
    backslash cannot break out of the JS string (defense in depth)."""
    payload = json.dumps({"base": base_url, "token": token})
    return (
        f"window.__STOCKROOM__ = {payload};\n"
        "if ('serviceWorker' in navigator) {\n"
        "  navigator.serviceWorker.getRegistrations().then(function (rs) {\n"
        "    rs.forEach(function (r) { r.unregister(); });\n"
        "  });\n"
        "}\n"
    )


def run_window(base_url: str, token: str) -> None:
    """Open the WebView2 window onto the FastAPI-served frontend and block until it
    closes. Injects the base+token on every load (so an SPA reload after self-update
    re-authenticates). The uvicorn server is owned + stopped by the host supervisor
    that called run_window (stockroom.host.run), which shuts it down once this returns."""
    global _ACTIVE_WINDOW
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    window = webview.create_window("Stockroom", url=base_url, width=1400, height=900)
    _ACTIVE_WINDOW = window

    def _on_loaded():
        # re-inject on EVERY load: after a self-update reload or an SPA route change
        # the renderer must always carry the base + token.
        window.evaluate_js(inject_script(base_url, token))

    window.events.loaded += _on_loaded
    # Native drag/drop: pywebview exposes each dropped file's full path
    # (pywebviewFullPath) to the renderer; the frontend (M6) POSTs those paths to
    # /api/ingest/inspect with the token, using the dropped_paths_to_inspect_body
    # contract. The full path stays out of any HTTP upload (spec section 3.7).
    try:
        webview.start()  # blocks until the window closes
    finally:
        _ACTIVE_WINDOW = None
