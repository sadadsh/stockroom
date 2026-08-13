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

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stockroom.vcs.repo import GitRepo


class UpdateState:
    UP_TO_DATE = "up_to_date"
    UPDATED = "updated"
    OFFLINE = "offline"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"


@dataclass
class UpdateResult:
    state: str
    updated: bool = False
    detail: str = ""
    restart_requested: bool = False
    frontend_reload_requested: bool = False
    seamless_handoff_requested: bool = False
    activated_revision: str = ""
    rolled_back: bool = False


_LEGACY_RUNTIME_OVERRIDE_PATHS = frozenset(
    {
        "app/frontend/src/lib/copy.overrides.ts",
        "app/frontend/src/lib/element.overrides.ts",
        "app/frontend/src/lib/token.overrides.ts",
    }
)


def archive_legacy_runtime_overrides(
    repo: GitRepo,
    archive_root: Path | None = None,
) -> Path | None:
    """Preserve and clear the old generated source overrides that blocked updates.

    This migration is deliberately narrow. Only unstaged modifications to the
    three retired generated override modules are accepted. Any other tracked or
    staged work remains untouched and keeps automatic updating blocked.
    """

    changes = [line for line in repo.status_porcelain() if not line.startswith("??")]
    if not changes:
        return None
    selected: list[tuple[str, Path, bytes]] = []
    for line in changes:
        if len(line) < 4 or line[:2] != " M":
            return None
        relative = line[3:].replace("\\", "/")
        if relative not in _LEGACY_RUNTIME_OVERRIDE_PATHS:
            return None
        source = repo.root.joinpath(*relative.split("/"))
        try:
            data = source.read_bytes()
        except OSError:
            return None
        selected.append((relative, source, data))

    digest = hashlib.sha256()
    digest.update(repo.head().encode("ascii", errors="ignore"))
    for relative, _source, data in sorted(selected):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    root = Path(archive_root or (repo.root.parent / "Legacy Runtime Overrides"))
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{repo.head()[:12]}-{digest.hexdigest()[:16]}"
    temporary = Path(tempfile.mkdtemp(prefix=".Incoming-", dir=root))
    try:
        for relative, _source, data in selected:
            archived = temporary.joinpath(*relative.split("/"))
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_bytes(data)
        (temporary / "Archive.json").write_text(
            json.dumps(
                {
                    "schema": "stockroom-legacy-runtime-overrides/1",
                    "source_revision": repo.head(),
                    "paths": sorted(relative for relative, _source, _data in selected),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            for relative, _source, data in selected:
                if destination.joinpath(*relative.split("/")).read_bytes() != data:
                    return None
        else:
            os.replace(temporary, destination)
        repo.restore_paths([source for _relative, source, _data in selected])
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _looks_offline(reason: str) -> bool:
    r = reason.lower()
    return any(
        tok in r
        for tok in (
            "could not resolve host",
            "connection",
            "timed out",
            "network",
            "unable to access",
            "no route",
        )
    )


class AppUpdater:
    def __init__(
        self,
        repo: GitRepo,
        uv_runner: Callable[[], None] | None = None,
        restart: Callable[[], None] | None = None,
        frontend_reload: Callable[[], None] | None = None,
        release_activation: Callable[[str], object] | None = None,
        active_revision: Callable[[], str] | None = None,
        active_health: Callable[[], object] | None = None,
        legacy_override_archive: Path | None = None,
    ):
        self.repo = repo
        self._uv = uv_runner or (lambda: None)
        self._restart = restart or (lambda: None)
        self._frontend_reload = frontend_reload or (lambda: None)
        self._release_activation = release_activation
        self._active_revision = active_revision or self.repo.head
        self._active_health = active_health
        self._legacy_override_archive = legacy_override_archive

    def _check_identity(self) -> dict:
        """Stable, non-secret delivery facts the Settings UI can explain.

        A bare `update_available=false` cannot distinguish a current install from a detached,
        unreachable, or unmanaged one. Keep the payload deliberately small: exact local revision,
        release channel, and the launcher policy. No filesystem path or remote credential is exposed.
        """
        head = self._active_revision()
        return {
            "current_revision": head[:12] if head else "",
            "channel": self.repo.current_branch() or "detached",
            "automatic_on_launch": True,
            "check_interval_seconds": 120,
        }

    def check(self) -> dict:
        identity = self._check_identity()
        if not self.repo.has_remote():
            return {
                **identity,
                "update_available": False,
                "state": UpdateState.NO_REMOTE,
                "detail": "no application remote is configured",
                "target_revision": "",
            }
        # A real check must FETCH first: ahead_behind reads the local view of the
        # remote refs, so without a fetch the running app can never learn that a
        # new release exists and the Apply button never appears (the stuck-update
        # bug). An unreachable remote is reported honestly, never as Up To Date.
        ok, reason = self.repo.fetch()
        if not ok:
            return {
                **identity,
                "update_available": False,
                "state": UpdateState.OFFLINE,
                "detail": reason,
                "target_revision": "",
            }
        target = self.repo.upstream_head()
        if not target:
            return {
                **identity,
                "update_available": False,
                "state": UpdateState.UNVERIFIED,
                "detail": "the application branch has no verifiable upstream revision",
                "target_revision": "",
            }
        if self._release_activation is None:
            ab = self.repo.ahead_behind()
            if ab is None:
                return {
                    **identity,
                    "update_available": False,
                    "state": UpdateState.UNVERIFIED,
                    "detail": "the application branch has no verifiable upstream revision",
                    "target_revision": "",
                }
            behind = ab[1]
            update_available = behind > 0
        else:
            current = str(identity["current_revision"])
            update_available = current != target[:12]
            behind = 1 if update_available else 0
        return {
            **identity,
            "update_available": update_available,
            "state": "update_available" if update_available else UpdateState.UP_TO_DATE,
            "behind": behind,
            "target_revision": target[:12],
            # Internal consumers need the collision-free commit address.  The API
            # may expose it safely: a Git object name is not a credential.
            "target_revision_full": target,
        }

    @staticmethod
    def frontend_only(paths: tuple[str, ...]) -> bool:
        """Whether changed runtime bytes can be adopted by reloading the SPA."""
        if not paths or not any(path.startswith("app/frontend-dist/") for path in paths):
            return False
        harmless = (
            "app/frontend/",
            "app/frontend-dist/",
            "docs/",
            "tests/",
        )
        return all(path.startswith(harmless) for path in paths)

    def _apply(self, paths: tuple[str, ...]) -> UpdateResult:
        # Frozen dependency reconciliation runs before either adoption path.
        self._uv()
        if self.frontend_only(paths):
            self._frontend_reload()
            return UpdateResult(
                state=UpdateState.UPDATED,
                updated=True,
                frontend_reload_requested=True,
            )
        self._restart()
        return UpdateResult(state=UpdateState.UPDATED, updated=True, restart_requested=True)

    def activate_current(self, *, frontend_only: bool = False) -> UpdateResult:
        """Retry activation after bytes pulled successfully but dependency sync failed."""
        paths = ("app/frontend-dist/index.html",) if frontend_only else ("app/backend/",)
        return self._apply(paths)

    def verify_active(self) -> object | None:
        return self._active_health() if self._active_health is not None else None

    def update(self, target_revision: str | None = None) -> UpdateResult:
        if not self.repo.has_remote():
            return UpdateResult(state=UpdateState.NO_REMOTE, detail="no remote configured")
        if self._release_activation is not None:
            target = (target_revision or "").strip()
            if not target:
                ok, reason = self.repo.fetch()
                if not ok:
                    state = (
                        UpdateState.OFFLINE if _looks_offline(reason) else UpdateState.UNVERIFIED
                    )
                    return UpdateResult(state=state, detail=reason)
                target = self.repo.upstream_head()
            if not target:
                return UpdateResult(
                    state=UpdateState.UNVERIFIED,
                    detail="the application branch has no verifiable upstream revision",
                )
            if self._active_revision().casefold() == target.casefold():
                return UpdateResult(
                    state=UpdateState.UP_TO_DATE,
                    activated_revision=target,
                )
            outcome = self._release_activation(target)
            ok = bool(getattr(outcome, "ok", False))
            revision = str(getattr(outcome, "revision", ""))
            detail = str(getattr(outcome, "detail", ""))
            rolled_back = bool(getattr(outcome, "rolled_back", False))
            return UpdateResult(
                state=UpdateState.UPDATED if ok else UpdateState.BLOCKED,
                updated=ok,
                detail=detail,
                seamless_handoff_requested=ok,
                activated_revision=revision,
                rolled_back=rolled_back,
            )
        if self.repo.has_tracked_changes():
            archive_legacy_runtime_overrides(
                self.repo,
                self._legacy_override_archive,
            )
        if self.repo.has_tracked_changes():
            return UpdateResult(
                state=UpdateState.BLOCKED,
                detail="uncommitted tracked application files block automatic convergence",
            )
        before = self.repo.head()
        pull = self.repo.pull_ff()
        if pull.ok:
            if not pull.updated:
                return UpdateResult(state=UpdateState.UP_TO_DATE)
            paths = self.repo.changed_paths(before, self.repo.head())
            result = self._apply(paths)
            result.activated_revision = self.repo.head()
            return result
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
            if not reb.updated:
                return UpdateResult(state=UpdateState.UP_TO_DATE)
            paths = self.repo.changed_paths(before, self.repo.head())
            result = self._apply(paths)
            result.activated_revision = self.repo.head()
            return result
        if _looks_offline(reb.reason):
            return UpdateResult(state=UpdateState.OFFLINE, detail=reb.reason)
        return UpdateResult(state=UpdateState.DIVERGED, detail=reb.reason)
