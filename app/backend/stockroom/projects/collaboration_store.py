"""Machine-local persistence for active project work sessions.

Remote Git LFS locks remain authoritative. This store preserves the session facts
needed to resume Stockroom after a process restart: base commit, branch, claimed
documents, and the exact remote lock identities. It never stores credentials.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from stockroom.projects.collaboration import WorkSession
from stockroom.vcs.locks import DocumentLock

_LOCK = threading.RLock()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _session_payload(session: WorkSession) -> dict:
    return {
        "schema_version": 1,
        "id": session.id,
        "owner": session.owner,
        "branch": session.branch,
        "base_branch": session.base_branch,
        "base_commit": session.base_commit,
        "documents": list(session.documents),
        "locks": [asdict(lock) for lock in session.locks],
        "started_at": session.started_at,
        "shared_commit": session.shared_commit,
    }


def _load_session(payload: dict) -> WorkSession:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported work session record")
    locks = tuple(
        DocumentLock(
            id=str(lock["id"]),
            path=str(lock["path"]),
            owner=str(lock.get("owner") or ""),
            locked_at=str(lock.get("locked_at") or ""),
        )
        for lock in payload.get("locks", [])
    )
    return WorkSession(
        id=str(payload["id"]),
        owner=str(payload["owner"]),
        branch=str(payload["branch"]),
        base_branch=str(payload["base_branch"]),
        base_commit=str(payload["base_commit"]),
        documents=tuple(str(path) for path in payload.get("documents", [])),
        locks=locks,
        started_at=str(payload["started_at"]),
        shared_commit=str(payload.get("shared_commit") or ""),
    )


class WorkSessionStore:
    """One recoverable active work session per registered project."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def active(self, project_id: str) -> WorkSession | None:
        path = self._path(project_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid work session record")
        return _load_session(payload)

    def save(self, project_id: str, session: WorkSession) -> WorkSession:
        with _LOCK:
            current = self.active(project_id)
            if current is not None and current.id != session.id:
                raise ValueError("this project already has an active work session")
            _atomic_json(self._path(project_id), _session_payload(session))
        return session

    def clear(self, project_id: str, session_id: str) -> None:
        with _LOCK:
            current = self.active(project_id)
            if current is None:
                return
            if current.id != session_id:
                raise ValueError("the active work session changed")
            self._path(project_id).unlink()

    def _path(self, project_id: str) -> Path:
        if not project_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in project_id
        ):
            raise ValueError("invalid project id")
        return self.root / f"{project_id}.json"
