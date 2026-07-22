"""The pywebview WebView2 window (spec section 3.7; knowledge-transfer section 2).

pywebview is NOT Qt; it hosts the FastAPI-served frontend in a native WebView2. It
injects the API base + per-launch token into the renderer so the SPA authenticates
every request, disables service workers (stale-bundle risk after a self-update),
exposes a native file picker to Ingest via js_api (window.pywebview.api.pick_ingest_files,
so a vendor zip skips an HTTP upload), and stops uvicorn on close (the host supervisor that started
the server thread does the stop after run_window returns). pywebview is imported
lazily inside run_window, so this module imports on Linux without it; the pure
helpers (inject_script, dropped_paths_to_inspect_body, active_window) are Linux-tested.

Also opens a distributor's CAD-download page (DigiKey product page etc.) in a dedicated,
VISIBLE second window and captures the ZIP it downloads (plan
docs/superpowers/plans/2026-07-18-digikey-asset-download.md, Task 3) - see the "CAD-source
download capture" section below and _HostApi.open_cad_download. That wiring is Windows-only
and owner-verified; the module still imports cleanly on Linux (pywebview-specific calls stay
inside functions/guards, same discipline as the rest of this file)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None
_CAD_WINDOW = None
_CAD_DOWNLOADS_WATCH = None
_CAD_CAPTURE_LOCK = threading.Lock()


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


def bind_native_drop(window, on_drop, dom_event_handler=None) -> bool:
    """Register the native drop + dragover handlers through pywebview's DOM API on
    the window's CURRENT document. Returns True when it bound, False on any failure
    (drag-drop is an enhancement over the file picker, never a hard dependency).

    Rebinding is the CALLER's job: an SPA reload (e.g. after a self-update) replaces
    window.dom.document, so the handlers registered on the old document are gone and
    this must run again against the new one. A stale bind-once flag was the bug that
    silently killed drag-drop after the first reload."""
    try:
        if dom_event_handler is None:
            from webview.dom import DOMEventHandler as dom_event_handler
        doc = window.dom.document
        # dragover must preventDefault so the drop event fires at all
        doc.events.dragover += dom_event_handler(
            lambda e: None, prevent_default=True, stop_propagation=False, debounce=500
        )
        doc.events.drop += dom_event_handler(
            on_drop, prevent_default=True, stop_propagation=False
        )
        return True
    except Exception:  # noqa: BLE001 - drag-drop is an enhancement; never break the app
        return False


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


# -- CAD-source download capture (plan docs/superpowers/plans/2026-07-18-digikey-asset-
# download.md, Task 3): opening a distributor's CAD page (e.g. a DigiKey product page) in
# a dedicated window and getting the ZIP it downloads back to the SPA without a manual
# drag/drop. Two tiers, because pywebview exposes NO public download-intercept API
# (verified against pywebview's vendored WebView2 backend, 2026-07: ALLOW_DOWNLOADS only
# ever triggers pywebview's OWN native Save-As dialog via edgechromium.py::
# on_download_starting; there is no download-related entry in its public event set):
#
#   tier 1 (best-effort, Windows only): _install_cad_download_intercept reaches into
#   pywebview's internals and redirects THIS ONE window's download save-path, degrading
#   silently (never raising) on any shape mismatch.
#
#   tier 2 (always available): a DownloadsWatch (download_capture.py - pure, Linux-tested)
#   polled on a background thread, the backstop for whatever tier 1 cannot reach.
#
# Whichever tier finds the file first forwards it to the SPA via
# window.__STOCKROOM_CAD_DOWNLOAD__(path) - the SAME convergence point regardless of which
# tier fired, so the frontend (Task 4) never has to know which one won. Tier 3 is the
# existing manual pick_ingest_files() picker, unchanged.


def cad_window():
    return _CAD_WINDOW


def cad_downloads_watch():
    return _CAD_DOWNLOADS_WATCH


def cad_forward_js(path: str) -> str:
    """The renderer call that hands a captured CAD-download ZIP path to the SPA, exactly
    mirroring drop_forward_js. Guarded so a renderer that has not registered the hook is a
    no-op, and JSON-encoded so a quote/backslash in a path cannot break out of the script."""
    encoded = json.dumps(str(path))
    return (
        "window.__STOCKROOM_CAD_DOWNLOAD__ && "
        f"window.__STOCKROOM_CAD_DOWNLOAD__({encoded});"
    )


def _forward_cad_capture(path) -> None:
    """Hand a captured path to the SPA on the MAIN window - never on the remote cad
    window, which never loads the SPA and so never has the forwarding hook registered."""
    spa = active_window()
    if spa is not None:
        spa.evaluate_js(cad_forward_js(str(path)))


def _fire_cad_capture_once(path, state: dict) -> bool:
    """Thread-safe single-fire gate shared by both tiers for one open_cad_download() call:
    tier 1 (a WebView2 COM callback thread) and tier 2 (the poll thread below) race to
    report a captured path, and only the FIRST one to arrive wins - the loser's later find
    is real but redundant (the same completed download, or a stray leftover zip) once the
    SPA already has a path to inspect."""
    with _CAD_CAPTURE_LOCK:
        if state["fired"]:
            return False
        state["fired"] = True
        state["stop"] = True
    return True


def _poll_downloads_watch(
    watch,
    state: dict,
    *,
    interval: float = 1.5,
    timeout: float = 300.0,
    sleep=time.sleep,
    now=time.time,
) -> None:
    """TIER 2 background loop: poll `watch` (download_capture.DownloadsWatch) until it
    finds a zip, a tier-1 capture flags state["stop"], or `timeout` elapses with nothing
    found. Runs on a daemon thread started by open_cad_download. This function has zero
    pywebview dependency (importable and callable on Linux), but only ever actually finds
    a real file on a Windows machine watching a real Downloads folder."""
    deadline = now() + timeout
    while now() < deadline and not state["stop"]:
        found = watch.poll()
        if found is not None:
            if _fire_cad_capture_once(found, state):
                _forward_cad_capture(found)
            return
        sleep(interval)


def _install_cad_download_intercept(window, target_dir: Path, on_captured, state: dict) -> bool:
    """TIER 1 (best-effort, Windows only): reach past pywebview's public API - which
    exposes NO download hook, only the ALLOW_DOWNLOADS setting that triggers pywebview's
    own native Save-As dialog - into its vendored WebView2 backend, and redirect THIS ONE
    window's next download save-path into `target_dir`, notifying `on_captured(path)` once
    WebView2 reports the download Completed.

    Why a per-INSTANCE monkeypatch, not a per-CLASS one: pywebview's Windows browser
    (webview.platforms.winforms.BrowserView -> webview.platforms.edgechromium.EdgeChrome)
    wires `sender.CoreWebView2.DownloadStarting += self.on_download_starting` exactly once
    per window, inside EdgeChrome.on_webview_ready, when THAT window's CoreWebView2 finishes
    its async init (verified against pywebview's vendored source, 2026-07). That `+=`
    resolves `self.on_download_starting` at THAT moment; patching the CLASS method would
    hijack EVERY window's downloads, including the main SPA window's BOM CSV / fab zip /
    audit-markdown Blob exports, which must keep their normal Save-As flow (see
    run_window's ALLOW_DOWNLOADS comment). Patching the INSTANCE attribute on just THIS
    window's EdgeChrome object - installed immediately after webview.create_window()
    returns, synchronously before on_webview_ready has had any chance to run - scopes the
    redirect to this one distributor window only.

    Returns True once the monkeypatch itself is installed (BrowserView and its browser
    instance were found); False if pywebview's internals do not match this shape (a
    different pywebview version, a non-EdgeChrome renderer) - the caller still has tier 2
    armed regardless. Never raises: this reaches into library internals pywebview gives no
    compatibility guarantee on, so ANY shape mismatch must degrade, never crash the running
    app. If the per-download handler cannot subscribe to the WebView2 download's completion
    signal, it deliberately does NOT redirect the save path either, so the file falls
    through to WebView2's own default save location (the OS Downloads folder) - exactly
    where tier 2 is already watching, rather than landing, uncaptured, in a temp dir tier 2
    never looks at."""
    if os.name != "nt":
        return False
    try:
        from webview.platforms.winforms import BrowserView  # pywebview's Windows backend
    except Exception:  # noqa: BLE001 - not the expected Windows backend; tier 2 still covers it
        return False

    browser_form = BrowserView.instances.get(getattr(window, "uid", None))
    edge = getattr(browser_form, "browser", None)
    if edge is None:
        return False

    def _on_download_starting(sender, args) -> None:
        try:
            operation = args.DownloadOperation
        except Exception:  # noqa: BLE001 - can't observe completion; let it save to the
            return  # default location (OS Downloads) where tier 2 is watching

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            name = os.path.basename(str(args.ResultFilePath)) or "cad-download.zip"
            dest = target_dir / name

            def _on_state_changed(op_sender, op_args) -> None:
                try:
                    from Microsoft.Web.WebView2.Core import CoreWebView2DownloadState

                    done = operation.State == CoreWebView2DownloadState.Completed
                except Exception:  # noqa: BLE001 - best-effort: treat an unreadable state as done
                    done = True
                if done and _fire_cad_capture_once(dest, state):
                    on_captured(dest)

            operation.StateChanged += _on_state_changed
            args.ResultFilePath = str(dest)
            args.Handled = True  # skip pywebview's native Save-As dialog for this window
        except Exception:  # noqa: BLE001 - best-effort; fall through to the default save flow
            return

    try:
        edge.on_download_starting = _on_download_starting
    except Exception:  # noqa: BLE001 - could not patch this instance; tier 2 still covers it
        return False
    return True


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

    def pick_altium_files(self) -> list[str]:
        """A native picker for a part's Altium assets: a .SchLib + .PcbLib pair, or a single
        compiled .IntLib. Returns real filesystem paths straight to the frontend, which posts
        them to /api/altium/parts/{id}/attach (the same host-captured-path path as ingest)."""
        import webview

        win = active_window()
        if win is None:
            return []
        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Altium libraries (*.IntLib;*.SchLib;*.PcbLib)", "All files (*.*)"),
        )
        return list(result) if result else []

    def pick_datasheet_file(self) -> list[str]:
        """A native picker for the part's datasheet PDF, so Autofill can attach a
        file already on disk (the frontend sends its path as datasheet_file)."""
        import webview

        win = active_window()
        if win is None:
            return []
        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Datasheet PDF (*.pdf)", "All files (*.*)"),
        )
        return list(result) if result else []

    def open_cad_download(self, url: str) -> None:
        """Open a distributor's CAD-download page (e.g. a DigiKey product page) in a
        SECOND, VISIBLE window dedicated to this one flow - the fetch_window() precedent,
        but visible instead of hidden, since the owner clicks the vendor's own Download
        button on it. This window gets NO `loaded` handler at all - not merely relying on
        should_inject's origin guard, there is simply no wiring through which the
        per-launch token could ever reach this remote page - and NO js_api bridge either,
        so nothing this app exposes is reachable from remote content.

        Arms BOTH capture tiers on every call: tier 1 best-effort redirects this window's
        next WebView2 download into a fresh app temp dir
        (_install_cad_download_intercept, Windows only, degrades silently); tier 2 arms a
        DownloadsWatch over the OS Downloads folder as of right now and polls it on a
        daemon thread, the always-available backstop for whatever tier 1 cannot reach (an
        unexpected pywebview version, a non-EdgeChrome renderer, a WebView2 quirk).
        Whichever tier finds the ZIP first forwards it to the SPA via
        window.__STOCKROOM_CAD_DOWNLOAD__(path); the other tier's late or redundant find
        is dropped by the shared single-fire gate (_fire_cad_capture_once).

        Replaces any cad window left over from a previous call (closing it first) rather
        than piling up extra windows across repeated clicks."""
        global _CAD_WINDOW, _CAD_DOWNLOADS_WATCH
        import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

        from stockroom.host.download_capture import DownloadsWatch, default_downloads_dir

        if _CAD_WINDOW is not None:
            try:
                _CAD_WINDOW.destroy()
            except Exception:  # noqa: BLE001 - already closed/invalid; we're replacing it anyway
                pass
            _CAD_WINDOW = None

        win = webview.create_window("stockroom-cad", url=url, width=1200, height=900)
        _CAD_WINDOW = win

        def _on_cad_closed() -> None:
            global _CAD_WINDOW
            if _CAD_WINDOW is win:
                _CAD_WINDOW = None

        win.events.closed += _on_cad_closed

        capture_state = {"fired": False, "stop": False}
        target_dir = Path(tempfile.mkdtemp(prefix="stockroom-cad-"))
        _install_cad_download_intercept(win, target_dir, _forward_cad_capture, capture_state)

        watch = DownloadsWatch.start(default_downloads_dir())
        _CAD_DOWNLOADS_WATCH = watch
        threading.Thread(
            target=_poll_downloads_watch, args=(watch, capture_state), daemon=True
        ).start()


def run_window(base_url: str, token: str) -> None:
    """Open the WebView2 window onto the FastAPI-served frontend and block until it
    closes. Injects the base+token on every load (so an SPA reload after self-update
    re-authenticates). The uvicorn server is owned + stopped by the host supervisor
    that called run_window (stockroom.host.run), which shuts it down once this returns."""
    global _ACTIVE_WINDOW
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    # pywebview blocks ALL downloads by default, which silently kills every export
    # in the app (the BOM CSV, the fab zip, the audit markdown are Blob+anchor
    # downloads). Enable them so WebView2 shows its normal download flow. Module
    # global, so the hidden fetch window inherits it too: acceptable, its vendor
    # pages are user-initiated enrichment fetches and a download needs user action.
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001 - an older pywebview without settings still runs
        pass

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

    # Track WHICH document the drop handlers are bound to (by identity), so a reload
    # rebinds against the fresh document instead of a stale bind-once flag leaving
    # drag-drop dead. WebView2 exposes dropped-file paths ONLY to handlers registered
    # through pywebview's DOM API; window.addEventListener('drop') in the SPA gets File
    # objects with NO path, which is why the host binds them here.
    bound_doc = {"id": None}

    def _bind_native_drop() -> None:
        try:
            doc = window.dom.document
        except Exception:  # noqa: BLE001 - no DOM API on this backend; picker still works
            return
        if id(doc) == bound_doc["id"]:
            return  # already bound to THIS document (a route change, not a reload)
        if bind_native_drop(window, _on_native_drop):
            bound_doc["id"] = id(doc)

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
