"""App-repo self-update (spec section 12; distinct from library sync in sync.py).

The route exposes the installed checkout's identity and delivery policy, fetches before deciding
whether an update exists, and applies a fast-forward or a safe rebase of disjoint local library
commits before syncing dependencies and requesting a graceful restart. A true conflict remains an
honest DIVERGED state. Token-guarded like every route.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from stockroom.api.updater import AppUpdater, UpdateState


def update_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/update", dependencies=[Depends(require_token)])

    @r.get("/check")
    def check(request: Request) -> dict:
        ctx = request.app.state.ctx
        convergence = getattr(ctx, "update_convergence", None)
        if convergence is not None:
            return convergence.status()
        mirrored_status = getattr(ctx, "convergence_status_path", None)
        if mirrored_status is not None:
            try:
                document = json.loads(mirrored_status.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    return document
            except (OSError, ValueError):
                pass
        if ctx.app_repo is None:
            return {
                "update_available": False,
                "state": UpdateState.NO_REMOTE,
                "detail": "this installation is not managed by an application checkout",
                "current_revision": "",
                "target_revision": "",
                "channel": "unmanaged",
                "automatic_on_launch": False,
                "check_interval_seconds": 120,
            }
        return AppUpdater(ctx.app_repo).check()

    @r.post("/apply")
    def apply(request: Request) -> dict:
        ctx = request.app.state.ctx
        if (
            getattr(ctx, "update_convergence", None) is not None
            or getattr(ctx, "convergence_status_path", None) is not None
        ):
            return {
                "state": UpdateState.BLOCKED,
                "updated": False,
                "detail": "the persistent window host applies verified releases automatically",
                "restart_requested": False,
                "frontend_reload_requested": False,
                "seamless_handoff_requested": False,
                "activated_revision": "",
                "rolled_back": False,
            }
        if ctx.app_repo is None:
            return {
                "state": UpdateState.NO_REMOTE,
                "updated": False,
                "detail": "no app repo available",
                "restart_requested": False,
            }
        updater = getattr(ctx, "app_updater", None) or AppUpdater(
            ctx.app_repo, uv_runner=ctx.uv_sync, restart=ctx.request_restart
        )
        result = updater.update()
        return {
            "state": result.state,
            "updated": result.updated,
            "detail": result.detail,
            "restart_requested": result.restart_requested,
            "frontend_reload_requested": result.frontend_reload_requested,
            "seamless_handoff_requested": result.seamless_handoff_requested,
            "activated_revision": result.activated_revision[:12],
            "rolled_back": result.rolled_back,
        }

    return r
