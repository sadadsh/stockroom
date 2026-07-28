"""Server-backed document locks for collaborative EDA repositories.

Git is the source synchronization system, while Git LFS supplies the remote locking
protocol. Native design documents do not need to be stored as LFS objects to be
claimed: Stockroom treats the remote lock as an edit lease and verifies it before a
scoped commit. Content filtering remains a separate, explicitly qualified policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stockroom.vcs import lfs
from stockroom.vcs.repo import GitRepo


class LockError(RuntimeError):
    """A remote lock operation failed without changing project source."""


@dataclass(frozen=True)
class DocumentLock:
    id: str
    path: str
    owner: str
    locked_at: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> "DocumentLock":
        owner = value.get("owner") or {}
        return cls(
            id=str(value.get("id") or ""),
            path=Path(str(value.get("path") or "")).as_posix(),
            owner=str(owner.get("name") or value.get("ownername") or ""),
            locked_at=str(value.get("locked_at") or ""),
        )


class GitLfsLockService:
    """Thin, testable use of the installed ``git lfs`` locking API."""

    def __init__(self, repo: GitRepo):
        self.repo = repo

    def available(self) -> tuple[bool, str]:
        return lfs.locking_probe(self.repo)

    def list(self) -> tuple[DocumentLock, ...]:
        proc = self.repo._run("lfs", "locks", "--json", check=False)
        if proc.returncode != 0:
            raise LockError((proc.stderr or proc.stdout).strip() or "could not list document locks")
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise LockError("the lock server returned invalid JSON") from exc
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("locks")
        else:
            rows = None
        if not isinstance(rows, list):
            raise LockError("the lock server response did not contain a lock list")
        locks = tuple(DocumentLock.from_dict(row) for row in rows if isinstance(row, dict))
        if any(not lock.id or not lock.path for lock in locks):
            raise LockError("the lock server returned an incomplete lock")
        return locks

    def acquire(self, path: Path | str) -> DocumentLock:
        rel = self.repo._rel(path)
        if not rel or rel.startswith("../") or rel == "..":
            raise LockError("document lock path must be inside the repository")
        proc = self.repo._run("lfs", "lock", "--json", rel, check=False)
        if proc.returncode != 0:
            raise LockError((proc.stderr or proc.stdout).strip() or f"could not lock {rel}")
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise LockError("the lock server returned invalid JSON") from exc
        row = payload.get("lock") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and not isinstance(row, dict):
            row = payload
        if isinstance(payload, list) and len(payload) == 1:
            row = payload[0]
        if not isinstance(row, dict):
            raise LockError("the lock server response did not contain the acquired lock")
        lock = DocumentLock.from_dict(row)
        if not lock.id or lock.path != Path(rel).as_posix():
            raise LockError("the lock server returned the wrong document lock")
        return lock

    def owns(self, expected: DocumentLock) -> bool:
        return any(lock.id == expected.id and lock.path == expected.path for lock in self.list())

    def release(self, lock: DocumentLock, *, force: bool = False) -> None:
        args = ["lfs", "unlock", "--id", lock.id]
        if force:
            args.append("--force")
        proc = self.repo._run(*args, check=False)
        if proc.returncode != 0:
            raise LockError((proc.stderr or proc.stdout).strip() or f"could not unlock {lock.path}")
