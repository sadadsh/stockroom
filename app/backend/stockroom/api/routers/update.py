"""App-repo self-update (spec section 12; distinct from library sync in sync.py).

The route exposes the installed checkout's identity and delivery policy, fetches before deciding
whether an update exists, and applies a fast-forward or a safe rebase of disjoint local library
commits before syncing dependencies and requesting a graceful restart. A true conflict remains an
honest DIVERGED state. Token-guarded like every route.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request

from stockroom.api.updater import AppUpdater, UpdateState


def _frontend_revision() -> str:
    """Revision baked into the exact SPA bundle served by this backend."""

    from stockroom.api.app import _FRONTEND_DIST

    try:
        document = json.loads((_FRONTEND_DIST / "build-identity.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    version = document.get("version") if isinstance(document, dict) else None
    if not isinstance(version, str):
        return ""
    match = re.search(r"\+([0-9a-f]{7,})$", version.strip(), flags=re.IGNORECASE)
    return match.group(1) if match is not None else ""


def _with_frontend_revision(status: dict) -> dict:
    return {**status, "frontend_revision": _frontend_revision()}


def update_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/update", dependencies=[Depends(require_token)])

    @r.get("/check")
    def check(request: Request) -> dict:
        ctx = request.app.state.ctx
        convergence = getattr(ctx, "update_convergence", None)
        if convergence is not None:
            return _with_frontend_revision(convergence.status())
        mirrored_status = getattr(ctx, "convergence_status_path", None)
        if mirrored_status is not None:
            try:
                document = json.loads(mirrored_status.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    return _with_frontend_revision(document)
            except (OSError, ValueError):
                pass
        if ctx.app_repo is None:
            return _with_frontend_revision(
                {
                    "update_available": False,
                    "state": UpdateState.NO_REMOTE,
                    "detail": "this installation is not managed by an application checkout",
                    "current_revision": "",
                    "target_revision": "",
                    "channel": "unmanaged",
                    "automatic_on_launch": False,
                    "check_interval_seconds": 120,
                }
            )
        return _with_frontend_revision(AppUpdater(ctx.app_repo).check())

    @r.post("/apply")
    def apply(request: Request) -> dict:
        ctx = request.app.state.ctx
        convergence = getattr(ctx, "update_convergence", None)
        activate_ready = getattr(convergence, "activate_ready", None)
        if callable(activate_ready):
            accepted = bool(activate_ready())
            return {
                "state": "updating" if accepted else UpdateState.BLOCKED,
                "updated": False,
                "detail": (
                    "Restarting into the verified release."
                    if accepted
                    else "No verified release is ready to apply."
                ),
                "restart_requested": False,
                "frontend_reload_requested": False,
                "seamless_handoff_requested": accepted,
                "activated_revision": "",
                "rolled_back": False,
            }
        if convergence is not None or getattr(ctx, "convergence_status_path", None) is not None:
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
