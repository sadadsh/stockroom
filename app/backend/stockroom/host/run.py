"""The windowed host entry: the supervisor that ties the API server and the WebView2
window into one running app (spec section 3.7; the launcher's uv_run_app target).

It builds the app context, starts uvicorn on a loopback ephemeral port on a worker
thread, wires the real WebView2 RenderedDomFetcher onto the context (closing the M4
enrichment seam at runtime), opens the WebView2 window onto the FastAPI-served
frontend, and, the moment the window closes, stops the server so no orphaned
process lingers. The window is injectable (open_window) so the whole seam is
integration-tested on Linux with a real uvicorn server; only the actual WebView2
window is Windows-verified.

This lives in stockroom.host, never stockroom.api, so the API package stays a pure
headless ASGI app (spec section 2.1) and only the host imports the window layer."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from stockroom.api.context import AppContext
from stockroom.launcher.exit_codes import EXIT_RESTART

# EXIT_RESTART (the self-update restart exit code the launcher relaunches on) lives in the
# leaf module stockroom.launcher.exit_codes so the frozen launcher can import it without
# dragging this whole host/API module into the bundle (M9d). Re-exported here for the host.
__all__ = ["EXIT_RESTART", "run_windowed", "main"]


def _serve_in_thread(app, port: int, timeout: float = 15.0):
    """Start uvicorn on a daemon thread bound to loopback and return once it is
    accepting connections. Raises if it never comes up (honest, no silent hang).
    uvicorn skips signal-handler install off the main thread, so this is safe."""
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="stockroom-api")
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            thread.join(timeout=5.0)
            raise RuntimeError("the API server did not start within the timeout")
        time.sleep(0.02)
    return server, thread


def _open_window(base_url: str, token: str) -> None:
    # lazy so importing stockroom.host.run on Linux never touches pywebview
    from stockroom.host.window import run_window

    run_window(base_url, token)


def _close_active_window() -> None:
    """Host restart hook for the self-updater: closing the window returns from
    run_window, which stops the server, so the process exits and the launcher can
    relaunch on the freshly pulled code. The relaunch loop itself is Windows-verified;
    on Linux (no window) this is a safe no-op."""
    from stockroom.host.window import active_window

    win = active_window()
    if win is not None:
        win.destroy()


def _install_injected_index(app, base_url: str, token: str) -> None:
    """Insert a route that serves index.html with window.__API_BASE__ + __STOCKROOM_TOKEN__
    already injected, taking precedence over the SPA static mount, so the SPA is authenticated
    from its very first byte. Without this the token arrives only via the window's on-loaded
    evaluate_js, which lands AFTER the SPA's initial queries fire, so a no-retry query like
    onboarding 401s once and never recovers (hiding the first-run setup screen). No-op if the
    built frontend is absent."""
    from stockroom.api.app import _FRONTEND_DIST
    from stockroom.host.window import inject_script

    index = _FRONTEND_DIST / "index.html"
    if not index.exists():
        return
    from starlette.responses import HTMLResponse
    from starlette.routing import Route

    html = index.read_text(encoding="utf-8")
    injected = html.replace(
        "<head>", "<head>\n<script>" + inject_script(base_url, token) + "</script>", 1
    )

    async def _index(_request):
        return HTMLResponse(injected)

    app.router.routes.insert(0, Route("/", _index))
    app.router.routes.insert(1, Route("/index.html", _index))


def run_windowed(
    ctx: AppContext | None = None,
    libraries_root: Path | None = None,
    kicad_dir: Path | None = None,
    open_window: Callable[[str, str], None] | None = None,
) -> bool:
    """Run the app until the window closes. Returns True if the app requested a self-update
    restart (the launcher relaunches on the freshly pulled code), False on a normal close."""
    from stockroom.api.app import create_app
    from stockroom.api.serve import build_context, pick_free_port
    from stockroom.host.webview_fetch import WebViewRenderedDomFetcher

    if ctx is None:
        ctx = build_context(libraries_root, kicad_dir=kicad_dir)
    # Close the M4 seam at runtime: enrich now renders bot-protected pages through the
    # live WebView2 engine (resolved lazily from the running window on Windows).
    if ctx.rendered_dom_fetcher is None:
        ctx.rendered_dom_fetcher = WebViewRenderedDomFetcher()
    # Give the self-updater a real restart hook instead of the no-op default: the updater
    # (updater.py) calls this AFTER a successful git pull + uv sync, so flag the restart
    # intent, then close the window. run_windowed then returns True and main() exits
    # EXIT_RESTART, which the frozen launcher recognizes and relaunches on (M9d).
    restart_requested = {"value": False}

    def _request_restart() -> None:
        restart_requested["value"] = True
        _close_active_window()

    ctx.request_restart = _request_restart

    app = create_app(ctx)
    port = pick_free_port()
    base_url = f"http://127.0.0.1:{port}"
    _install_injected_index(app, base_url, ctx.token)  # authenticate the SPA from its first byte
    server, thread = _serve_in_thread(app, port)
    opener = open_window or _open_window
    try:
        opener(base_url, ctx.token)  # blocks until the window closes
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
    return restart_requested["value"]


def main() -> None:  # pragma: no cover - the real Windows-run entry (uv run target)
    if run_windowed():
        raise SystemExit(EXIT_RESTART)


if __name__ == "__main__":  # pragma: no cover
    main()
