"""Library sync state (spec sections 2.2, 9). Offline and divergence are
first-class states surfaced with exact detail, never clobbered; this is the LIBRARY
repo sync, distinct from the app self-update (updater.py)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request


def _working_copy_status(ctx) -> dict[str, str]:
    library_top = ctx.repo.top_level()
    app_repo = getattr(ctx, "app_repo", None)
    app_top = app_repo.top_level() if app_repo is not None else None
    if library_top is not None and app_top is not None and library_top == app_top:
        return {
            "mode": "embedded",
            "detail": "The library and application use one managed working copy.",
        }
    library_remote = ctx.repo.remote_url().strip().rstrip("/\\").casefold()
    app_remote = (
        app_repo.remote_url().strip().rstrip("/\\").casefold() if app_repo is not None else ""
    )
    if library_remote and app_remote and library_remote == app_remote:
        return {
            "mode": "rival_application_checkout",
            "detail": (
                "The active library is inside a second checkout of the application repository."
            ),
        }
    return {
        "mode": "separate",
        "detail": "The active library uses a separate working copy.",
    }


def sync_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/sync", dependencies=[Depends(require_token)])

    @r.post("")
    def do_sync(request: Request) -> dict:
        ctx = request.app.state.ctx
        result = ctx.sync.sync()
        if result.pulled:
            # A pull can bring in part records AND project registrations (both are committed into
            # this same library repo), and it can make generated artifacts stale when the installed
            # build or profile has changed. Match `AppContext.reconcile`: refresh stale derivations
            # first, then rebuild both indexes from their final on-disk state.
            ctx.refresh_stale_derivations()
            ctx.rebuild_index()
            ctx.rebuild_project_index()
        ctx.last_sync = result
        return {
            "state": result.state,
            "pulled": result.pulled,
            "pushed": result.pushed,
            "converged": getattr(result, "converged", False),
            "detail": result.detail,
        }

    @r.get("/status")
    def status(request: Request) -> dict:
        ctx = request.app.state.ctx
        ab = ctx.repo.ahead_behind()
        last = getattr(ctx, "last_sync", None)
        checkout_inventory = getattr(ctx, "checkout_inventory", None)
        mirrored_inventory = getattr(ctx, "checkout_inventory_path", None)
        if checkout_inventory is None and mirrored_inventory is not None:
            try:
                candidate = json.loads(mirrored_inventory.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    checkout_inventory = candidate
            except (OSError, ValueError):
                pass
        from stockroom.vcs.github_auth import accounts as github_accounts

        return {
            "has_remote": ctx.repo.has_remote(),
            "current_branch": ctx.repo.current_branch(),
            "ahead": ab[0] if ab else 0,
            "behind": ab[1] if ab else 0,
            "github_auth": {
                "mode": "git_credential_manager",
                "accounts": github_accounts(ctx.repo),
            },
            "working_copy": _working_copy_status(ctx),
            "checkout_inventory": checkout_inventory
            or {
                "state": "unavailable",
                "rival_count": 0,
                "checkouts": [],
            },
            "last_sync": (
                None
                if last is None
                else {
                    "state": last.state,
                    "pulled": last.pulled,
                    "pushed": last.pushed,
                    "converged": getattr(last, "converged", False),
                    "detail": last.detail,
                }
            ),
        }

    @r.post("/github/login")
    def github_login(request: Request) -> dict:
        """Start the current Windows user's Git Credential Manager OAuth flow."""
        from stockroom.vcs.github_auth import login

        ctx = request.app.state.ctx

        def work(progress):
            progress({"stage": "waiting", "pct": 0.2, "message": "waiting for GitHub sign-in"})
            return {"mode": "git_credential_manager", "accounts": login(ctx.repo)}

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/remote")
    def connect_remote(request: Request, body: dict) -> dict:
        """Attach this library repo to one credential-helper-authenticated GitHub remote."""
        url = str(body.get("url") or "").strip()
        parsed = urlsplit(url)
        if (
            parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "github.com"
            or parsed.username
            or parsed.password
            or not parsed.path.strip("/")
        ):
            raise ValueError("enter an HTTPS GitHub repository URL without embedded credentials")
        ctx = request.app.state.ctx
        if ctx.repo.remote_url("origin"):
            raise ValueError("origin is already configured for this library")
        ctx.repo.add_remote("origin", url)
        return {"configured": True, "remote": url}

    return r
