"""First-run onboarding surface (M9b): tell the app where the library lives (open an
existing one, clone a git URL, or create a fresh one), then repoint the running engine at
it LIVE via AppContext.switch_library (same token, so auth keeps working, no restart).

A frozen exe ships no library, so this is the gate that makes every library and project
feature usable on a real install. Read-only status + a set + a dismiss. Routers never
invent an error shape: onboarding raises ValueError for a bad request and api/errors.py
maps it to 400.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.schemas import SetLibraryBody
from stockroom.store import library_location as libloc
from stockroom.store import onboarding as onb
from stockroom.vcs.repo import GitError, GitRepo


def _status(ctx) -> dict:
    cfg = ctx.config
    root = Path(ctx.libraries_root)
    # The library that ships inside the app repo counts as onboarded even if this machine never
    # ran the setup screen: a clone of the app already carries it, so the app opens straight on
    # it. A completed onboarding choice keeps onboarded True too.
    onboarded = bool(getattr(cfg, "onboarded", False)) or libloc.ships_in_repo(root)
    # under_git via git itself (rev-parse), so the in-repo library, backed by the ENCLOSING app
    # repo with no nested .git of its own, still reports True.
    try:
        under_git = GitRepo(root).is_git_repo()
    except GitError:
        under_git = (root / ".git").exists()
    return {
        "onboarded": onboarded,
        "first_run": not onboarded,
        "libraries_root": root.as_posix(),
        "profiles": ctx.profile_store.list(),
        "under_git": under_git,
        "default_dir": onb.default_library_dir().as_posix(),
    }


def onboarding_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/onboarding", dependencies=[Depends(require_token)])

    @r.get("")
    def get_onboarding(request: Request) -> dict:
        # The current library location + whether the one-time welcome screen should show.
        return _status(request.app.state.ctx)

    @r.post("/library")
    def set_library(request: Request, body: SetLibraryBody) -> dict:
        # Open / create / clone the library, then repoint the running engine at it live (the
        # same token keeps authenticating). A bad mode / missing dir / non-empty clone dest
        # is a ValueError -> 400; a clone GitError -> 503.
        ctx = request.app.state.ctx
        root = onb.set_library(
            ctx.config, body.mode,
            path=body.path or None, url=body.url or None, dest=body.dest or None,
        )
        ctx.switch_library(root)
        return _status(ctx)

    @r.post("/complete")
    def complete(request: Request) -> dict:
        # Dismiss the welcome screen keeping the current (e.g. auto-created default) library.
        ctx = request.app.state.ctx
        onb.complete_onboarding(ctx.config)
        return _status(ctx)

    return r
