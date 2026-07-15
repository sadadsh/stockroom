"""App-repo self-update: pull the latest code, then uv sync, then a graceful restart
(spec section 12; knowledge-transfer section 2, update flow). This is the CODE/UI/
DATA repo, distinct from the library sync in routers/sync.py.

It tries a fast-forward first; on a non-fast-forward it RECONCILES by rebase, because
the in-repo library means a local part commit (libraries/) and a remote app-code commit
(app/) touch DISJOINT paths (the same reason the launcher's boot-time _reconcile_pull
rebases). A plain ff-only would get permanently stuck the moment the first part is added,
forcing the user to re-download a release to update. Only a TRUE conflict (the rare
same-file case) is surfaced as DIVERGED, never guessed (spec section 2.2, honest
degradation). uv_runner and restart are injected so this is pure, fixture-repo-testable
logic with no real shell-out."""

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
        # A real check must FETCH first: ahead_behind reads the local view of the
        # remote refs, so without a fetch the running app can never learn that a
        # new release exists and the Apply button never appears (the stuck-update
        # bug). An unreachable remote is reported honestly, never as Up To Date.
        ok, reason = self.repo.fetch()
        if not ok:
            return {
                "update_available": False,
                "state": UpdateState.OFFLINE,
                "detail": reason,
            }
        ab = self.repo.ahead_behind()
        behind = ab[1] if ab else 0
        return {"update_available": behind > 0, "behind": behind}

    def _apply(self) -> UpdateResult:
        # files changed: sync deps then request a graceful restart + reload
        self._uv()
        self._restart()
        return UpdateResult(state=UpdateState.UPDATED, updated=True, restart_requested=True)

    def update(self) -> UpdateResult:
        if not self.repo.has_remote():
            return UpdateResult(state=UpdateState.NO_REMOTE, detail="no remote configured")
        pull = self.repo.pull_ff()
        if pull.ok:
            return self._apply() if pull.updated else UpdateResult(state=UpdateState.UP_TO_DATE)
        if _looks_offline(pull.reason):
            return UpdateResult(state=UpdateState.OFFLINE, detail=pull.reason)
        # A non-fast-forward is the in-repo library case: local part commits (libraries/) diverge
        # main from the remote app-code commits (app/), on DISJOINT paths. RECONCILE by rebase so
        # the self-update keeps flowing AND the user's parts are preserved (matching the launcher's
        # boot-time _reconcile_pull). A plain ff-only would get permanently stuck the moment the
        # first part is added, forcing a re-download. A TRUE conflict (the rare same-file case)
        # aborts the rebase and is surfaced honestly as DIVERGED, never guessed (spec section 2.2).
        reb = self.repo.pull_rebase()
        if reb.ok:
            return self._apply() if reb.updated else UpdateResult(state=UpdateState.UP_TO_DATE)
        if _looks_offline(reb.reason):
            return UpdateResult(state=UpdateState.OFFLINE, detail=reb.reason)
        return UpdateResult(state=UpdateState.DIVERGED, detail=reb.reason)
