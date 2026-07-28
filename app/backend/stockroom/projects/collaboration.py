"""A safe work-session boundary for two people editing one EDA Git repository."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
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


class ReviewManager:
    """Review and integrate one immutable remote commit without replacing local work."""

    def __init__(self, repo: GitRepo):
        self.repo = repo

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

    def _validate_remote_branch(self, branch: str) -> None:
        checked = self.repo._run("check-ref-format", "--branch", branch, check=False)
        if checked.returncode != 0:
            raise CollaborationError("invalid_branch", f"invalid branch: {branch}")
