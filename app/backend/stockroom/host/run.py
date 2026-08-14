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

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from stockroom.api.context import AppContext
from stockroom.launcher.exit_codes import EXIT_RESTART

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# EXIT_RESTART (the self-update restart exit code the launcher relaunches on) lives in the
# leaf module stockroom.launcher.exit_codes so the frozen launcher can import it without
# dragging this whole host/API module into the bundle (M9d). Re-exported here for the host.
__all__ = ["EXIT_RESTART", "run_windowed", "main"]


def _serve_in_thread(app, port: int, timeout: float = 15.0):
    """Start uvicorn on a daemon thread bound to loopback and return once it is
    accepting connections. Raises if it never comes up (honest, no silent hang).
    uvicorn skips signal-handler install off the main thread, so this is safe."""
    import uvicorn

    # PyInstaller's windowed executable intentionally has no stdout/stderr.
    # Uvicorn's default logging formatter probes ``sys.stdout.isatty()`` while
    # configuring itself, which crashes a real double-click launch before the
    # native window can appear. The stable host owns its own diagnostics, so
    # keep uvicorn's console/access logging disabled at this embedded boundary.
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,
        access_log=False,
    )
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
    from stockroom.host.window import request_window_close

    if not request_window_close():
        raise RuntimeError("the active Stockroom window did not accept a close request")


def _start_restart_watchdog(
    graceful_handoff: threading.Event,
    *,
    delay_seconds: float = 8.0,
    exit_process: Callable[[int], None] = os._exit,
) -> threading.Thread:
    """Guarantee the launcher regains control when a native window ignores close.

    A graceful WebView close remains the preferred path because it lets the host
    release every service normally. If that UI thread does not return within the
    bounded delay, exiting with ``EXIT_RESTART`` transfers control to the stable
    launcher, which starts the freshly downloaded checkout.
    """

    def _watch() -> None:
        if not graceful_handoff.wait(max(0.0, float(delay_seconds))):
            exit_process(EXIT_RESTART)

    thread = threading.Thread(
        target=_watch,
        name="stockroom-restart-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def _same_origin_reload_url(base_url: str, current_url: str | None) -> str:
    """Retarget the active SPA route onto ``base_url`` without preserving remote URLs."""

    if not current_url:
        return base_url
    base = urlsplit(base_url)
    current = urlsplit(current_url)
    if (
        current.scheme.casefold() != base.scheme.casefold()
        or current.netloc.casefold() != base.netloc.casefold()
    ):
        return base_url
    return urlunsplit(
        (
            base.scheme,
            base.netloc,
            current.path or "/",
            current.query,
            current.fragment,
        )
    )


def _cache_busted_reload_url(url: str, token: str) -> str:
    """Force WebView2 to fetch the replaced index while preserving the active route."""

    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "__stockroom_reload"
    ]
    query.append(("__stockroom_reload", token))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def _persist_active_window_session(
    win,
    config=None,
    *,
    required: bool = True,
) -> bool:
    """Synchronously capture the renderer's last-keystroke state, when supported.

    The export hook is deliberately synchronous: navigation cannot race an async
    PUT whose renderer is about to be destroyed.  Old frontend bundles have no
    hook and remain reloadable.  Once a bundle exposes the hook, a malformed or
    failed export aborts an in-process navigation rather than silently losing the
    user's work. A full process restart may pass ``required=False``: the normal
    debounced server copy remains durable, while a malformed transient renderer
    envelope cannot veto application updates forever.
    """

    evaluate = getattr(win, "evaluate_js", None)
    if evaluate is None:
        return False
    try:
        exported = evaluate(
            "(function () {"
            "var f = window.__STOCKROOM_EXPORT_UI_SESSION__;"
            "return typeof f === 'function' ? f() : null;"
            "})()"
        )
    except Exception:
        if not required:
            return False
        raise RuntimeError("the active UI session could not be exported") from None
    if exported is None:
        return False
    from stockroom.store.ui_session import persist_export_envelope

    try:
        persist_export_envelope(exported, config)
    except Exception:
        if not required:
            return False
        raise RuntimeError("the active UI session export was invalid") from None
    return True


def _reload_active_window(
    base_url: str,
    timeout: float = 30.0,
    *,
    config=None,
) -> None:
    """Adopt a replaced frontend bundle and wait for the existing window to load it."""
    from stockroom.host.window import active_window

    win = active_window()
    if win is None:
        raise RuntimeError("the active Stockroom window is unavailable for frontend adoption")
    _persist_active_window_session(win, config)
    try:
        current_url = win.get_current_url()
    except Exception:  # noqa: BLE001 - an unreadable route falls back to the app root
        current_url = None
    target_url = _cache_busted_reload_url(
        _same_origin_reload_url(base_url, current_url),
        uuid4().hex,
    )
    loaded = threading.Event()

    def _loaded() -> None:
        loaded.set()

    event = getattr(getattr(win, "events", None), "loaded", None)
    if event is None:
        raise RuntimeError("the active window has no load-completion event")
    event += _loaded
    try:
        win.load_url(target_url)
        if not loaded.wait(timeout):
            raise RuntimeError("the active window did not load before the deadline")
    finally:
        try:
            event -= _loaded
        except Exception:  # noqa: BLE001 - an event cleanup failure cannot undo navigation
            pass


def _prepare_release_candidate(root: Path) -> None:
    """Create the candidate's frozen environment without mutating the live checkout."""
    proc = subprocess.run(
        ["uv", "sync", "--frozen"],
        cwd=str(root),
        capture_output=True,
        text=True,
        creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0,
        timeout=300.0,
    )
    if proc.returncode != 0:
        raise RuntimeError("candidate dependency preparation failed")


def _install_injected_index(
    app,
    base_url: str,
    token: str,
    config=None,
    *,
    expose_token_to_renderer: bool = True,
) -> None:
    """Serve the exact UI/session bootstrap ahead of the static SPA mount.

    The legacy pywebview host needs ``expose_token_to_renderer=True`` so its
    first queries authenticate before the asynchronous loaded callback. The
    native WebView2 host passes ``False`` and synchronously adds the token to
    approved same-origin requests; that path must never serialize the secret
    into the HTML/JavaScript document. No-op when the built frontend is absent.
    """
    from stockroom.api.app import _FRONTEND_DIST
    from stockroom.host.window import design_recovery_requested, inject_script

    index = _FRONTEND_DIST / "index.html"
    if not index.exists():
        return
    from starlette.responses import HTMLResponse
    from starlette.routing import Route

    def _render() -> str:
        # The UI preferences are read PER REQUEST, not baked in once at startup: the SPA reloads
        # itself after a self-update, and a reload must not resurrect the theme that was saved when
        # the process booted. The index.html text stays cached; only the small config is re-read.
        from stockroom.store.machine_config import MachineConfig
        from stockroom.store.ui_session import (
            bootstrap_script,
            default_snapshot,
            load_snapshot,
        )

        try:
            # Rendering index.html is a read. In particular, a managed shadow may
            # serve pre-adoption health/UI probes before it owns authority, so this
            # path must never trigger legacy credential migration.
            path = getattr(config, "source_path", None)
            ui = MachineConfig.load(
                path,
                migrate_credentials=False,
            ).ui
        except Exception:  # noqa: BLE001 - an unreadable config must never block the window opening
            ui = {}
        ui = {**ui, "design_bypass_applied": design_recovery_requested()}
        try:
            session = load_snapshot(config)
        except Exception:  # noqa: BLE001 - corrupt/dangling state is never injected
            session = default_snapshot()
        html = index.read_text(encoding="utf-8")
        return html.replace(
            "<head>",
            (
                "<head>\n<script>"
                + inject_script(
                    base_url,
                    token if expose_token_to_renderer else None,
                    ui=ui,
                )
                + bootstrap_script(session)
                + "</script>"
            ),
            1,
        )

    async def _index(_request):
        return HTMLResponse(_render())

    app.router.routes.insert(0, Route("/", _index))
    app.router.routes.insert(1, Route("/index.html", _index))


def _start_altium_library_convergence(ctx):
    """Start automatic DbLib setup for a real desktop context, if it has a profile."""

    if getattr(ctx, "profile", None) is None:
        return None
    from stockroom.altium.convergence import AltiumLibraryConvergenceService

    def _active_altium_library() -> Path | None:
        profile = getattr(ctx, "profile", None)
        if profile is None:
            return None
        return Path(profile.root) / "altium" / "Stockroom.DbLib"

    def _record_altium_convergence(result) -> None:
        setattr(ctx, "last_altium_convergence", result)

    service = AltiumLibraryConvergenceService(
        _active_altium_library,
        result_sink=_record_altium_convergence,
    )
    setattr(ctx, "altium_library_convergence", service)
    service.start()
    return service


def _development_service_state_root() -> Path:
    configured = os.environ.get("STOCKROOM_SERVICE_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise RuntimeError(
            "the Windows development service state root is unavailable"
        )
    return (Path(local_app_data) / "Stockroom" / "Service State").resolve()


def _prepare_managed_library(
    libraries_root: Path | None,
    *,
    service_state_root: Path,
    authority_scope: str = "ApplicationService",
) -> Path:
    """Bootstrap the first-run library only while holding service authority."""

    if libraries_root is not None:
        return Path(libraries_root).resolve()
    from stockroom.service import (
        ServiceControl,
        ServiceMode,
        WindowsCurrentIdentity,
        WindowsNamedMutexFactory,
    )
    from stockroom.store.machine_config import MachineConfig
    from stockroom.store.onboarding import bootstrap_library

    control = ServiceControl(
        Path(service_state_root).resolve() / "Control.sqlite",
        mode=ServiceMode.COORDINATOR,
        identity=WindowsCurrentIdentity(),
        mutex_factory=WindowsNamedMutexFactory(purpose=authority_scope),
        authority_scope=authority_scope,
    )
    fence = control.acquire()
    try:
        config = MachineConfig.load(migrate_credentials=False)
        return Path(bootstrap_library(config)).resolve()
    finally:
        try:
            control.release(fence)
        finally:
            control.close()


def _start_development_service_authority(
    ctx: AppContext,
    *,
    state_root: Path,
    enable_altium: bool,
    authority_scope: str = "ApplicationService",
):
    """Mount the production workflow owner without claiming signed delivery."""

    from stockroom.host.service_authority import (
        ContextServiceAuthority,
        ContextServiceLifecycle,
    )
    from stockroom.planning.production_composition import (
        build_production_workflow_registry_for_context,
    )

    app_repo = getattr(ctx, "app_repo", None)
    revision = ""
    if app_repo is not None:
        try:
            revision = app_repo.head()
        except Exception:  # noqa: BLE001 - identity remains explicitly source-only
            revision = ""
    release_id = f"development-{revision[:12]}" if revision else "development-source"
    root = Path(state_root).resolve()
    lifecycle = ContextServiceLifecycle(
        ctx,
        workflow_database=root / "Workflow.sqlite",
        workflow_registry_factory=build_production_workflow_registry_for_context,
        enable_altium=enable_altium,
        require_publication_executor=True,
    )
    return ContextServiceAuthority(
        ctx,
        release_id=release_id,
        control_database=root / "Control.sqlite",
        lifecycle=lifecycle,
        start_as_coordinator=True,
        authority_scope=authority_scope,
    )


def _mount_development_source_convergence(
    ctx: AppContext,
    app_repo,
    *,
    request_restart: Callable[[], None],
):
    """Continuously adopt ``main`` while the real Windows service authority owns work.

    The Windows source host already has one long-lived workflow/service authority, so it
    must not start the candidate-backend handoff used by lightweight development embeds.
    It still needs the same continuous Git delivery contract. WebView2 proved unable
    to adopt replaced bundle bytes reliably in this long-lived authority process, so
    every revision uses one session-preserving native restart through the stable
    launcher. That keeps the visible behavior deterministic without requiring the
    user to close the app or download another executable.
    """

    from stockroom.api.updater import AppUpdater
    from stockroom.update import UpdateConvergenceService

    updater = AppUpdater(
        app_repo,
        uv_runner=ctx.uv_sync,
        restart=request_restart,
        frontend_reload=request_restart,
    )
    setattr(ctx, "app_updater", updater)
    convergence = UpdateConvergenceService(
        updater,
        running_revision=app_repo.head(),
    )
    setattr(ctx, "update_convergence", convergence)
    return convergence


def run_windowed(
    ctx: AppContext | None = None,
    libraries_root: Path | None = None,
    kicad_dir: Path | None = None,
    open_window: Callable[[str, str], None] | None = None,
    source_service_state_root: Path | None = None,
    *,
    source_authority_scope: str = "ApplicationService",
    enable_source_convergence: bool = True,
) -> bool:
    """Run the app until the window closes. Returns True if the app requested a self-update
    restart (the launcher relaunches on the freshly pulled code), False on a normal close."""
    from stockroom.api.app import create_app
    from stockroom.api.serve import build_context, pick_free_port
    from stockroom.host.proxy import SwitchableBackendProxy
    from stockroom.host.release_runtime import (
        HostUpdateMode,
        UnavailableProductionUpdateRuntime,
        create_production_update_runtime,
        host_update_mode,
        production_data_root,
        verified_packaged_release_identity,
    )
    from stockroom.host.webview_fetch import WebViewRenderedDomFetcher

    update_mode = host_update_mode()
    owns_context = ctx is None
    managed_service_state_root: Path | None = None
    production_state_root: Path | None = None
    if owns_context:
        if os.name == "nt":
            if update_mode is HostUpdateMode.PRODUCTION:
                production_state_root = production_data_root()
                managed_service_state_root = (
                    production_state_root / "Service State"
                ).resolve()
            else:
                managed_service_state_root = (
                    _development_service_state_root()
                    if source_service_state_root is None
                    else Path(source_service_state_root).resolve()
                )
            prepared_library = _prepare_managed_library(
                libraries_root,
                service_state_root=managed_service_state_root,
                authority_scope=source_authority_scope,
            )
            ctx = build_context(
                prepared_library,
                kicad_dir=kicad_dir,
                cold=True,
            )
        else:
            ctx = build_context(libraries_root, kicad_dir=kicad_dir)
    assert ctx is not None
    if update_mode is HostUpdateMode.DEVELOPMENT_SOURCE and not enable_source_convergence:
        # Local development follows the selected working tree directly. Never let its API
        # fetch, rebase, pull, or replace dirty source while an editor is writing it.
        ctx.app_repo = None
    host_config = getattr(ctx, "config", None)
    setattr(ctx, "host_update_mode", update_mode.value)
    background_sync_stop: threading.Event | None = None
    update_convergence_stop = None
    altium_convergence = None
    launch_sync_thread: threading.Thread | None = None
    handoff = None
    development_service_authority = None
    production_update_runtime = None
    graceful_restart_handoff = threading.Event()
    restart_watchdog_started = False
    try:
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
            nonlocal restart_watchdog_started
            from stockroom.host.window import active_window

            win = active_window()
            if win is not None:
                _persist_active_window_session(
                    win,
                    host_config,
                    required=False,
                )
            restart_requested["value"] = True
            if not restart_watchdog_started:
                restart_watchdog_started = True
                _start_restart_watchdog(graceful_restart_handoff)
            try:
                _close_active_window()
            except RuntimeError:
                # The watchdog owns the deterministic fallback. Do not leave
                # convergence activation-pending after the checkout already moved.
                pass

        ctx.request_restart = _request_restart
        app_repo = getattr(ctx, "app_repo", None)

        if (
            update_mode is HostUpdateMode.DEVELOPMENT_SOURCE
            and os.name == "nt"
            and (owns_context or source_service_state_root is not None)
            and isinstance(ctx, AppContext)
        ):
            development_service_authority = (
                _start_development_service_authority(
                    ctx,
                    state_root=(
                        managed_service_state_root
                        or (
                            Path(source_service_state_root).resolve()
                            if source_service_state_root is not None
                            else _development_service_state_root()
                        )
                    ),
                    # Native Altium work is user-triggered from Settings. Merely opening the
                    # source host must not consume a seat or create command windows.
                    enable_altium=False,
                    authority_scope=source_authority_scope,
                )
            )
        elif update_mode is HostUpdateMode.DEVELOPMENT_SOURCE:
            # Non-Windows test/source embeddings retain the legacy local owners;
            # the canonical Windows source host always takes the fenced branch.
            launch_sync_thread = threading.Thread(
                target=ctx.sync_on_launch,
                name="stockroom-launch-sync",
                daemon=True,
            )
            launch_sync_thread.start()
            background_sync_stop = ctx.start_background_sync()
            if owns_context:
                altium_convergence = _start_altium_library_convergence(ctx)

        app = create_app(ctx)
        backend_proxy = SwitchableBackendProxy(app)
        port = pick_free_port()
        base_url = f"http://127.0.0.1:{port}"
        _install_injected_index(
            app,
            base_url,
            ctx.token,
            host_config,
        )  # auth + continuity from the first byte
        if update_mode is HostUpdateMode.DEVELOPMENT_SOURCE:
            # Every mutable-source window uses the same pywebview-owned provider surface, including
            # Stockroom Development's custom Vite opener. Restricting this to the default opener
            # left Manage Models with chrome but no native page. No debugging port is opened:
            # capture observes download events and never drives the provider page.
            from stockroom.host.window import InAppProviderBrowserSurface

            if getattr(ctx, "provider_browser_surface", None) is None:
                setattr(ctx, "provider_browser_surface", InAppProviderBrowserSurface(base_url))
        if update_mode is HostUpdateMode.PRODUCTION:
            try:
                production_update_runtime = create_production_update_runtime(
                    backend_proxy,
                    context=ctx,
                    public_base_url=base_url,
                    token=ctx.token,
                    reload_window=lambda url: _reload_active_window(
                        url,
                        config=host_config,
                    ),
                    manage_native_window=open_window is None,
                    data_root=production_state_root,
                )
            except Exception:  # noqa: BLE001 - keep the signed built-in UI observable
                try:
                    packaged_release_id = verified_packaged_release_identity()
                except Exception:  # noqa: BLE001 - never invent an unverified identity
                    packaged_release_id = ""
                blocker = "production_service_bootstrap_failed"
                # A production bootstrap failure is not permission to resurrect
                # unmanaged mutation owners. Keep the packaged UI and read paths
                # available for diagnosis while every mutation remains fenced.
                setattr(ctx, "release_id", packaged_release_id)
                setattr(ctx, "service_generation", 0)
                setattr(ctx, "service_mode", "shadow")
                setattr(ctx, "service_control", None)
                setattr(ctx, "service_fence", None)
                setattr(ctx, "workflow_coordinator", None)
                setattr(ctx, "service_authority_required", True)
                setattr(ctx, "service_degraded_reason", blocker)
                production_update_runtime = UnavailableProductionUpdateRuntime(
                    blocker=blocker,
                    release_id=packaged_release_id,
                )
            setattr(ctx, "update_convergence", production_update_runtime)
            provider_surface = getattr(
                production_update_runtime,
                "provider_browser_surface",
                None,
            )
            if callable(provider_surface):
                setattr(ctx, "provider_browser_surface", provider_surface)
            # The shell bridge behind Manage > Export Component... / Open In... / Reveal
            # Component Files.... Absent (and the three menu items with it) on a host that does
            # not own a native window, which is honest: nothing can reveal a folder from a
            # headless process, and an item that cannot work is a dead click path.
            native_shell = getattr(production_update_runtime, "native_shell", None)
            if native_shell is not None:
                setattr(ctx, "native_shell", native_shell)
        # Do not expose the local ASGI app until production authority is active
        # or explicitly bound fail-closed. This removes the startup interval in
        # which mutation routes previously ran without any service fence.
        server, thread = _serve_in_thread(backend_proxy, port)
        if (
            enable_source_convergence
            and update_mode is not HostUpdateMode.PRODUCTION
            and app_repo is not None
            and development_service_authority is None
        ):
            # Mutable Git delivery is a source-development compatibility mode
            # only. A frozen/production host never reaches this branch and can
            # never fall back to Git when its signed feed is unavailable.
            from stockroom.api.updater import AppUpdater
            from stockroom.store.machine_config import config_dir
            from stockroom.update import (
                GitReleaseStore,
                SeamlessBackendHandoff,
                UpdateConvergenceService,
                spawn_candidate_backend,
            )
            from stockroom.vcs.checkouts import (
                default_checkout_roots,
                scan_stockroom_checkouts,
            )

            releases_root = config_dir() / "app-releases"
            release_store = GitReleaseStore(app_repo, releases_root)

            def _adopt_backend(target_base_url: str) -> None:
                backend_proxy.switch(None if target_base_url == base_url else target_base_url)
                _reload_active_window(base_url, config=host_config)

            handoff = SeamlessBackendHandoff(
                release_store,
                original_revision=app_repo.head(),
                original_base_url=base_url,
                prepare=_prepare_release_candidate,
                spawn=lambda candidate: spawn_candidate_backend(
                    candidate,
                    ctx.token,
                    convergence_status_path=release_store.convergence_status_path,
                    checkout_inventory_path=release_store.checkout_inventory_path,
                    public_base_url=base_url,
                ),
                adopt=_adopt_backend,
            )
            handoff.restore_last_active()
            if handoff.active_base_url != base_url:
                backend_proxy.switch(handoff.active_base_url)
            updater = AppUpdater(
                app_repo,
                release_activation=handoff.activate,
                active_revision=lambda: handoff.active_revision,
                active_health=handoff.verify_active,
            )
            setattr(ctx, "app_updater", updater)
            convergence = UpdateConvergenceService(
                updater,
                running_revision=handoff.active_revision,
                status_sink=release_store.write_convergence_status,
            )
            setattr(ctx, "update_convergence", convergence)

            if owns_context:
                # Duplicate discovery is read-only and bounded.  It runs away from
                # the request path so opening Settings never stalls on a large drive.
                scanning_inventory = {
                    "state": "scanning",
                    "rival_count": 0,
                    "checkouts": [],
                }
                setattr(ctx, "checkout_inventory", scanning_inventory)
                release_store.write_checkout_inventory(scanning_inventory)

                def _scan_checkouts() -> None:
                    try:
                        inventory = scan_stockroom_checkouts(
                            app_repo,
                            roots=default_checkout_roots(app_repo.top_level() or app_repo.root),
                            active_library=ctx.repo.top_level(),
                            releases_root=releases_root,
                        )
                        setattr(ctx, "checkout_inventory", inventory)
                        release_store.write_checkout_inventory(inventory)
                    except Exception as exc:  # noqa: BLE001 - observability cannot block the app
                        inventory = {
                            "state": "failed",
                            "detail": str(exc),
                            "rival_count": 0,
                            "checkouts": [],
                        }
                        setattr(ctx, "checkout_inventory", inventory)
                        release_store.write_checkout_inventory(inventory)

                threading.Thread(
                    target=_scan_checkouts,
                    name="stockroom-checkout-inventory",
                    daemon=True,
                ).start()
        elif (
            enable_source_convergence
            and update_mode is not HostUpdateMode.PRODUCTION
            and app_repo is not None
            and development_service_authority is not None
        ):
            # The canonical Windows source host owns real workflows through its
            # coordinator, but must still converge to pushed main revisions. Keep
            # that updater alongside the authority instead of silently omitting it.
            _mount_development_source_convergence(
                ctx,
                app_repo,
                request_restart=_request_restart,
            )
        convergence = getattr(ctx, "update_convergence", None)
        if convergence is not None:
            update_convergence_stop = convergence.start()
        try:
            if (
                production_update_runtime is not None
                and production_update_runtime.owns_native_window
            ):
                # The stable broker remains alive while release-owned WPF/WebView2
                # windows replace one another. Only the currently active visible
                # child can end this wait; retiring an old window during an update
                # must never tear down the broker or service authority.
                production_update_runtime.wait_until_window_closed()
                # A normal return means the runtime observed an AUTHENTICATED close
                # of the active window (every other outcome raises). That is exactly
                # the graceful handoff the restart watchdog waits for, so stand it
                # down HERE, before the shutdown budget below spends its seconds
                # against the same deadline. Without this the watchdog armed by
                # _request_restart hard-exits mid-shutdown on every production
                # update; it must stay the last resort for a window that does not
                # close, which is the raising path and correctly skips this line.
                graceful_restart_handoff.set()
            else:
                opener = open_window or _open_window
                opener(base_url, ctx.token)  # degraded/source compatibility window
                graceful_restart_handoff.set()
        finally:
            try:
                if production_update_runtime is not None:
                    production_update_runtime.close()
                    production_update_runtime = None
            finally:
                server.should_exit = True
                thread.join(timeout=5.0)
        return restart_requested["value"]
    finally:
        if production_update_runtime is not None:
            production_update_runtime.close()
        if background_sync_stop is not None:
            background_sync_stop.set()
        if update_convergence_stop is not None:
            update_convergence_stop.set()
            update_convergence_stop.join(timeout=5.0)
        if altium_convergence is not None:
            altium_convergence.stop()
        if handoff is not None:
            handoff.close()
        if development_service_authority is not None:
            development_service_authority.close()
        if owns_context:
            # Usually finished long before the user closes the window. Bound the wait so an
            # unreachable remote cannot turn window shutdown into an indefinite hang.
            if launch_sync_thread is not None:
                launch_sync_thread.join(timeout=5.0)
            ctx.close()


def _spawn_self() -> int:
    """Run this host again, in a child process, and return its exit code.

    The SAME interpreter and the SAME module, deliberately: resolving either from PATH would
    relaunch whatever python happens to be first, which on a machine with several is not the
    install's venv.
    """
    return subprocess.call(
        [sys.executable, "-m", "stockroom.host.run"],
        creationflags=_NO_WINDOW,
    )


def main() -> None:
    """Run the window, and RELAUNCH after a self-update rather than assuming a supervisor exists.

    The host used to just `raise SystemExit(EXIT_RESTART)` and trust something outside to bring it
    back. Only the frozen `Stockroom.exe` does that -- and the owner runs
    `python -m stockroom.host.run`, with no exe and no shortcut on the machine. So every update
    pulled the files, closed the window, and ended. From the owner's side: *"my app still wont
    update even with latest files pulled"* -- the pull had worked every time; nothing restarted.

    Relaunching in-process makes the update path whole however the app was started, and the
    EXIT_RESTART fallback keeps the launcher's contract intact for a frozen install. The child's
    exit code becomes ours, so a second update inside the new process still works.
    """
    if not run_windowed():
        return
    try:
        code = _spawn_self()
    except Exception:  # noqa: BLE001 - a failed relaunch must fall back, never kill the update
        raise SystemExit(EXIT_RESTART) from None
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
