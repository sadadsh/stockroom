"""App-repo self-update: git pull --ff-only, then uv sync, then a graceful restart
(spec section 12; knowledge-transfer section 2, update flow). This is the CODE/UI/
DATA repo, distinct from the library sync in routers/sync.py. It reuses the same
ff-only + non-ff detection the library SyncEngine uses (GitRepo.pull_ff), and on a
non-fast-forward it DOES NOT guess: it surfaces DIVERGED and leaves resolution to
the owner (spec section 2.2, honest degradation). uv_runner and restart are
injected so this is pure, fixture-repo-testable logic with no real shell-out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from stockroom.vcs.repo import GitRepo


class UpdateState:
    UP_TO_DATE = "up_to_date"
    UPDATED = "updated"
    OFFLINE = "offline"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"


@dataclass
class UpdateResult:
    state: str
    updated: bool = False
    detail: str = ""
    restart_requested: bool = False


def _looks_offline(reason: str) -> bool:
    r = reason.lower()
    return any(
        tok in r
        for tok in ("could not resolve host", "connection", "timed out",
                    "network", "unable to access", "no route")
    )


class AppUpdater:
    def __init__(
        self,
        repo: GitRepo,
        uv_runner: Callable[[], None] | None = None,
        restart: Callable[[], None] | None = None,
    ):
        self.repo = repo
        self._uv = uv_runner or (lambda: None)
        self._restart = restart or (lambda: None)

    def check(self) -> dict:
        if not self.repo.has_remote():
            return {"update_available": False, "state": UpdateState.NO_REMOTE}
        # ahead_behind reads the local view; a real check fetches first, but the
        # fetch is a network op wrapped by update() itself. Report best-effort.
        ab = self.repo.ahead_behind()
        behind = ab[1] if ab else 0
        return {"update_available": behind > 0, "behind": behind}

    def update(self) -> UpdateResult:
        if not self.repo.has_remote():
            return UpdateResult(state=UpdateState.NO_REMOTE, detail="no remote configured")
        pull = self.repo.pull_ff()
        if not pull.ok:
            if _looks_offline(pull.reason):
                return UpdateResult(state=UpdateState.OFFLINE, detail=pull.reason)
            # a non-fast-forward is never guessed: surface it (spec section 2.2)
            return UpdateResult(state=UpdateState.DIVERGED, detail=pull.reason)
        if not pull.updated:
            return UpdateResult(state=UpdateState.UP_TO_DATE)
        # files changed: sync deps then request a graceful restart + reload
        self._uv()
        self._restart()
        return UpdateResult(state=UpdateState.UPDATED, updated=True, restart_requested=True)
