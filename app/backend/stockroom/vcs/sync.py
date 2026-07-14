"""Pull-before-push, fast-forward-only library sync.

True divergence is never clobbered: it is surfaced with the exact state and the
caller decides. Offline is a first-class state (local work is untouched, sync
resumes when the network returns). This is the unit the M5 background timer and
the post-commit hook call (spec sections 2 and 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from stockroom.vcs.repo import GitRepo


class SyncState:
    SYNCED = "synced"
    PUSHED = "pushed"
    PULLED = "pulled"
    OFFLINE = "offline"
    DIVERGED = "diverged"
    DENIED = "denied"
    NO_REMOTE = "no_remote"


@dataclass
class SyncResult:
    state: str
    pulled: bool = False
    pushed: bool = False
    detail: str = ""


def _looks_denied(reason: str) -> bool:
    """An authentication / authorization failure, distinct from a network outage or a genuine
    divergence: a private repo the bundled git cannot log in to, or a missing / rejected
    credential. GitHub answers a private repo with 'repository not found' to an unauthenticated
    client, so that phrase is an auth failure here (not a missing remote). Checked BEFORE
    _looks_offline because a 403 also reads as 'unable to access'."""
    r = reason.lower()
    return any(
        tok in r
        for tok in (
            "authentication failed", "could not read username", "could not read password",
            "terminal prompts disabled", "permission denied", "repository not found",
            "invalid username or password", "support for password authentication",
            "403 forbidden", "error: 403",
        )
    )


def _looks_offline(reason: str) -> bool:
    r = reason.lower()
    return any(
        tok in r
        for tok in ("could not resolve host", "connection", "timed out",
                    "network", "unable to access", "no route")
    )


def _classify_failure(reason: str) -> str:
    """The honest state for a failed pull/push reason: an auth failure is DENIED, a network
    outage is OFFLINE, anything else is a genuine DIVERGED (history conflict)."""
    if _looks_denied(reason):
        return SyncState.DENIED
    if _looks_offline(reason):
        return SyncState.OFFLINE
    return SyncState.DIVERGED


class SyncEngine:
    def __init__(self, repo: GitRepo):
        self.repo = repo

    def sync(self) -> SyncResult:
        # Remote presence is a `git remote` fact, NOT an upstream-ref fact: a freshly
        # cloned empty remote has a remote but no upstream ref until the first push.
        if not self.repo.has_remote():
            return SyncResult(state=SyncState.NO_REMOTE, detail="no remote configured")

        has_upstream = self.repo.has_upstream()

        pulled = False
        if has_upstream:
            pull = self.repo.pull_ff()
            if not pull.ok:
                return SyncResult(state=_classify_failure(pull.reason), detail=pull.reason)
            pulled = pull.updated

        # decide whether we have local commits to push
        if has_upstream:
            ahead, _behind = self.repo.ahead_behind() or (0, 0)
            need_push = ahead > 0
        else:
            # no upstream yet: any local commit is a first push that also sets upstream
            need_push = self.repo.head() != ""

        pushed = False
        if need_push:
            push = self.repo.push()
            if not push.ok:
                return SyncResult(state=_classify_failure(push.reason), pulled=pulled,
                                  detail=push.reason)
            pushed = True

        if pushed:
            return SyncResult(state=SyncState.PUSHED, pulled=pulled, pushed=True)
        if pulled:
            return SyncResult(state=SyncState.PULLED, pulled=True)
        return SyncResult(state=SyncState.SYNCED)
