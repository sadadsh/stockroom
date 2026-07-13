"""Library sync state (spec sections 2.2, 9). Offline and divergence are
first-class states surfaced with exact detail, never clobbered; this is the LIBRARY
repo sync, distinct from the app self-update (updater.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request


def sync_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/sync", dependencies=[Depends(require_token)])

    @r.post("")
    def do_sync(request: Request) -> dict:
        ctx = request.app.state.ctx
        result = ctx.sync.sync()
        if result.pulled:
            ctx.rebuild_index()
        return {"state": result.state, "pulled": result.pulled,
                "pushed": result.pushed, "detail": result.detail}

    @r.get("/status")
    def status(request: Request) -> dict:
        ctx = request.app.state.ctx
        ab = ctx.repo.ahead_behind()
        return {
            "has_remote": ctx.repo.has_remote(),
            "current_branch": ctx.repo.current_branch(),
            "ahead": ab[0] if ab else 0,
            "behind": ab[1] if ab else 0,
        }

    return r
