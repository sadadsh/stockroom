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
import logging
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from stockroom.capture.classify import classify_asset
from stockroom.capture.requirements import Requirement
from stockroom.host.overlay import build_overlay_js
from stockroom.host.vendor_drivers.drivers import build_driver_js

_log = logging.getLogger("stockroom.host.cad")

_CAPTURE_LOG_INSTALLED = {"done": False}


def _install_capture_logfile() -> None:
    """Route the guided-capture logger to a file in the config dir (capture.log) at INFO, so a
    real capture leaves a durable trail of every file that lands, its classification, the Altium
    paths pulled from it, and each forward. The windowed app otherwise logs to a console that is
    not captured, so a field issue ("the Altium files aren't recognized") had no evidence to read.
    Best-effort and installed once; a read-only config dir simply skips it."""
    if _CAPTURE_LOG_INSTALLED["done"]:
        return
    _CAPTURE_LOG_INSTALLED["done"] = True
    try:
        from logging.handlers import RotatingFileHandler

        from stockroom.store.machine_config import config_dir

        path = config_dir() / "capture.log"
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _log.addHandler(handler)
        _log.setLevel(logging.INFO)
    except Exception:  # noqa: BLE001 - logging is a diagnostic aid, never a launch blocker
        pass

_ACTIVE_WINDOW = None
_FETCH_WINDOW = None
_CAD_WINDOW = None
_CAD_DOWNLOADS_WATCH = None
# The one live guided-capture session + its tier-2 poll thread. Starting a new capture
# stops the prior (B4): a stale poll thread must never forward a late file onto a new part.
_CAD_SESSION = None
_CAD_POLL_THREAD = None
_CAD_CAPTURE_LOCK = threading.Lock()

# Loose Altium library suffixes that get pulled out of a captured zip to attach-ready paths.
_ALTIUM_SUFFIXES = frozenset({".schlib", ".pcblib", ".intlib"})
_ALTIUM_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


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
# Each captured file is classified and forwarded to the SPA via
# window.__STOCKROOM_CAD_DOWNLOAD__(payload) - the SAME convergence point regardless of which
# tier fired, so the frontend never has to know which one won. The payload carries the live
# session token, the requirements the file satisfies, and any loose Altium paths pulled from
# a captured zip; the CaptureSession's per-requirement record() dedups a redundant re-fire
# and decides when the capture is complete. Tier 3 is the existing manual pick_ingest_files()
# picker, unchanged.


def cad_window():
    return _CAD_WINDOW


def cad_downloads_watch():
    return _CAD_DOWNLOADS_WATCH


def cad_forward_js(payload: dict) -> str:
    """The renderer call that hands a CaptureForward payload to the SPA, mirroring
    drop_forward_js. Guarded so a renderer that has not registered the hook is a no-op, and
    JSON-encoded so a quote/backslash in a path cannot break out of the script. `payload` is
    the object the frontend's useGuidedCapture reads: {path?, token?, requirements?,
    altiumPaths?, signal?}."""
    encoded = json.dumps(payload)
    return (
        "window.__STOCKROOM_CAD_DOWNLOAD__ && "
        f"window.__STOCKROOM_CAD_DOWNLOAD__({encoded});"
    )


def cad_overlay_received_js(requirements) -> str:
    """The host to page push that ticks the HUD checklist: one
    window.__STOCKROOM_OVERLAY__.received({requirement}) call per newly-satisfied requirement,
    guarded so a remote page without the overlay bridge is a silent no-op, and JSON-encoded so a
    requirement value can never break out of the script. Requirement enums are emitted as their
    wire .value strings (the same contract as build_capture_payload). One-way host to page: the
    CAD window has no js_api, so this only mutates the overlay DOM."""
    calls = "".join(
        "window.__STOCKROOM_OVERLAY__.received("
        f"{json.dumps({'requirement': r.value if isinstance(r, Requirement) else str(r)})});"
        for r in requirements
    )
    return f"window.__STOCKROOM_OVERLAY__ && (function(){{try{{{calls}}}catch(e){{}}}})();"


def cad_download_event_js(state: str, fmt: str | None = None) -> str:
    """Push a REAL download-lifecycle event to the in-page reactor so it reacts to a file actually
    landing, not a timer or a vendor UI modal. `state` is "completed" (a captured file for `fmt`,
    "kicad"/"altium", finished + was classified) - relayed from _forward_cad_capture, the point where
    BOTH capture tiers converge, so the reactor advances no matter which tier caught the file and the
    download's own critical-path handlers stay pristine. The reactor advances to the next format only
    on a real "completed" for the format it is awaiting, so there is no preemption and no phantom-modal
    wait. Guarded, JSON-encoded, one-way (the cad window has no js_api)."""
    payload: dict = {"state": state}
    if fmt:
        payload["format"] = fmt
    return "window.__SR_DL__ && window.__SR_DL__(" + json.dumps(payload) + ");"


def build_capture_payload(path=None, token=None, requirements=None, altium_paths=None) -> dict:
    """The JSON-safe CaptureForward dict the host forwards to the SPA. Only non-empty
    fields are included so the frontend's `p.altiumPaths ?? [p.path]` fallback stays
    correct (an empty altiumPaths would defeat it). Requirement enum members are emitted as
    their wire `.value` strings (the shared contract with the TypeScript union)."""
    payload: dict = {}
    if path:
        payload["path"] = str(path)
    if token:
        payload["token"] = str(token)
    if requirements:
        payload["requirements"] = [
            r.value if isinstance(r, Requirement) else str(r) for r in requirements
        ]
    if altium_paths:
        payload["altiumPaths"] = [str(p) for p in altium_paths]
    return payload


def _extract_altium_members(zip_path, out_dir) -> list[str]:
    """Pull every loose Altium library member (.SchLib/.PcbLib/.IntLib) out of a captured
    zip into out_dir, returning their paths, so the SPA can post them straight to the Altium
    attach route (which reads loose files off disk). Each member is flattened to its
    basename inside out_dir, which also neutralizes any zip-slip path in the archive. A
    non-zip / unreadable archive yields [] (never raises)."""
    out = Path(out_dir)
    extracted: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if Path(n).suffix.lower() in _ALTIUM_SUFFIXES]
            if members:
                out.mkdir(parents=True, exist_ok=True)
            for name in members:
                dest = out / Path(name).name
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(str(dest))
            # one level of nesting: vendors wrap the Altium set in an inner zip inside
            # the bundle; its loose members extract the same way (flattened basenames)
            for name in zf.namelist():
                if Path(name).suffix.lower() != ".zip":
                    continue
                try:
                    import io as _io

                    with zf.open(name) as inner_fh:
                        with zipfile.ZipFile(_io.BytesIO(inner_fh.read())) as inner:
                            inner_members = [
                                n for n in inner.namelist()
                                if Path(n).suffix.lower() in _ALTIUM_SUFFIXES
                            ]
                            if inner_members:
                                out.mkdir(parents=True, exist_ok=True)
                            for iname in inner_members:
                                dest = out / Path(iname).name
                                with inner.open(iname) as src, open(dest, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                extracted.append(str(dest))
                except (zipfile.BadZipFile, OSError, KeyError):
                    continue
    except (zipfile.BadZipFile, OSError):
        return []
    return extracted


def _altium_paths_from_capture(path, classified, reqs, extract_dir) -> list[str]:
    """The loose Altium library paths to attach for this capture, or [] when it carries no
    Altium content the session still needs. A captured zip is unpacked into extract_dir; a
    loose Altium file (.SchLib/.PcbLib/.IntLib) is handed over by its own path (the backend
    attach reads and normalizes it directly, extracting a single .IntLib itself)."""
    if not any(r in _ALTIUM_REQS for r in reqs):
        return []
    p = Path(path)
    if p.suffix.lower() == ".zip":
        return _extract_altium_members(p, extract_dir) if extract_dir is not None else []
    return [str(p)]


def _emit_to_spa(payload: dict) -> None:
    """Forward a CaptureForward payload to the SPA on the MAIN window - never on the remote
    cad window, which never loads the SPA and so never has the forwarding hook registered."""
    spa = active_window()
    if spa is not None:
        spa.evaluate_js(cad_forward_js(payload))


def _emit_to_cad_window(js: str) -> None:
    """Push a host to page script (a received tick or the Complete flash) into the REMOTE cad
    window ONLY - never the SPA. Reads the module global _CAD_WINDOW and best-effort evaluate_js on
    it; a None window (never opened / mid-close) or a destroyed handle is a silent no-op, so a HUD
    update from the poll thread can never crash the capture. One-way: the cad window has no js_api."""
    win = _CAD_WINDOW
    if win is None:
        return
    try:
        win.evaluate_js(js)
    except Exception:  # noqa: BLE001 - a window mid-close must never crash the poll thread
        pass


def _preserve_unrecognized(path) -> None:
    """Copy a captured file whose Altium content could not be pulled into a durable
    capture-debug dir under the config dir, so a field report ("the Altium files aren't
    recognized / are corrupted") can be diagnosed against the ACTUAL bytes even after the
    session temp dir is cleaned by the next capture. Best-effort; never raises."""
    try:
        from stockroom.store.machine_config import config_dir

        dbg = config_dir() / "capture-debug"
        dbg.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(dbg, os.path.basename(str(path)) or "capture.bin")
        shutil.copyfile(path, dest)
        _log.warning("capture: preserved the unrecognized file at %s", dest)
    except Exception:  # noqa: BLE001 - a diagnostic aid, never a capture blocker
        pass


def _forward_cad_capture(path, session=None, *, extract_dir=None) -> None:
    """Classify a captured file, record the requirements it satisfies into `session`, and
    forward the rich CaptureForward payload (path + live token + classified requirements +
    any loose Altium paths pulled from a zip) to the SPA.

    The session's per-requirement record() is the dedup gate: tier 1 (a WebView2 COM
    callback thread) and tier 2 (the poll thread) both call this, and a file that satisfies
    nothing new (a redundant re-fire, a wrong-format download) records [] and forwards
    nothing. Held under _CAD_CAPTURE_LOCK so only one thread ever extracts+forwards a given
    file; the evaluate_js itself runs outside the lock."""
    with _CAD_CAPTURE_LOCK:
        classified = classify_asset(Path(path))
        _log.info(
            "capture: file=%s classified=%s",
            os.path.basename(str(path)),
            sorted(r.value for r in classified.requirements),
        )
        # An altium requirement may only be RECORDED when backed by real attachable
        # paths. A capture whose altium content cannot be pulled out (a zip with no
        # extract_dir, an extraction failure) must leave the need OPEN - recording it
        # unbacked completed the session and closed the window while the SPA had
        # nothing to attach (live 2026-07-24: "got all the files", record incomplete).
        wanted = classified.requirements
        altium_wanted = [r for r in wanted if r in _ALTIUM_REQS]
        backed_altium: list[str] = []
        if altium_wanted:
            backed_altium = _altium_paths_from_capture(path, classified, altium_wanted, extract_dir)
            _log.info(
                "capture: altium wanted=%s backed=%s extract_dir=%s",
                sorted(r.value for r in altium_wanted),
                [os.path.basename(p) for p in backed_altium],
                str(extract_dir),
            )
            if not backed_altium:
                _log.warning(
                    "capture: altium content could NOT be pulled from %s - need stays open",
                    os.path.basename(str(path)),
                )
                _preserve_unrecognized(path)
                wanted = frozenset(r for r in wanted if r not in _ALTIUM_REQS)
        if session is not None:
            # reqs may be EMPTY (a duplicate re-fire, or a wrong-format download): the SPA forward
            # and HUD tick are gated on it below, but the completed relay still fires - the reactor
            # must hear about every file that landed, or it waits out a watchdog on a done download.
            reqs = session.record(wanted, path)
            token = session.token
        else:
            reqs = sorted(wanted, key=lambda r: r.value)
            token = None
        # hand the altium paths over only when this forward actually carries altium reqs
        # (a dedup that dropped them must not re-send the files)
        altium_paths = backed_altium if any(r in _ALTIUM_REQS for r in reqs) else []
        payload = build_capture_payload(path, token, reqs, altium_paths)
    _log.info(
        "capture: forwarding reqs=%s altiumPaths=%s",
        sorted(payload.get("requirements", [])),
        [os.path.basename(p) for p in payload.get("altiumPaths", [])],
    )
    if payload.get("requirements"):
        _emit_to_spa(payload)
    # Tick the HUD checklist live: push the newly-satisfied requirements to the cad window host
    # to page (only for a real capture session, and only when this file satisfied something new -
    # the same non-empty gate that prevents a redundant SPA re-forward). Outside the lock, like the
    # SPA emit.
    if session is not None and reqs:
        _emit_to_cad_window(cad_overlay_received_js(reqs))
    # Relay a "completed" download event for EVERY captured file - including one that satisfied
    # nothing new (a duplicate) or the WRONG format outright (live 2026-07-23: a sticky prior
    # selection made UL serve its Altium+STEP bundle against a KiCad request). The format names
    # what the FILE actually contains (classified), not what the session needed, so the reactor
    # can tell "my format landed" from "something else landed" and react at once (wrongfile ->
    # reselect) instead of waiting out its watchdog on a download that already finished.
    if session is not None:
        _classified_values = [
            r.value if isinstance(r, Requirement) else str(r) for r in classified.requirements
        ]
        for fmt in _capture_formats(_classified_values) or ["unknown"]:
            _emit_to_cad_window(cad_download_event_js("completed", fmt))


def cad_overlay_complete_js() -> str:
    """The host to page push that reveals the HUD Complete flash on session completion, guarded so a
    remote page without the overlay bridge is a silent no-op. One-way: the cad window has no js_api."""
    return "window.__STOCKROOM_OVERLAY__ && window.__STOCKROOM_OVERLAY__.complete();"


def _forward_done_signal(session) -> None:
    """Forward a distinct {signal:'done'} to the SPA on completion (DONE-01), mirroring
    _forward_timeout_signal: the SPA lands in a clean terminal done state the instant the browser
    finishes, token-scoped so a stale done from a replaced capture cannot mark a new part done."""
    _emit_to_spa({"signal": "done", "token": session.token})


def _finish_and_close(session, *, sleep=time.sleep, close_delay: float = 1.0) -> None:
    """The ordered finish-and-close on session completion (DONE-01): flash Complete on the HUD, tell
    the SPA the capture is done, hold briefly (close_delay, via the injectable sleep) so the flash is
    visible, then close the cad window best-effort (read the _CAD_WINDOW global, guarded destroy).

    Closing from the poll thread is safe: _on_cad_closed guards its poll-thread join with a
    current-thread check, so there is no self-join deadlock. The temp dir is DELIBERATELY left intact
    - the async Altium attach still reads the loose paths pulled into it, and the NEXT capture cleans
    it; double-cleaning here would yank files from an in-flight attach (documented invariant)."""
    _emit_to_cad_window(cad_overlay_complete_js())
    _forward_done_signal(session)
    if close_delay:
        sleep(close_delay)
    win = _CAD_WINDOW
    if win is not None:
        try:
            win.destroy()
        except Exception:  # noqa: BLE001 - the window may already be gone; closing is best-effort
            pass


def _forward_timeout_signal(session) -> None:
    """Forward an honest {signal:'timeout'} to the SPA (fixes B1 at the host layer): the
    guided window never hangs forever - if the deadline elapses with unmet needs the poll
    loop tells the SPA to stop waiting instead of returning silently."""
    _emit_to_spa({"signal": "timeout", "token": session.token})


def _session_complete(session) -> bool:
    """Read the session's completeness under the capture lock. is_complete() iterates
    session.received (`set(self.received)`), and the tier-1 WebView2 COM thread mutates that
    dict via record() under the same lock, so an unguarded read from the tier-2 poll thread
    could iterate the dict mid-mutation ('dictionary changed size during iteration'). Reading
    under the lock makes the two mutually exclusive."""
    with _CAD_CAPTURE_LOCK:
        return session.is_complete()


def _poll_downloads_watch(
    watch,
    session,
    *,
    extract_dir=None,
    interval: float = 1.5,
    timeout: float = 300.0,
    close_delay: float = 1.0,
    sleep=time.sleep,
    now=time.time,
) -> None:
    """TIER 2 background loop: poll `watch` (download_capture.DownloadsWatch) for captured
    files, forwarding each into `session` until the session is complete, it is stopped
    (replaced/closed), or `timeout` elapses. Unlike the prior single-file flow it keeps
    polling, so a guided capture can collect BOTH its KiCad and its Altium assets as they
    arrive one at a time. On a genuine timeout (deadline reached with unmet needs) it
    forwards a timeout signal (fixes B1 at the host layer) rather than returning silently;
    on a stop it returns silently - the stopper owns teardown, and a timeout signal must
    never land on the part that replaced this one. Runs on a daemon thread started by
    open_cad_download. Zero pywebview dependency (importable and callable on Linux); only
    ever finds a real file on Windows watching a real Downloads folder."""
    deadline = now() + timeout
    while not session.stop_flag["stop"] and now() < deadline:
        if _session_complete(session):
            # all needs met: flash Complete on the HUD, tell the SPA it is done, and auto-close the
            # cad window (DONE-01). The temp dir is left for the async Altium attach (cleaned on the
            # next capture); no double-clean here.
            _finish_and_close(session, sleep=sleep, close_delay=close_delay)
            return
        found = watch.poll()
        if found is not None:
            _forward_cad_capture(found, session, extract_dir=extract_dir)
            continue  # re-check completion at once; a burst of files should not each sleep
        sleep(interval)
    if session.stop_flag["stop"]:
        return
    if not _session_complete(session):
        _forward_timeout_signal(session)


# -- The guided-capture wall (Cloudflare verification / vendor login) is solved BY THE USER
# (owner 2026-07-24): an OS-level auto-click of the Turnstile only tripped Cloudflare's bot
# detection - it verified, then reset, over and over. So the driver only SENSES the wall
# (senseWall) and hands off through the overlay "Your Turn", and the host waits for the user
# to clear it (the persistent profile then keeps that clearance for later captures). The one
# thing the host DOES auto-accept is Edge's "allow multiple automatic downloads?" bar, so the
# second (Altium) file is never gated behind a prompt (owner's must-keep) - see below.


def _should_auto_allow_permission(kind: str) -> bool:
    """Whether a WebView2 permission request in the CAD window is auto-granted. ONLY the
    download-related kinds (Edge's "allow multiple automatic downloads?" bar, which blocked
    the second file of the both-format capture, live 2026-07-24) - camera/mic/location and
    everything else keep their normal prompts."""
    return "download" in (kind or "").lower()


def _grant_download_permission(args, *, allow_state) -> bool:
    """Apply the auto-allow decision to a WebView2 PermissionRequestedEventArgs: for a
    download-related kind, set State=Allow AND Handled=True, and return True. Handled=True is
    the load-bearing part - in WebView2, leaving Handled false still shows the default
    permission dialog (State is only the preselection), so the "allow multiple automatic
    downloads?" bar kept appearing on the SECOND download and the Altium set never followed
    the KiCad one (live 2026-07-24). Kept pure (no pywebview types) so it unit-tests with a
    fake args; the COM handler is a thin wrapper. Non-download kinds are left untouched, so
    camera/mic/location keep their normal prompt."""
    try:
        kind = str(args.PermissionKind)
    except Exception:  # noqa: BLE001 - an unreadable kind is simply not granted
        return False
    if not _should_auto_allow_permission(kind):
        return False
    args.State = allow_state
    try:
        args.Handled = True
    except Exception:  # noqa: BLE001 - an older args without Handled still gets State=Allow
        pass
    return True


def _origin_of(url: str) -> str:
    """The scheme://host[:port] origin of a URL, or "" when it has none. WebView2's
    SetPermissionStateAsync keys the automatic-downloads content setting on the top-level
    page origin, so this is what to pre-authorize."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _arm_download_permission_on_ui(core, state: dict) -> None:
    """Make the second (Altium) download never stall behind Edge's "allow multiple automatic
    downloads?" bar (the owner's must-keep). Runs once per session (the `state["armed"]` flag)
    on the UI thread - the download-starting callback fires there with the CoreWebView2 as
    `sender`, on the FIRST (KiCad) download, before the site initiates the second.

    PRIMARY mechanism: PRE-AUTHORIZE the page origin via CoreWebView2Profile.SetPermissionStateAsync
    (MultipleAutomaticDownloads -> Allow), so the bar never appears and it PERSISTS in the profile
    for later captures. This is required because WebView2 150.x does NOT raise PermissionRequested
    for that bar (isolated real-Windows test 2026-07-24: the 2nd download was blocked and no
    PermissionRequested fired). BACKUP: also subscribe PermissionRequested for any runtime that does
    raise it (harmless where it doesn't). MUST be on the UI thread - the prior daemon-thread install
    threw "CoreWebView2 can only be accessed from the UI thread" (E_NOINTERFACE) and never attached,
    so only the KiCad zip was ever captured (live 2026-07-24)."""
    if state.get("armed"):
        return
    state["armed"] = True

    # PRIMARY: pre-authorize the origin so the bar never shows (persists in the profile).
    try:
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2PermissionKind,
            CoreWebView2PermissionState,
        )

        origin = _origin_of(str(getattr(core, "Source", "") or ""))
        profile = getattr(core, "Profile", None)
        if origin and profile is not None:
            profile.SetPermissionStateAsync(
                CoreWebView2PermissionKind.MultipleAutomaticDownloads,
                origin,
                CoreWebView2PermissionState.Allow,
            )
            _log.info("cad multi-download pre-authorized for %s", origin)
        else:
            _log.warning("cad multi-download: no origin/profile to pre-authorize; the bar may prompt")
    except Exception:  # noqa: BLE001 - older runtime without the API degrades to the backup below
        _log.warning("cad multi-download pre-authorize unavailable; relying on the permission event")

    # BACKUP: the permission event, for any runtime that DOES raise it for this bar.
    def _on_permission_requested(sender, args) -> None:
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

            _grant_download_permission(args, allow_state=CoreWebView2PermissionState.Allow)
        except Exception:  # noqa: BLE001 - a shape mismatch degrades to the manual prompt
            pass

    try:
        core.PermissionRequested += _on_permission_requested
    except Exception:  # noqa: BLE001 - could not subscribe; the pre-authorize above covers it
        pass


def _install_cad_download_intercept(
    window, target_dir: Path, on_captured, *, retries: int = 10, delay: float = 0.05, sleep=time.sleep
) -> bool:
    """TIER 1 (best-effort, Windows only): reach past pywebview's public API - which
    exposes NO download hook, only the ALLOW_DOWNLOADS setting that triggers pywebview's
    own native Save-As dialog - into its vendored WebView2 backend, and redirect THIS ONE
    window's next download save-path into `target_dir`, notifying `on_captured(path)` once
    WebView2 reports the download Completed. `on_captured` is idempotent (the CaptureSession
    dedups by requirement), so a repeated Completed callback forwards nothing extra.

    Readiness (B3): the window's CoreWebView2 initializes asynchronously, so its EdgeChrome
    browser instance may not be registered the instant create_window() returns. The grab is
    retried a few times with a short backoff before conceding to tier 2, and every failure
    is logged instead of silently swallowed.

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
        _log.warning("cad tier-1 unavailable: pywebview WinForms backend not importable; tier 2 covers it")
        return False

    edge = None
    for attempt in range(max(1, retries)):
        browser_form = BrowserView.instances.get(getattr(window, "uid", None))
        edge = getattr(browser_form, "browser", None)
        if edge is not None:
            break
        if attempt < retries - 1:
            sleep(delay)  # CoreWebView2 inits async; give it a beat before conceding to tier 2
    if edge is None:
        _log.warning("cad tier-1: EdgeChrome browser not ready after %d tries; tier 2 covers it", retries)
        return False

    perm_state: dict = {}

    def _on_download_starting(sender, args) -> None:
        # Arm the multi-download permission auto-allow HERE (not on a daemon thread): this callback
        # is on the UI thread with the CoreWebView2 as `sender`, and fires on the first download,
        # before the site initiates the second - so the "allow multiple downloads?" bar for the
        # Altium download is auto-accepted (owner's must-keep). Guarded to subscribe once.
        _arm_download_permission_on_ui(sender, perm_state)
        # A download IS starting - relay the real 'started' event to the reactor from a worker
        # thread (this handler runs on the COM thread and must stay pristine). Fires on both
        # branches below: even when completion can't be observed, the start happened.
        threading.Thread(target=_emit_download_started, daemon=True).start()
        try:
            operation = args.DownloadOperation
        except Exception:  # noqa: BLE001 - can't observe completion; let it save to the
            return  # default location (OS Downloads) where tier 2 is watching

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            name = os.path.basename(str(args.ResultFilePath)) or "cad-download.zip"
            dest = _unique_dest(target_dir, name)
            _log.info("cad tier-1: download starting name=%s -> %s", name, dest.name)

            fired = {"done": False}

            def _on_state_changed(op_sender, op_args) -> None:
                # KEEP THIS HANDLER PRISTINE: it runs on WebView2's download COM thread, in the
                # critical path of the download itself. Calling evaluate_js here stalled the download
                # mid-stream (live-observed 2026-07-23), and running the forward pipeline (classify +
                # extract + blocking evaluate_js pushes) synchronously here hung the thread mid-relay
                # (live-observed 2026-07-23, second finding: the HUD ticked, then the completed relay
                # never reached the page). So this reads the state and DISPATCHES the completed file
                # to a worker thread - nothing else - and fires exactly once per download operation
                # (a repeated Completed re-fire would relay a duplicate event the reactor could
                # misread as a wrong-format delivery for the NEXT format).
                try:
                    from Microsoft.Web.WebView2.Core import CoreWebView2DownloadState

                    done = operation.State == CoreWebView2DownloadState.Completed
                except Exception:  # noqa: BLE001 - best-effort: treat an unreadable state as done
                    done = True
                if done and not fired["done"]:
                    fired["done"] = True
                    _dispatch_captured(on_captured, dest)

            operation.StateChanged += _on_state_changed
            args.ResultFilePath = str(dest)
            args.Handled = True  # skip pywebview's native Save-As dialog for this window
        except Exception:  # noqa: BLE001 - best-effort; fall through to the default save flow
            _log.warning("cad tier-1: redirect failed; falling through to the OS Downloads folder")
            return

    try:
        edge.on_download_starting = _on_download_starting
    except Exception:  # noqa: BLE001 - could not patch this instance; tier 2 still covers it
        _log.warning("cad tier-1: could not patch this window's download handler; tier 2 covers it")
        return False
    return True


# Per-vendor login DOM selector sets (username-or-email + password). The download happens ON
# DigiKey (owner correction 2026-07-22), so the DigiKey ACCOUNT web login is the PRIMARY autofill -
# signing into DigiKey prepares login for everything - with Ultra Librarian / SnapEDA / SamacSys
# KEPT as backups in case one is prompted in-page. Selectors are OWNER-VALIDATE first-guesses
# against the live login DOMs (which change); the generic set is the unknown-vendor fallback.
_LOGIN_SELECTORS: dict[str, dict[str, str]] = {
    "digikey": {
        "user": "input#username,input[name='username'],input[type='email'],input[name*='user' i]",
        "pass": "input#password,input[type='password'],input[name='password']",
    },
    "ultralibrarian": {
        "user": "input[name='Email'],input[type='email'],input[name*='user' i]",
        "pass": "input[name='Password'],input[type='password']",
    },
    "snapeda": {
        "user": "input[name='email'],input[type='email'],input[name*='user' i]",
        "pass": "input[name='password'],input[type='password']",
    },
    "samacsys": {
        "user": "input[name='email'],input[type='email'],input[name*='user' i]",
        "pass": "input[name='password'],input[type='password']",
    },
}
_GENERIC_LOGIN_SELECTORS = {
    "user": "input[type='email'],input[name='username'],input[name='email'],input[name*='user']",
    "pass": "input[type='password']",
}


def build_login_autofill_js(vendor: str, username: str, password: str) -> str:
    """A best-effort login auto-fill for the vendor window, from the per-machine saved creds
    (Settings). Pure string builder. Empty when there is nothing to fill (so nothing is
    injected - the LGN-02 "log in once" path). Creds are JSON-encoded (never string-concatenated)
    and every field fill is guarded, so a page without a matching field is a silent no-op. Injected
    ONLY into the remote cad window on its `loaded` event - never the SPA. `vendor` selects the
    per-vendor login DOM (digikey account primary / ultralibrarian / snapeda / samacsys), falling
    back to a generic email/username + password fill for an unknown vendor."""
    if not (username or password):
        return ""
    sels = _LOGIN_SELECTORS.get((vendor or "").strip().lower(), _GENERIC_LOGIN_SELECTORS)
    j = json.dumps
    return (
        "(function(){try{"
        f"var u={j(username)},p={j(password)};"
        # DigiKey's login (PingFederate) and the vendor forms are React-controlled: assigning
        # el.value directly leaves React's internal value tracker empty, so a submit validates
        # an EMPTY field ("Please fill out this field") though the box shows the text (live
        # 2026-07-24). Go through the prototype's NATIVE value setter so the input event React
        # listens for carries a value it accepts.
        "function nset(el,val){try{var proto=(el instanceof HTMLTextAreaElement)"
        "?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
        "var d=Object.getOwnPropertyDescriptor(proto,'value');"
        "if(d&&d.set){d.set.call(el,val);}else{el.value=val;}}catch(e){el.value=val;}}"
        # Only fill a field that is VISIBLE and not already carrying a different value the user
        # is typing (never clobber a manual edit); a field already holding the target value is
        # a no-op success.
        "function fill(sel,val){if(!val)return false;var el=document.querySelector(sel);"
        "if(!el||el.offsetParent===null)return false;"
        "var cur=(el.value||'');if(cur===val)return true;if(cur.trim())return false;"
        "nset(el,val);el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));return true;}"
        f"var US={j(sels['user'])},PS={j(sels['pass'])};"
        # AUTO-SUBMIT (owner 2026-07-24: "make everything automatic"). DigiKey's login is TWO
        # steps (email -> Next -> password -> Sign In). Fill the visible field, then click its
        # submit button ONCE per step (tracked in `sent`, reset each fresh page load), so a full
        # capture logs in with the saved creds and no clicks. Bounded: at most one click per step
        # per page, only after the field truly holds the value, and only a submit/Next/Sign-in
        # style button (never Register/Cancel) - so a wrong cred fails once and never loops (the
        # reactor's wall detection then hands off). Also clicks a "Login" prompt (e.g. the guest
        # download-limit modal) to REACH the login form.
        "var sent={u:false,p:false,go:false};"
        "function submit(){try{"
        "var b=document.querySelector('form button[type=submit]:not([disabled]),form input[type=submit]:not([disabled])');"
        "if(!b){var cs=[].slice.call(document.querySelectorAll('button,input[type=submit],a[role=button]'));"
        "b=cs.filter(function(x){return x.offsetParent!==null&&!x.disabled&&"
        "/^(sign ?in|log ?in|login|next|continue|submit)$/i.test((x.textContent||x.value||'').trim());})[0];}"
        "if(b&&b.offsetParent!==null){b.click();return true;}return false;}catch(e){return false;}}"
        "function tick(){"
        "var pw=document.querySelector(PS);var pwv=pw&&pw.offsetParent!==null;"
        "fill(US,u);if(pwv)fill(PS,p);"
        "var uEl=document.querySelector(US);"
        "if(pwv){if(!sent.p&&pw.value===p){sent.p=true;setTimeout(submit,450);}}"
        "else if(uEl&&uEl.offsetParent!==null){if(!sent.u&&uEl.value===u){sent.u=true;setTimeout(submit,450);}}"
        # a login/guest-limit prompt with no field to fill: click its Login button ONCE to reach
        # the sign-in form (then the fills+submits above take over on the login page)
        "else if(!sent.go){var g=[].slice.call(document.querySelectorAll('button,a')).filter(function(x){"
        "return x.offsetParent!==null&&/^(sign ?in|log ?in|login)$/i.test((x.textContent||'').trim());})[0];"
        "if(g){sent.go=true;setTimeout(function(){try{g.click();}catch(e){}},450);}}}"
        "var n=0;var iv=setInterval(function(){n++;tick();if(n>=40)clearInterval(iv);},600);tick();"
        "}catch(e){}})();"
    )


def _formats_for_needs(needs) -> list[str]:
    """The vendor download formats (`kicad`/`altium`) a set of Requirement values implies,
    KiCad before Altium."""
    values = {str(n) for n in (needs or [])}
    formats: list[str] = []
    if any(v.startswith("kicad_") for v in values):
        formats.append("kicad")
    if any(v.startswith("altium_") for v in values):
        formats.append("altium")
    return formats


def _capture_formats(requirement_values) -> list[str]:
    """The formats a CAPTURED file actually DELIVERS, for the reactor's completed relay: a format
    counts only when its core symbol+footprint pair is present. This is deliberately stricter than
    _formats_for_needs (which maps NEEDS, where any missing kicad_* must re-drive kicad): a stray
    STEP classifies as kicad_model alone, and naming that a "kicad" delivery would falsely advance
    the reactor past a format it never received (live 2026-07-23: UL's Altium+STEP bundle against a
    KiCad request)."""
    values = {str(n) for n in (requirement_values or [])}
    formats: list[str] = []
    if {"kicad_symbol", "kicad_footprint"} <= values:
        formats.append("kicad")
    if {"altium_symbol", "altium_footprint"} <= values:
        formats.append("altium")
    return formats


def _unique_dest(target_dir, name: str) -> Path:
    """A collision-free save path inside target_dir. The vendor names EVERY export the same
    (<MPN>.zip), so a second format's download would OVERWRITE the first zip while its async SPA
    attach may still be reading that path (live 2026-07-23: the Altium zip replaced the
    just-captured KiCad zip on disk seconds after the KiCad forward). Appends -2, -3, ... before
    the suffix until the name is free."""
    base = Path(name).stem or "cad-download"
    suffix = Path(name).suffix or (".zip" if not name else "")
    dest = Path(target_dir) / f"{base}{suffix}"
    n = 2
    while dest.exists():
        dest = Path(target_dir) / f"{base}-{n}{suffix}"
        n += 1
    return dest


def _emit_download_started() -> None:
    """Relay the browser's REAL download-started event to the in-page reactor. Owner heuristic
    (2026-07-23): a successful run's download STARTS within ~5s of the click, so the reactor
    fails 'nostart' fast - on to the next source - when nothing begins. Called on a worker
    thread, never on the download's COM-critical path."""
    _emit_to_cad_window(cad_download_event_js("started"))


def _dispatch_captured(on_captured, dest) -> None:
    """Hand a completed download to `on_captured` on a WORKER thread and return immediately.
    Tier 1's StateChanged fires on WebView2's download COM thread; running the forward pipeline
    (classify + extract + blocking evaluate_js pushes) on that thread hung it mid-relay
    (live-observed 2026-07-23: the HUD ticked, then the completed relay never reached the page),
    so the COM callback must never wait on the forward."""
    threading.Thread(target=on_captured, args=(dest,), daemon=True).start()


def _vendor_from_url(url: str) -> tuple[str, str]:
    """(driver_key, display_label) for a resolved CAD-source URL. The key drives which vendor
    driver runs (empty = no automation, guidance only); the label is what the overlay shows."""
    u = (url or "").lower()
    # DigiKey is checked FIRST: the guided capture happens ON DigiKey, and its CAD models page URL
    # carries a `?tab=ultralibrarian` (or traceparts/cadenas/snapmagic) query, so a naive provider
    # substring match would mis-route a DigiKey page to a legacy provider driver whose selectors never
    # fire (live-observed 2026-07-23: the models page injected the Ultra Librarian driver, 0 captures).
    # The provider drivers below apply only to a window opened DIRECTLY on a provider site.
    if "digikey" in u:
        return ("digikey", "DigiKey")
    if "ultralibrarian" in u:
        return ("ultralibrarian", "Ultra Librarian")
    if "snapeda" in u or "snapmagic" in u:
        return ("snapeda", "SnapEDA")
    if "componentsearchengine" in u or "samacsys" in u:
        return ("samacsys", "SamacSys")
    return ("", "the vendor")


def cad_loaded_scripts(
    needs, vendor_key: str, vendor_label: str, formats, creds, part_name: str = ""
) -> list[str]:
    """The scripts to inject into the cad window on each `loaded`, in order: the overlay (so
    the panel + `window.__STOCKROOM_OVERLAY__` bridge exist first), then a best-effort login
    auto-fill (omitted when there are no creds), then the vendor driver (which reports into the
    overlay). `part_name` is shown as the HUD header focal point when non-empty."""
    scripts = [build_overlay_js(list(needs), vendor_label, part_name)]
    autofill = build_login_autofill_js(
        vendor_key, (creds or {}).get("username", ""), (creds or {}).get("password", "")
    )
    if autofill:
        scripts.append(autofill)
    scripts.append(build_driver_js(vendor_key, list(formats)))
    return scripts


def _load_vendor_creds(vendor_key: str) -> dict:
    """The saved login for a vendor from the per-machine config, or {} (best-effort - a missing
    or unreadable config never blocks the capture). Handles digikey + ultralibrarian + snapeda +
    samacsys. The digikey ACCOUNT web login (digikey_username/password - NOT the API
    client_id/secret) and samacsys_* fields are read via getattr so they degrade to blank before
    Phase 4 SET-01 adds them (nothing injected -> the LGN-02 "log in once" path); ul/snapeda read
    their existing fields."""
    if vendor_key not in ("digikey", "ultralibrarian", "snapeda", "samacsys"):
        return {}
    try:
        from stockroom.store.machine_config import MachineConfig

        cfg = MachineConfig.load()
    except Exception:  # noqa: BLE001 - no config / unreadable: just skip the auto-fill
        return {}
    if vendor_key == "digikey":
        return {
            "username": getattr(cfg, "digikey_username", ""),
            "password": getattr(cfg, "digikey_password", ""),
        }
    if vendor_key == "ultralibrarian":
        return {"username": cfg.ul_username, "password": cfg.ul_password}
    if vendor_key == "snapeda":
        return {"username": cfg.snapeda_username, "password": cfg.snapeda_password}
    return {
        "username": getattr(cfg, "samacsys_username", ""),
        "password": getattr(cfg, "samacsys_password", ""),
    }


def cad_scripts_for_url(
    url: str, needs_values, part_name: str = "", driver_formats=None
) -> list[str]:
    """The cad scripts (overlay + optional per-vendor login autofill + driver) re-derived from a
    url: vendor/label via `_vendor_from_url`, formats via `_formats_for_needs`, creds via
    `_load_vendor_creds`. So a DigiKey url yields the DigiKey-account autofill (when creds are
    saved), an in-page provider url (snapeda / samacsys / ultralibrarian) yields that provider's
    autofill, and a url with no saved creds yields overlay + driver only. The single DRY path for
    both the initial injection and every re-injection - all host->page evaluate_js, never the token
    or a js_api bridge.

    `driver_formats` overrides which formats the DRIVER attempts while the OVERLAY still shows the
    full `needs_values` checklist. The host drives ONE format per fresh page load (DigiKey's stateful
    export + Download-complete modals cannot be reliably reused for a 2nd format in one session), so it
    passes the single next-unmet format here; None (the default) means all requested formats."""
    vendor_key, vendor_label = _vendor_from_url(url)
    formats = _formats_for_needs(needs_values) if driver_formats is None else list(driver_formats)
    creds = _load_vendor_creds(vendor_key)
    return cad_loaded_scripts(needs_values, vendor_key, vendor_label, formats, creds, part_name)


def _inject_cad_scripts(
    win, fallback_url: str, needs_values, part_name: str = "", driver_formats=None
) -> None:
    """Re-derive the cad scripts from the window's CURRENT url (guarded `get_current_url`, falling
    back to `fallback_url`) and inject them via `evaluate_js` - the light in-site re-injection, so
    after an in-site DigiKey nav or an in-page modal the current url's overlay + autofill + driver
    are re-injected. `driver_formats` scopes the driver to the next-unmet format (one per page load).
    Injection is host->page `evaluate_js` only; never `inject_script`, never the token or a js_api."""
    try:
        current = win.get_current_url()
    except Exception:  # noqa: BLE001 - a backend without get_current_url falls back to the original
        current = None
    url = current or fallback_url
    for script in cad_scripts_for_url(url, needs_values, part_name, driver_formats):
        try:
            win.evaluate_js(script)
        except Exception:  # noqa: BLE001 - injection is best-effort; never crash the app
            _log.warning("cad guided-overlay/driver injection failed on load")


# Candidate pywebview event slots for a popup / new-window / navigation, tried in order. The
# surface is backend + version specific, so the wiring probes for whichever the installed
# pywebview exposes and degrades silently when none is present (owner correction: cross-site is
# DE-SCOPED, so this is a LIGHT backstop, not the architecture).
_CAD_REINJECT_EVENTS = (
    "new_window",
    "new_window_request",
    "window_open",
    "popup",
    "navigated",
    "before_navigate",
)


def _reinject_popup(win, target, needs_values, part_name: str = "") -> None:
    """Inject the cad scripts onto a popped / navigated window (or back onto `win` when the event
    carried no window object), re-derived from that window's current url. Host->page `evaluate_js`
    only - a popup NEVER receives the token or a js_api bridge."""
    tw = target if (target is not None and hasattr(target, "evaluate_js")) else win
    _inject_cad_scripts(tw, "", needs_values, part_name)


def _wire_cad_reinjection(
    win, needs_values, part_name: str = "", *, candidate_events=_CAD_REINJECT_EVENTS
) -> bool:
    """LIGHT defensive backstop: best-effort subscribe to the installed pywebview's popup /
    new-window / navigation event IF it exposes one, re-injecting the cad scripts onto that window
    via `evaluate_js`. Returns True once a slot is subscribed; logs a warning and returns False
    when the backend exposes none - the same silent-degrade discipline as
    `_install_cad_download_intercept` on an older backend. NEVER calls `inject_script` and NEVER
    wires js_api / the token onto the popup."""
    try:
        events = win.events
    except Exception:  # noqa: BLE001 - no events surface; in-site re-injection still covers it
        _log.warning("cad re-injection unavailable: window exposes no events; in-site re-inject covers it")
        return False

    def _on_popup(target=None, *args, **kwargs):
        try:
            _reinject_popup(win, target, needs_values, part_name)
        except Exception:  # noqa: BLE001 - best-effort backstop; never crash the app
            _log.warning("cad popup re-injection failed")

    for name in candidate_events:
        slot = getattr(events, name, None)
        if slot is None:
            continue
        try:
            slot += _on_popup
            return True
        except Exception:  # noqa: BLE001 - this slot did not accept a handler; try the next
            continue
    _log.warning("cad re-injection: no popup/new-window event on this pywebview backend; in-site re-inject covers it")
    return False


def _parse_needs(needs) -> frozenset:
    """The frontend hands the capture's needs as Requirement `.value` strings; map them back
    to the Requirement enum, dropping anything unrecognized (never trust remote input)."""
    out = set()
    for n in needs or []:
        try:
            out.add(Requirement(n))
        except ValueError:
            continue
    return frozenset(out)


def _clean_temp(session) -> None:
    """Remove a finished session's scratch dir. Best-effort - a still-open handle on Windows
    must never crash teardown."""
    temp = getattr(session, "temp_dir", None)
    if temp is not None:
        shutil.rmtree(temp, ignore_errors=True)


def _stop_active_capture() -> None:
    """Stop and tear down the live capture (B4 + B8): flag the session to stop, join its
    tier-2 poll thread so it can no longer forward a late file onto whatever part replaces
    it, then clean its temp dir. Safe to call with nothing active. Called at the top of a
    new open_cad_download and when the cad window closes."""
    global _CAD_SESSION, _CAD_POLL_THREAD
    prior = _CAD_SESSION
    thread = _CAD_POLL_THREAD
    if prior is not None:
        prior.stop()
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)
    if prior is not None:
        _clean_temp(prior)
    _CAD_SESSION = None
    _CAD_POLL_THREAD = None


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

    def open_cad_download(self, url, needs=None, part_name=None) -> str:
        """Open a vendor CAD-download page (Ultra Librarian / SnapEDA, or a DigiKey product
        page) in a SECOND, VISIBLE window dedicated to this one guided capture, and return a
        per-capture session TOKEN the SPA gates every forward on (B4). `needs` is the list of
        Requirement `.value` strings the part still needs (KiCad and/or Altium); it seeds the
        CaptureSession that decides when the capture is complete.

        This window gets NO `loaded` handler at all - not merely relying on should_inject's
        origin guard, there is simply no wiring through which the per-launch token could ever
        reach this remote page - and NO js_api bridge either, so nothing this app exposes is
        reachable from remote content.

        Arms BOTH capture tiers on every call: tier 1 best-effort redirects this window's
        downloads into the session temp dir (_install_cad_download_intercept, Windows only,
        degrades silently); tier 2 arms a widened DownloadsWatch over the OS Downloads folder
        and polls it on a daemon thread, the always-available backstop. Each captured file is
        classified and forwarded into the session with this session's token; the session's
        per-requirement dedup drops a redundant re-fire. The poll loop keeps running so a
        capture can collect BOTH its KiCad and its Altium assets as they land.

        Replaces any prior capture first: stops the prior session + joins its poll thread so a
        stale file can never misattribute onto this new part (B4), cleans the prior temp dir
        (B8), and closes the leftover window rather than piling up extra windows."""
        global _CAD_WINDOW, _CAD_DOWNLOADS_WATCH, _CAD_SESSION, _CAD_POLL_THREAD
        import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

        from stockroom.capture.session import CaptureSession
        from stockroom.host.download_capture import DownloadsWatch, default_downloads_dir

        _stop_active_capture()

        if _CAD_WINDOW is not None:
            try:
                _CAD_WINDOW.destroy()
            except Exception:  # noqa: BLE001 - already closed/invalid; we're replacing it anyway
                pass
            _CAD_WINDOW = None

        needs_set = _parse_needs(needs)
        name = part_name or ""
        session = CaptureSession.start(name, needs_set, now=time.time())
        session.temp_dir = Path(tempfile.mkdtemp(prefix="stockroom-cad-"))
        _CAD_SESSION = session
        _log.info(
            "capture: session start part=%s needs=%s url=%s temp=%s",
            name,
            sorted(r.value for r in needs_set),
            url,
            session.temp_dir.name,
        )

        win = webview.create_window("stockroom-cad", url=url, width=1200, height=900)
        _CAD_WINDOW = win

        # Guide the capture INSIDE the vendor window: on each load, re-derive from the window's
        # CURRENT url and inject the overlay (the checklist + the __STOCKROOM_OVERLAY__ bridge),
        # then a best-effort login auto-fill from the saved creds, then the vendor driver
        # (auto-click, reporting into the overlay). Re-deriving from the current url is the light
        # in-site re-injection (LGN-03): an in-site DigiKey nav or an in-page modal re-injects the
        # right scripts. All best-effort and guarded; injected ONLY on this remote window via
        # evaluate_js, never the SPA, and NEVER with the per-launch token or a js_api bridge.
        needs_values = [r.value for r in needs_set]

        def _remaining_formats():
            """The vendor formats (kicad/altium) still NOT captured, in order. On a FRESH page load
            (initial, the product->models navigation, or a recovery reload) the reactor is injected
            scoped to just these, so an already-captured format is never re-driven. The reactor itself
            sequences them, gating each on the REAL browser download event - the host does not
            orchestrate; it only scopes what to inject and relays the real events."""
            return _formats_for_needs([r.value for r in session.remaining()])

        def _on_cad_loaded() -> None:
            # Re-inject the reactor on each load, scoped to what is STILL needed. The reactor reacts to
            # live page state + the real download events (window.__SR_DL__); the host stays a dumb
            # collector + re-injector. The overlay still shows the FULL checklist (needs_values).
            _inject_cad_scripts(win, url, needs_values, name, driver_formats=_remaining_formats())

        win.events.loaded += _on_cad_loaded
        # Best-effort popup / new-window re-injection when this pywebview backend exposes the
        # event; degrades silently otherwise (cross-site is DE-SCOPED - a LIGHT backstop only).
        _wire_cad_reinjection(win, needs_values, name)

        thread_box: dict = {"t": None}

        def _on_cad_closed() -> None:
            global _CAD_WINDOW, _CAD_SESSION, _CAD_POLL_THREAD
            if _CAD_WINDOW is win:
                _CAD_WINDOW = None
            session.stop()
            t = thread_box["t"]
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=2.0)
            # Deliberately do NOT clean the temp dir here. The SPA attaches the loose Altium
            # paths pulled into it ASYNC after a forward, and a user commonly closes this
            # window the moment the download lands - deleting the dir now would yank those
            # files out from under an in-flight attach. The temp dir is cleaned when the NEXT
            # capture starts (_stop_active_capture), by which point any attach is long done;
            # a last, never-followed capture leaves one small dir the OS temp-reaps.
            if _CAD_SESSION is session:
                _CAD_SESSION = None
                _CAD_POLL_THREAD = None

        win.events.closed += _on_cad_closed

        def _on_captured(captured_path) -> None:
            _forward_cad_capture(captured_path, session, extract_dir=session.temp_dir)

        # tier-1 also arms the multi-download permission auto-allow on the UI thread from its
        # download-starting callback (see _arm_download_permission_on_ui); no separate install.
        tier1 = _install_cad_download_intercept(win, session.temp_dir, _on_captured)

        downloads_dir = default_downloads_dir()
        watch = DownloadsWatch.start(downloads_dir)
        _CAD_DOWNLOADS_WATCH = watch
        _log.info(
            "capture: tiers armed tier1_intercept=%s tier2_watch=%s",
            bool(tier1),
            str(downloads_dir),
        )
        thread = threading.Thread(
            target=_poll_downloads_watch,
            args=(watch, session),
            kwargs={"extract_dir": session.temp_dir},
            daemon=True,
        )
        thread_box["t"] = thread
        _CAD_POLL_THREAD = thread
        thread.start()
        return session.token


def _webview_start_kwargs(start_fn, profile_dir) -> dict:
    """The private_mode/storage_path kwargs that make the guided-capture (vendor) window's
    login persist across parts and app launches (B5). pywebview's storage is set once at
    webview.start(), not per window, so a persistent, non-private profile on the shared
    WebView2 environment is what carries the vendor's login cookies from one capture to the
    next. Included only when this pywebview version accepts them (older versions ignore the
    profile and the login simply will not persist). The main SPA is loopback with a
    per-launch token injected on every load and its service workers unregistered, so a
    persistent profile changes nothing for it."""
    import inspect

    params = inspect.signature(start_fn).parameters
    kwargs: dict = {}
    if "private_mode" in params:
        kwargs["private_mode"] = False
    if "storage_path" in params:
        kwargs["storage_path"] = str(profile_dir)
    return kwargs


def run_window(base_url: str, token: str) -> None:
    """Open the WebView2 window onto the FastAPI-served frontend and block until it
    closes. Injects the base+token on every load (so an SPA reload after self-update
    re-authenticates). The uvicorn server is owned + stopped by the host supervisor
    that called run_window (stockroom.host.run), which shuts it down once this returns."""
    global _ACTIVE_WINDOW
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    from stockroom.store.machine_config import config_dir

    _install_capture_logfile()

    # pywebview blocks ALL downloads by default, which silently kills every export
    # in the app (the BOM CSV, the fab zip, the audit markdown are Blob+anchor
    # downloads). Enable them so WebView2 shows its normal download flow. Module
    # global, so the hidden fetch window inherits it too: acceptable, its vendor
    # pages are user-initiated enrichment fetches and a download needs user action.
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001 - an older pywebview without settings still runs
        pass
    # Dev-only observability: STOCKROOM_CDP_PORT exposes WebView2's remote-debugging port so the
    # REAL app can be driven and verified over CDP in live end-to-end tests (capture -> attach ->
    # library placement). Never set in normal use; a pywebview without the setting ignores it.
    cdp_port = os.environ.get("STOCKROOM_CDP_PORT")
    if cdp_port:
        try:
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(cdp_port)
        except Exception:  # noqa: BLE001 - a bad value/old pywebview must never block launch
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

    _autocap = {"fired": False}

    def _on_loaded():
        # Re-inject on every SPA load (after a self-update reload or route change the
        # renderer must always carry the base + token), but ONLY when the loaded page
        # is the loopback SPA origin (never a remote page), so the token can never leak
        # to remote web content (defense in depth on top of the dedicated fetch window).
        if not _spa_is_current():
            return
        window.evaluate_js(inject_script(base_url, token))
        _bind_native_drop()
        # DEV-ONLY (STOCKROOM_AUTOCAP=<part_id>): trigger the guided capture for a part straight
        # from the host, so a real capture can be exercised WITHOUT the CDP remote-debugging port
        # that makes DigiKey serve a degraded page. Fetches the part's cad-source (url + needs)
        # and calls the js_api open_cad_download - the same path the Get Files button takes. Fires
        # once. No-op unless the env var is set.
        autocap_id = os.environ.get("STOCKROOM_AUTOCAP")
        if autocap_id and not _autocap["fired"]:
            _autocap["fired"] = True
            window.evaluate_js(
                "(async()=>{try{var b=window.__API_BASE__,t=window.__STOCKROOM_TOKEN__;"
                "var r=await fetch(b+'/api/library/parts/" + autocap_id + "/cad-source',"
                "{headers:{Authorization:'Bearer '+t}});var d=await r.json();"
                "if(window.pywebview&&window.pywebview.api&&window.pywebview.api.open_cad_download)"
                "{window.pywebview.api.open_cad_download(d.url,d.needs,d.mpn||'');}"
                "}catch(e){}})();"
            )

    window.events.loaded += _on_loaded
    # Adding a vendor ZIP also works through the native file picker exposed as
    # window.pywebview.api.pick_ingest_files (js_api above), the fallback path that
    # never depends on the drag-drop DOM registration above.
    #
    # A persistent, non-private WebView2 profile so a vendor login in the guided-capture
    # window survives across parts and launches (B5). pywebview sets storage once here at
    # start(), for every window in this session including the later cad window.
    profile_dir = config_dir() / "webview-profile"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError:  # a read-only/odd config dir must never block launch; login just won't persist
        pass
    try:
        webview.start(**_webview_start_kwargs(webview.start, profile_dir))  # blocks until close
    finally:
        _ACTIVE_WINDOW = None
