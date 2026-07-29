"""A safe work-session boundary for two people editing one EDA Git repository."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import uuid4

from stockroom.text import counted
from stockroom.vcs.locks import DocumentLock, LockError
from stockroom.vcs.repo import GitRepo


class CollaborationError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class DocumentLockService(Protocol):
    def available(self) -> tuple[bool, str]: ...

    def acquire(self, path: Path | str) -> DocumentLock: ...

    def owns(self, expected: DocumentLock) -> bool: ...

    def release(self, lock: DocumentLock, *, force: bool = False) -> None: ...


@dataclass(frozen=True)
class WorkSession:
    id: str
    owner: str
    branch: str
    base_branch: str
    base_commit: str
    documents: tuple[str, ...]
    locks: tuple[DocumentLock, ...]
    started_at: str
    shared_commit: str = ""


@dataclass(frozen=True)
class ReviewCandidate:
    branch: str
    commit: str
    base_branch: str
    base_commit: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReviewEvent:
    """An immutable repository-backed decision bound to one exact review commit."""

    id: str
    kind: str
    branch: str
    commit: str
    base_branch: str
    base_commit: str
    reviewer: str
    message: str
    created_at: str


@dataclass(frozen=True)
class ReviewListing:
    """One pushed work branch as observed from the current remote base."""

    branch: str
    commit: str
    base_branch: str
    base_commit: str
    fork_commit: str
    changed_paths: tuple[str, ...]
    commit_count: int
    ready: bool
    blocked_reason: str = ""
    events: tuple[ReviewEvent, ...] = ()


class WorkSessionManager:
    """Start and share a branch only while every edited document remains claimed."""

    def __init__(
        self,
        repo: GitRepo,
        locks: DocumentLockService,
        *,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ):
        self.repo = repo
        self.locks = locks
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: uuid4().hex)

    def start(
        self,
        *,
        owner: str,
        branch: str,
        documents: Sequence[Path | str],
    ) -> WorkSession:
        owner = owner.strip()
        if not owner:
            raise CollaborationError("owner_required", "a collaborator identity is required")
        if not documents:
            raise CollaborationError(
                "documents_required", "select at least one design document to edit"
            )
        self._validate_branch(branch)
        rel_documents = self._normalize_documents(documents)
        self._preflight_synced_base()
        remote_exists = self.repo._run(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{branch}",
            check=False,
        )
        if remote_exists.returncode == 0:
            raise CollaborationError(
                "branch_exists", f"remote work branch already exists: {branch}"
            )
        base_branch = self.repo.current_branch()
        base_commit = self.repo.head()

        available, reason = self.locks.available()
        if not available:
            raise CollaborationError(
                "locking_unavailable", reason or "the remote document lock service is unavailable"
            )

        acquired: list[DocumentLock] = []
        try:
            for document in rel_documents:
                acquired.append(self.locks.acquire(document))
            switched = self.repo._run("switch", "-c", branch, check=False)
            if switched.returncode != 0:
                raise CollaborationError(
                    "branch_failed",
                    (switched.stderr or switched.stdout).strip()
                    or f"could not create work branch {branch}",
                )
        except (CollaborationError, LockError) as exc:
            release_errors = self._release_best_effort(acquired)
            if isinstance(exc, CollaborationError):
                detail = exc.detail
                code = exc.code
            else:
                detail = str(exc)
                code = "lock_failed"
            if release_errors:
                detail += f"; lock cleanup also failed: {'; '.join(release_errors)}"
            raise CollaborationError(code, detail) from exc

        return WorkSession(
            id=self._new_id(),
            owner=owner,
            branch=branch,
            base_branch=base_branch,
            base_commit=base_commit,
            documents=rel_documents,
            locks=tuple(acquired),
            started_at=self._now().isoformat().replace("+00:00", "Z"),
        )

    def share(self, session: WorkSession, *, message: str) -> WorkSession:
        if self.repo.current_branch() != session.branch:
            raise CollaborationError(
                "wrong_branch", f"switch to {session.branch} before sharing this work session"
            )
        for lock in session.locks:
            try:
                owned = self.locks.owns(lock)
            except LockError as exc:
                raise CollaborationError(
                    "lock_status_failed",
                    f"the edit lock for {lock.path} could not be verified: {exc}",
                ) from exc
            if not owned:
                raise CollaborationError(
                    "lock_lost", f"the edit lock for {lock.path} is no longer owned"
                )

        dirty = self.repo.dirty_paths()
        if not dirty:
            raise CollaborationError("nothing_to_share", "the work session has no local changes")
        allowed = set(session.documents)
        unexpected = sorted(
            self.repo._rel(path) for path in dirty if self.repo._rel(path) not in allowed
        )
        if unexpected:
            raise CollaborationError(
                "unclaimed_changes",
                "changes outside the claimed documents must be resolved first: "
                + ", ".join(unexpected),
            )

        commit = self.repo.commit(message, dirty)
        pushed = self.repo.push()
        if not pushed.ok:
            raise CollaborationError(
                "push_failed",
                pushed.reason or "the remote rejected the work branch",
            )
        return replace(session, shared_commit=commit)

    def recovery_status(
        self,
        session: WorkSession,
        *,
        verify_claims: bool = True,
        trust_claims: bool = False,
    ) -> dict:
        """Diagnose a persisted session without changing source, refs, or claims."""

        current_branch = self.repo.current_branch()
        branch_exists = (
            self.repo._run(
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{session.branch}",
                check=False,
            ).returncode
            == 0
        )
        dirty = tuple(self.repo._rel(path) for path in self.repo.dirty_paths())
        claimed_set = set(session.documents)
        dirty_claimed = tuple(path for path in dirty if path in claimed_set)
        dirty_unclaimed = tuple(path for path in dirty if path not in claimed_set)
        missing = tuple(
            path for path in session.documents if not (self.repo.root / path).is_file()
        )
        issues: list[dict] = []
        held: list[str] = []
        lost: list[str] = []
        unknown: list[str] = []

        if not branch_exists:
            issues.append(
                {
                    "code": "work_branch_missing",
                    "severity": "error",
                    "detail": f"The local work branch {session.branch} is missing.",
                    "paths": [],
                }
            )
        elif current_branch != session.branch:
            issues.append(
                {
                    "code": (
                        "resume_branch_available"
                        if not dirty
                        else "wrong_branch_with_changes"
                    ),
                    "severity": "action" if not dirty else "error",
                    "detail": (
                        f"Resume the clean checkout on {session.branch}."
                        if not dirty
                        else "The checkout is on another branch and has local changes; "
                        "Stockroom will not switch it automatically."
                    ),
                    "paths": list(dirty),
                }
            )
        if missing:
            issues.append(
                {
                    "code": "claimed_documents_missing",
                    "severity": "error",
                    "detail": "One or more claimed native documents are missing.",
                    "paths": list(missing),
                }
            )
        if dirty_unclaimed:
            issues.append(
                {
                    "code": "unclaimed_changes",
                    "severity": "error",
                    "detail": "Local changes outside this session must remain separate.",
                    "paths": list(dirty_unclaimed),
                }
            )

        available, reason = self.locks.available() if verify_claims else (True, "")
        if trust_claims:
            held.extend(lock.path for lock in session.locks)
        elif not verify_claims:
            unknown.extend(lock.path for lock in session.locks)
            issues.append(
                {
                    "code": "claims_need_recovery",
                    "severity": "action",
                    "detail": (
                        "This session survived an application restart. Reverify its "
                        "remote claims before sharing."
                    ),
                    "paths": list(unknown),
                }
            )
        elif not available:
            unknown.extend(lock.path for lock in session.locks)
            issues.append(
                {
                    "code": "claim_service_offline",
                    "severity": "offline",
                    "detail": reason or "Remote document claims cannot be verified.",
                    "paths": list(unknown),
                }
            )
        else:
            for lock in session.locks:
                try:
                    owned = self.locks.owns(lock)
                except LockError as exc:
                    unknown.append(lock.path)
                    issues.append(
                        {
                            "code": "claim_status_unknown",
                            "severity": "offline",
                            "detail": f"The claim for {lock.path} could not be verified: {exc}",
                            "paths": [lock.path],
                        }
                    )
                    continue
                if owned:
                    held.append(lock.path)
                else:
                    lost.append(lock.path)
            if lost:
                issues.append(
                    {
                        "code": "claims_lost",
                        "severity": "action",
                        "detail": (
                            "The saved session is intact, but one or more remote claims "
                            "must be reacquired before sharing."
                        ),
                        "paths": list(lost),
                    }
                )

        hard_error = any(issue["severity"] == "error" for issue in issues)
        offline = any(issue["severity"] == "offline" for issue in issues)
        action = any(issue["severity"] == "action" for issue in issues)
        safe_to_resume = (
            branch_exists
            and not missing
            and not dirty_unclaimed
            and not offline
            and not hard_error
            and (current_branch == session.branch or not dirty)
        )
        state = (
            "attention"
            if hard_error
            else "offline"
            if offline
            else "resume_available"
            if action
            else "healthy"
        )
        return {
            "state": state,
            "detail": (
                "Protected work is active and every remote claim is held."
                if state == "healthy"
                else "Protected work can be resumed without replacing local files."
                if state == "resume_available"
                else "Protected work is preserved, but remote claims cannot be verified."
                if state == "offline"
                else "Protected work is preserved; resolve the listed repository state first."
            ),
            "safe_to_resume": safe_to_resume,
            "ready_to_share": (
                state == "healthy"
                and current_branch == session.branch
                and bool(dirty_claimed)
                and not session.shared_commit
            ),
            "source_preserved": not missing,
            "current_branch": current_branch,
            "dirty_claimed": list(dirty_claimed),
            "dirty_unclaimed": list(dirty_unclaimed),
            "claims": {
                "held": held,
                "lost": lost,
                "unknown": unknown,
            },
            "issues": issues,
        }

    def resume(self, session: WorkSession) -> WorkSession:
        """Safely return to a persisted branch and reacquire only absent claims."""

        status = self.recovery_status(session)
        if not status["safe_to_resume"]:
            first = status["issues"][0] if status["issues"] else None
            raise CollaborationError(
                first["code"] if first else "resume_blocked",
                first["detail"] if first else "this protected work session cannot be resumed safely",
            )
        if self.repo.current_branch() != session.branch:
            switched = self.repo._run("switch", session.branch, check=False)
            if switched.returncode != 0:
                raise CollaborationError(
                    "branch_failed",
                    (switched.stderr or switched.stdout).strip()
                    or f"could not switch to {session.branch}",
                )

        lost = set(status["claims"]["lost"])
        if not lost:
            return session
        recovered: list[DocumentLock] = []
        locks: list[DocumentLock] = []
        try:
            for lock in session.locks:
                if lock.path not in lost:
                    locks.append(lock)
                    continue
                reacquired = self.locks.acquire(lock.path)
                recovered.append(reacquired)
                locks.append(reacquired)
        except LockError as exc:
            cleanup = self._release_best_effort(recovered)
            detail = f"remote claims could not be recovered: {exc}"
            if cleanup:
                detail += f"; recovered-claim cleanup also failed: {'; '.join(cleanup)}"
            raise CollaborationError("claim_recovery_failed", detail) from exc
        return replace(session, locks=tuple(locks))

    def release_after_integration(self, session: WorkSession, *, integrated_commit: str) -> None:
        if not session.shared_commit:
            raise CollaborationError(
                "not_shared", "the work session has no pushed commit to integrate"
            )
        if not self.repo.has_commit(integrated_commit):
            raise CollaborationError(
                "unknown_integration", "the integrated commit is not available locally"
            )
        if not self.repo.is_ancestor(session.shared_commit, integrated_commit):
            raise CollaborationError(
                "not_integrated", "the shared work is not an ancestor of the integration commit"
            )
        failures = self._release_best_effort(session.locks)
        if failures:
            raise CollaborationError("unlock_failed", "; ".join(failures))

    def finish_after_remote_integration(self, session: WorkSession) -> str:
        """Fetch the base branch, prove the shared commit landed, then release claims."""

        if not session.shared_commit:
            raise CollaborationError(
                "not_shared", "share this work session before finishing it"
            )
        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        remote_base = self.repo._run(
            "rev-parse",
            "--verify",
            f"refs/remotes/origin/{session.base_branch}^{{commit}}",
            check=False,
        )
        if remote_base.returncode != 0:
            raise CollaborationError(
                "base_missing",
                f"remote ref is unavailable: refs/remotes/origin/{session.base_branch}",
            )
        integrated_commit = remote_base.stdout.strip()
        if not self.repo.is_clean():
            raise CollaborationError(
                "dirty_tree",
                "preserve or commit local changes before finishing this work session",
            )
        current_branch = self.repo.current_branch()
        if current_branch == session.branch:
            switched = self.repo._run("switch", session.base_branch, check=False)
            if switched.returncode != 0:
                raise CollaborationError(
                    "branch_failed",
                    (switched.stderr or switched.stdout).strip()
                    or f"could not switch to {session.base_branch}",
                )
        elif current_branch != session.base_branch:
            raise CollaborationError(
                "wrong_branch",
                f"switch to {session.branch} or {session.base_branch} before finishing",
            )
        advanced = self.repo._run("merge", "--ff-only", integrated_commit, check=False)
        if advanced.returncode != 0:
            raise CollaborationError(
                "base_changed",
                (advanced.stderr or advanced.stdout).strip()
                or f"{session.base_branch} could not advance to the integrated commit",
            )
        self.release_after_integration(session, integrated_commit=integrated_commit)
        return integrated_commit

    def _preflight_synced_base(self) -> None:
        if not self.repo.is_git_repo():
            raise CollaborationError("not_git", "the project is not inside a Git repository")
        if not self.repo.has_remote():
            raise CollaborationError("no_remote", "the project repository has no remote")
        if not self.repo.is_clean():
            raise CollaborationError(
                "dirty_tree", "preserve or commit the existing local changes before starting work"
            )
        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        if not self.repo.has_upstream():
            raise CollaborationError("no_upstream", "the current branch has no configured upstream")
        ahead_behind = self.repo.ahead_behind()
        if ahead_behind is None:
            raise CollaborationError(
                "sync_unknown", "the local and remote branch relationship could not be determined"
            )
        ahead, behind = ahead_behind
        if ahead or behind:
            raise CollaborationError(
                "not_synced",
                f"the base branch is {counted(ahead, 'commit')} ahead and "
                f"{counted(behind, 'commit')} behind",
            )

    def _normalize_documents(self, documents: Sequence[Path | str]) -> tuple[str, ...]:
        normalized: list[str] = []
        for document in documents:
            rel = self.repo._rel(document)
            if not rel or rel == ".." or rel.startswith("../"):
                raise CollaborationError(
                    "outside_repository", "every claimed document must be inside the repository"
                )
            absolute = (self.repo.root / rel).resolve()
            try:
                absolute.relative_to(self.repo.root.resolve())
            except ValueError as exc:
                raise CollaborationError(
                    "outside_repository", "every claimed document must be inside the repository"
                ) from exc
            if not absolute.is_file():
                raise CollaborationError(
                    "document_missing", f"claimed document does not exist: {rel}"
                )
            normalized.append(Path(rel).as_posix())
        if len(set(normalized)) != len(normalized):
            raise CollaborationError("duplicate_document", "a document can be claimed only once")
        return tuple(normalized)

    def _validate_branch(self, branch: str) -> None:
        branch = branch.strip()
        if not branch:
            raise CollaborationError("branch_required", "a work branch name is required")
        checked = self.repo._run("check-ref-format", "--branch", branch, check=False)
        if checked.returncode != 0:
            raise CollaborationError("invalid_branch", f"invalid work branch: {branch}")
        exists = self.repo._run(
            "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False
        )
        if exists.returncode == 0:
            raise CollaborationError("branch_exists", f"work branch already exists: {branch}")

    def _release_best_effort(self, locks: Sequence[DocumentLock]) -> list[str]:
        failures: list[str] = []
        for lock in reversed(locks):
            try:
                self.locks.release(lock)
            except LockError as exc:
                failures.append(f"{lock.path}: {exc}")
        return failures


def work_session_recovery(
    repo: GitRepo,
    locks: DocumentLockService,
    session: WorkSession,
    *,
    verify_claims: bool = True,
    trust_claims: bool = False,
) -> dict:
    """Public read-only recovery seam used by collaboration status."""

    return WorkSessionManager(repo, locks).recovery_status(
        session,
        verify_claims=verify_claims,
        trust_claims=trust_claims,
    )


class ReviewManager:
    """Review and integrate one immutable remote commit without replacing local work."""

    _EVENT_TAG_PREFIX = "refs/tags/stockroom/review"

    def __init__(
        self,
        repo: GitRepo,
        *,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ):
        self.repo = repo
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: uuid4().hex)

    def discover(self, *, branch: str, base_branch: str = "main") -> ReviewCandidate:
        self._validate_remote_branch(branch)
        self._validate_remote_branch(base_branch)
        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        remote_branch = f"refs/remotes/origin/{branch}"
        remote_base = f"refs/remotes/origin/{base_branch}"
        commit = self._resolve_commit(remote_branch, code="review_missing")
        base_commit = self._resolve_commit(remote_base, code="base_missing")
        if not self.repo.is_ancestor(base_commit, commit):
            raise CollaborationError(
                "unrelated_review",
                f"{branch} is not based on the current remote {base_branch}",
            )
        changed = self.repo._run(
            "-c",
            "core.quotepath=false",
            "diff",
            "--name-only",
            "-z",
            base_commit,
            commit,
        ).stdout
        paths = tuple(path for path in changed.split("\0") if path)
        if not paths:
            raise CollaborationError("empty_review", "the work branch has no changes to review")
        return ReviewCandidate(
            branch=branch,
            commit=commit,
            base_branch=base_branch,
            base_commit=base_commit,
            changed_paths=paths,
        )

    def list_candidates(self, *, base_branch: str = "main") -> tuple[ReviewListing, ...]:
        """List pushed ``work/*`` branches without changing the working copy."""

        self._validate_remote_branch(base_branch)
        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        remote_base = f"refs/remotes/origin/{base_branch}"
        base_commit = self._resolve_commit(remote_base, code="base_missing")
        self._fetch_review_event_tags()
        refs = self.repo._run(
            "for-each-ref",
            "--format=%(refname)",
            "refs/remotes/origin/work/",
        ).stdout.splitlines()
        listings: list[ReviewListing] = []
        prefix = "refs/remotes/origin/"
        for ref in sorted(value.strip() for value in refs if value.strip()):
            branch = ref.removeprefix(prefix)
            commit = self._resolve_commit(ref, code="review_missing")
            fork = self.repo._run("merge-base", base_commit, commit, check=False)
            fork_commit = fork.stdout.strip() if fork.returncode == 0 else ""
            if not fork_commit:
                listings.append(
                    ReviewListing(
                        branch=branch,
                        commit=commit,
                        base_branch=base_branch,
                        base_commit=base_commit,
                        fork_commit="",
                        changed_paths=(),
                        commit_count=0,
                        ready=False,
                        blocked_reason=f"{branch} does not share history with {base_branch}",
                    )
                )
                continue
            changed = self.repo._run(
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                "-z",
                fork_commit,
                commit,
            ).stdout
            paths = tuple(path for path in changed.split("\0") if path)
            if not paths:
                continue
            ready = fork_commit == base_commit
            listings.append(
                ReviewListing(
                    branch=branch,
                    commit=commit,
                    base_branch=base_branch,
                    base_commit=base_commit,
                    fork_commit=fork_commit,
                    changed_paths=paths,
                    commit_count=self.repo.count_commits(fork_commit, commit),
                    ready=ready,
                    blocked_reason=(
                        ""
                        if ready
                        else f"{base_branch} advanced after this work branch started"
                    ),
                    events=self._events_for_commit(
                        commit,
                        branch=branch,
                        base_branch=base_branch,
                        fork_commit=fork_commit,
                    ),
                )
            )
        return tuple(listings)

    def request_changes(
        self,
        candidate: ReviewCandidate,
        *,
        reviewer: str,
        message: str,
    ) -> ReviewEvent:
        """Append one immutable change request without touching the working copy."""

        reviewer = reviewer.strip()
        message = message.strip()
        if not reviewer:
            raise CollaborationError("reviewer_required", "name the reviewer requesting changes")
        if len(reviewer) > 120:
            raise CollaborationError(
                "reviewer_too_long", "the reviewer name must be 120 characters or fewer"
            )
        if not message:
            raise CollaborationError(
                "review_message_required", "describe the changes that are required"
            )
        if len(message) > 2_000:
            raise CollaborationError(
                "review_message_too_long",
                "the change request must be 2,000 characters or fewer",
            )

        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        current_commit = self._resolve_commit(
            f"refs/remotes/origin/{candidate.branch}",
            code="review_missing",
        )
        current_base = self._resolve_commit(
            f"refs/remotes/origin/{candidate.base_branch}",
            code="base_missing",
        )
        if current_commit != candidate.commit:
            raise CollaborationError(
                "review_changed", "the work branch changed after it was reviewed"
            )
        if current_base != candidate.base_commit:
            raise CollaborationError(
                "base_changed", "the shared branch changed after this review began"
            )

        event_id = self._new_id().strip().lower()
        if not event_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in event_id
        ):
            raise CollaborationError(
                "review_event_id_invalid", "the review event identity is invalid"
            )
        created = self._now()
        event = ReviewEvent(
            id=event_id,
            kind="changes_requested",
            branch=candidate.branch,
            commit=candidate.commit,
            base_branch=candidate.base_branch,
            base_commit=candidate.base_commit,
            reviewer=reviewer,
            message=message,
            created_at=created.isoformat().replace("+00:00", "Z"),
        )
        tag_name = f"stockroom/review/{candidate.commit}/{event.id}"
        tag_ref = f"refs/tags/{tag_name}"
        payload = json.dumps(asdict(event), sort_keys=True, separators=(",", ":"))
        self.repo._set_test_identity_if_missing()
        tagged = self.repo._run(
            "tag",
            "-a",
            tag_name,
            candidate.commit,
            "-F",
            "-",
            input_text=f"{payload}\n",
            check=False,
        )
        if tagged.returncode != 0:
            raise CollaborationError(
                "review_event_write_failed",
                (tagged.stderr or tagged.stdout).strip()
                or "the repository review event could not be created",
            )
        pushed = self.repo._run(
            "push",
            "origin",
            f"{tag_ref}:{tag_ref}",
            check=False,
        )
        if pushed.returncode != 0:
            cleanup = self.repo._run("tag", "-d", tag_name, check=False)
            cleanup_detail = (
                ""
                if cleanup.returncode == 0
                else "; the unshared local event tag also could not be removed"
            )
            detail = (
                (pushed.stderr or pushed.stdout).strip()
                or "the repository review event could not be shared"
            )
            raise CollaborationError(
                "review_event_push_failed",
                detail + cleanup_detail,
            )
        return event

    def inspect(self, candidate: ReviewCandidate, inspect: Callable[[Path], None]) -> None:
        """Run a readonly inspector against a detached disposable worktree."""
        with TemporaryDirectory(prefix="stockroom-review-") as temp:
            worktree = Path(temp) / "checkout"
            added = self.repo._run(
                "worktree", "add", "--detach", str(worktree), candidate.commit, check=False
            )
            if added.returncode != 0:
                raise CollaborationError(
                    "review_worktree_failed",
                    (added.stderr or added.stdout).strip()
                    or "the review worktree could not be created",
                )
            try:
                inspect(worktree)
            finally:
                removed = self.repo._run(
                    "worktree", "remove", "--force", str(worktree), check=False
                )
                if removed.returncode != 0:
                    raise CollaborationError(
                        "review_cleanup_failed",
                        (removed.stderr or removed.stdout).strip()
                        or "the review worktree could not be removed",
                    )

    def approve_fast_forward(self, candidate: ReviewCandidate) -> str:
        """Integrate exactly the reviewed commit; a changed branch or base must be reviewed again."""
        if not self.repo.is_clean():
            raise CollaborationError(
                "dirty_tree", "preserve or commit local changes before approving a review"
            )
        if self.repo.current_branch() != candidate.base_branch:
            raise CollaborationError(
                "wrong_branch",
                f"switch to {candidate.base_branch} before approving this review",
            )
        ok, reason = self.repo.fetch()
        if not ok:
            raise CollaborationError("fetch_failed", reason or "the remote could not be fetched")
        current_commit = self._resolve_commit(
            f"refs/remotes/origin/{candidate.branch}", code="review_missing"
        )
        current_base = self._resolve_commit(
            f"refs/remotes/origin/{candidate.base_branch}", code="base_missing"
        )
        if current_commit != candidate.commit:
            raise CollaborationError(
                "review_changed", "the work branch changed after it was reviewed"
            )
        if current_base != candidate.base_commit or self.repo.head() != candidate.base_commit:
            raise CollaborationError(
                "base_changed", "the shared branch changed after this review began"
            )
        merged = self.repo._run("merge", "--ff-only", candidate.commit, check=False)
        if merged.returncode != 0:
            raise CollaborationError(
                "merge_failed",
                (merged.stderr or merged.stdout).strip()
                or "the reviewed commit could not be fast-forwarded",
            )
        pushed = self.repo.push()
        if not pushed.ok:
            raise CollaborationError(
                "push_failed",
                pushed.reason
                or "the remote changed while approval was being integrated; local work is preserved",
            )
        return self.repo.head()

    def _resolve_commit(self, ref: str, *, code: str) -> str:
        resolved = self.repo._run("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if resolved.returncode != 0:
            raise CollaborationError(code, f"remote ref is unavailable: {ref}")
        return resolved.stdout.strip()

    def _fetch_review_event_tags(self) -> None:
        pattern = f"{self._EVENT_TAG_PREFIX}/*"
        remote = self.repo._run(
            "ls-remote",
            "--tags",
            "--refs",
            "origin",
            pattern,
            check=False,
        )
        if remote.returncode != 0:
            raise CollaborationError(
                "review_event_fetch_failed",
                (remote.stderr or remote.stdout).strip()
                or "repository review events could not be discovered",
            )
        if not remote.stdout.strip():
            return
        fetched = self.repo._run(
            "fetch",
            "origin",
            f"{pattern}:{pattern}",
            check=False,
        )
        if fetched.returncode != 0:
            raise CollaborationError(
                "review_event_fetch_failed",
                (fetched.stderr or fetched.stdout).strip()
                or "repository review events could not be fetched",
            )

    def _events_for_commit(
        self,
        commit: str,
        *,
        branch: str,
        base_branch: str,
        fork_commit: str,
    ) -> tuple[ReviewEvent, ...]:
        prefix = f"{self._EVENT_TAG_PREFIX}/{commit}/"
        refs = self.repo._run(
            "for-each-ref",
            "--format=%(refname)",
            prefix,
        ).stdout.splitlines()
        events: list[ReviewEvent] = []
        for ref in sorted(value.strip() for value in refs if value.strip()):
            target = self._resolve_commit(ref, code="review_event_invalid")
            contents = self.repo._run(
                "for-each-ref",
                "--format=%(contents)",
                ref,
                check=False,
            )
            try:
                payload = json.loads(contents.stdout.strip())
                event = ReviewEvent(**payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise CollaborationError(
                    "review_event_invalid",
                    f"repository review event is malformed: {ref}",
                ) from exc
            event_id = ref.rsplit("/", 1)[-1]
            string_values = tuple(asdict(event).values())
            if (
                contents.returncode != 0
                or not all(isinstance(value, str) for value in string_values)
                or event.id != event_id
                or event.kind != "changes_requested"
                or target != commit
                or event.commit != commit
                or event.branch != branch
                or event.base_branch != base_branch
                or event.base_commit != fork_commit
                or not event.reviewer.strip()
                or not event.message.strip()
            ):
                raise CollaborationError(
                    "review_event_invalid",
                    f"repository review event does not match its review commit: {ref}",
                )
            events.append(event)
        return tuple(sorted(events, key=lambda event: (event.created_at, event.id)))

    def _validate_remote_branch(self, branch: str) -> None:
        checked = self.repo._run("check-ref-format", "--branch", branch, check=False)
        if checked.returncode != 0:
            raise CollaborationError("invalid_branch", f"invalid branch: {branch}")
