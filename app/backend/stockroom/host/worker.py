"""Windowless backend worker used by the persistent-window update host."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    token = os.environ.pop("STOCKROOM_HANDOFF_TOKEN", "")
    if not token:
        raise SystemExit("STOCKROOM_HANDOFF_TOKEN is required")

    release_id = os.environ.pop("STOCKROOM_RELEASE_ID", "")
    generation_text = os.environ.pop("STOCKROOM_SERVICE_GENERATION", "")
    service_mode = os.environ.pop("STOCKROOM_SERVICE_MODE", "")
    control_database = os.environ.pop("STOCKROOM_CONTROL_DATABASE", "")
    control_secret = os.environ.pop("STOCKROOM_SERVICE_CONTROL_TOKEN", "")
    workflow_database = os.environ.pop("STOCKROOM_WORKFLOW_DATABASE", "")
    managed = bool(control_database)
    production = os.environ.get("STOCKROOM_UPDATE_MODE", "").strip().casefold() == "production"
    # Validate the complete managed identity before constructing any application
    # object. A malformed production candidate gets no opportunity to inspect,
    # migrate, or repair shared machine/library state.
    if managed:
        if (
            not release_id
            or not generation_text.isdecimal()
            or int(generation_text) <= 0
            or service_mode != "shadow"
            or not control_secret
            or not workflow_database
        ):
            raise SystemExit("managed release worker identity is incomplete")
    elif production:
        raise SystemExit("production release worker authority is required")

    import uvicorn

    from stockroom.api.app import create_app
    from stockroom.api.serve import build_context
    from stockroom.host.run import _install_injected_index
    from stockroom.host.service_authority import (
        ContextServiceAuthority,
        ContextServiceLifecycle,
        install_service_authority_routes,
    )

    ctx = build_context(cold=managed)
    ctx.token = token
    authority = None
    if managed:
        from stockroom.planning.production_composition import (
            build_production_workflow_registry_for_context,
        )

        lifecycle = ContextServiceLifecycle(
            ctx,
            workflow_database=Path(workflow_database),
            workflow_registry_factory=(build_production_workflow_registry_for_context),
            enable_altium=True,
            require_publication_executor=True,
        )
        authority = ContextServiceAuthority(
            ctx,
            release_id=release_id,
            control_database=Path(control_database),
            lifecycle=lifecycle,
        )
        snapshot = authority.snapshot()
        if (
            snapshot.status.value != "active"
            or snapshot.generation != int(generation_text)
            or snapshot.mode.value != "shadow"
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
    _install_injected_index(app, public_base_url, token)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        try:
            if authority is not None:
                authority.close()
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
