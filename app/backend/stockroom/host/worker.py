"""Windowless backend worker used by the persistent-window update host."""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path


class _DeferredAttachedProviderSurface:
    """Make the parent-owned provider surface callable before its pipe handshake finishes."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._surface = None
        self._error: BaseException | None = None

    def bind(self, surface) -> None:
        self._surface = surface
        self._ready.set()

    def fail(self, error: BaseException) -> None:
        self._error = error
        self._ready.set()

    def _require_surface(self):
        if not self._ready.wait(15.0) or self._surface is None:
            raise RuntimeError("the packaged provider browser did not connect") from self._error
        return self._surface

    def provider_browser_surface(self, **kwargs):
        return self._require_surface().provider_browser_surface(**kwargs)

    def show_active_provider_browser(self) -> None:
        self._require_surface().show_active_provider_browser()

    def close_active_provider_browser(self) -> None:
        if self._ready.is_set() and self._surface is not None:
            self._surface.close_active_provider_browser()

    def close(self) -> None:
        if self._ready.is_set() and self._surface is not None:
            self._surface.close()


def _managed_update_runtime_factory():
    from stockroom.host.release_runtime import (
        HostUpdateMode,
        create_production_update_runtime,
        create_store_update_runtime,
        host_update_mode,
    )

    return (
        create_store_update_runtime
        if host_update_mode() is HostUpdateMode.MICROSOFT_STORE
        else create_production_update_runtime
    )


def _application_authority_scope(package_probe_scope: str) -> str:
    from stockroom.service import DEFAULT_AUTHORITY_SCOPE

    return package_probe_scope or DEFAULT_AUTHORITY_SCOPE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    token = os.environ.pop("STOCKROOM_HANDOFF_TOKEN", "")
    if not token:
        raise SystemExit("STOCKROOM_HANDOFF_TOKEN is required")
    startup_proof_token = os.environ.pop("STOCKROOM_STARTUP_PROOF_TOKEN", "")

    release_id = os.environ.pop("STOCKROOM_RELEASE_ID", "")
    generation_text = os.environ.pop("STOCKROOM_SERVICE_GENERATION", "")
    service_mode = os.environ.pop("STOCKROOM_SERVICE_MODE", "")
    control_database = os.environ.pop("STOCKROOM_CONTROL_DATABASE", "")
    control_secret = os.environ.pop("STOCKROOM_SERVICE_CONTROL_TOKEN", "")
    workflow_database = os.environ.pop("STOCKROOM_WORKFLOW_DATABASE", "")
    managed = bool(control_database)
    coordinator = managed and service_mode == "coordinator"
    production = os.environ.get("STOCKROOM_UPDATE_MODE", "").strip().casefold() == "production"
    # Validate the complete managed identity before constructing any application
    # object. A malformed production candidate gets no opportunity to inspect,
    # migrate, or repair shared machine/library state.
    if managed:
        shadow_identity_valid = (
            service_mode == "shadow"
            and generation_text.isdecimal()
            and int(generation_text) > 0
            and bool(control_secret)
        )
        coordinator_identity_valid = service_mode == "coordinator" and not generation_text
        if (
            not release_id
            or not workflow_database
            or not (shadow_identity_valid or coordinator_identity_valid)
        ):
            raise SystemExit("managed release worker identity is incomplete")
    elif production:
        raise SystemExit("production release worker authority is required")
    if production and coordinator and not startup_proof_token:
        raise SystemExit("STOCKROOM_STARTUP_PROOF_TOKEN is required")

    import uvicorn

    from stockroom.api.app import create_app
    from stockroom.api.serve import build_context
    from stockroom.host.run import _install_injected_index, _prepare_managed_library
    from stockroom.host.service_authority import (
        ContextServiceAuthority,
        ContextServiceLifecycle,
        install_service_authority_routes,
    )

    package_probe_scope = os.environ.pop("STOCKROOM_PACKAGE_PROBE_SCOPE", "")
    application_authority_scope = _application_authority_scope(package_probe_scope)
    if coordinator:
        prepared_library = _prepare_managed_library(
            None,
            service_state_root=Path(control_database).resolve().parent,
            authority_scope=application_authority_scope,
        )
        ctx = build_context(prepared_library, cold=True)
    else:
        ctx = build_context(cold=managed)
    ctx.token = token
    if startup_proof_token:
        ctx.startup_proof_token = startup_proof_token
    authority = None
    production_update_runtime = None
    if managed and not coordinator:
        from stockroom.planning.production_composition import (
            build_production_workflow_registry_for_context,
        )

        lifecycle = ContextServiceLifecycle(
            ctx,
            workflow_database=Path(workflow_database),
            workflow_registry_factory=(build_production_workflow_registry_for_context),
            enable_altium=False,
            require_publication_executor=True,
        )
        authority = ContextServiceAuthority(
            ctx,
            release_id=release_id,
            control_database=Path(control_database),
            lifecycle=lifecycle,
            start_as_coordinator=coordinator,
        )
        snapshot = authority.snapshot()
        if (
            snapshot.status.value != "active"
            or (not coordinator and snapshot.generation != int(generation_text))
            or snapshot.mode.value != service_mode
        ):
            authority.close()
            ctx.close()
            raise SystemExit("release worker generation fence is stale")
    else:
        setattr(ctx, "release_id", release_id or "development-source")
        setattr(ctx, "service_generation", int(generation_text or "0"))
        setattr(ctx, "service_mode", service_mode or "standalone")
    convergence_status = os.environ.pop("STOCKROOM_CONVERGENCE_STATUS", "")
    if convergence_status:
        setattr(ctx, "convergence_status_path", Path(convergence_status))
    checkout_inventory = os.environ.pop("STOCKROOM_CHECKOUT_INVENTORY", "")
    if checkout_inventory:
        setattr(ctx, "checkout_inventory_path", Path(checkout_inventory))
    attached_pipe = os.environ.pop("STOCKROOM_ATTACHED_WINDOW_PIPE", "")
    attached_host_pid = os.environ.pop("STOCKROOM_ATTACHED_WINDOW_PID", "")
    if bool(attached_pipe) != bool(attached_host_pid):
        ctx.close()
        raise SystemExit("attached window identity is incomplete")

    if authority is None:
        app = create_app(ctx)
    else:
        app = create_app(
            ctx,
            before_frontend_mount=lambda worker_app: install_service_authority_routes(
                worker_app,
                authority,
                secret=control_secret,
            ),
        )
    public_base_url = os.environ.pop(
        "STOCKROOM_PUBLIC_BASE_URL",
        f"http://127.0.0.1:{args.port}",
    )
    attached_surface = None
    if attached_pipe:
        try:
            expected_host_process_id = int(attached_host_pid)
        except ValueError as exc:
            ctx.close()
            raise SystemExit("attached window process identity is invalid") from exc
        attached_surface = _DeferredAttachedProviderSurface()
        setattr(ctx, "provider_browser_surface", attached_surface.provider_browser_surface)

        def connect_attached_window() -> None:
            try:
                from stockroom.host.window_runtime import AttachedProviderBrowserSurface
                from stockroom.host.window_supervisor import connect_attached_window_host

                client = connect_attached_window_host(
                    attached_pipe,
                    expected_host_process_id=expected_host_process_id,
                    release_id=release_id,
                    base_url=public_base_url,
                    api_credential=token,
                )
                attached_surface.bind(AttachedProviderBrowserSurface(client))
            except BaseException as exc:
                attached_surface.fail(exc)

        threading.Thread(
            target=connect_attached_window,
            name="Stockroom Attached Window",
            daemon=True,
        ).start()
    _install_injected_index(
        app,
        public_base_url,
        token,
        expose_token_to_renderer=False,
    )
    served_app = app
    if coordinator:
        from stockroom.host.proxy import SwitchableBackendProxy

        proxy = SwitchableBackendProxy(app)
        production_update_runtime = _managed_update_runtime_factory()(
            proxy,
            context=ctx,
            public_base_url=public_base_url,
            token=token,
            reload_window=lambda _url: None,
            manage_native_window=False,
            authority_scope=application_authority_scope,
        )
        setattr(ctx, "update_convergence", production_update_runtime)
        production_update_runtime.start()
        served_app = proxy
    try:
        uvicorn.run(served_app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        try:
            if attached_surface is not None:
                attached_surface.close()
            if production_update_runtime is not None:
                production_update_runtime.close()
            elif authority is not None:
                authority.close()
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
