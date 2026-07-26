"""Git-backed atomic mutation transaction.

Every library mutation stages its file operations, validates them (re-parse each
written KiCad file and JSON record), then commits as one scoped git commit. If
anything fails, git restores the touched paths and the mutation leaves zero
trace (spec sections 5 and 9). Git is the commit boundary and the undo system.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from stockroom.sexp.document import SexpDocument
from stockroom.vcs.repo import GitRepo

_SEXP_SUFFIXES = {".kicad_sym", ".kicad_mod", ".kicad_sch", ".kicad_pcb"}
_SEXP_TABLE_NAMES = {"sym-lib-table", "fp-lib-table"}


class TransactionError(Exception):
    pass


class Transaction:
    def __init__(self, repo: GitRepo):
        self.repo = repo
        self._paths: list[Path] = []
        self._dirs: list[Path] = []
        self._committed = False
        self._lock: threading.RLock | None = None

    def track(self, *paths: Path) -> None:
        for p in paths:
            path = Path(p)
            if path not in self._paths:
                self._paths.append(path)

    def track_dir(self, *dirs: Path) -> None:
        """Record a directory this transaction may freshly create so rollback prunes it
        if it ends up empty. Git cannot track an empty directory, so restore_paths alone
        would leave a brand-new category's .pretty dir behind (the zero-trace contract)."""
        for d in dirs:
            path = Path(d)
            if path not in self._dirs:
                self._dirs.append(path)

    def validate(self) -> None:
        for p in self._paths:
            if not p.exists():
                continue  # a removal is a legitimate tracked change
            if p.suffix in _SEXP_SUFFIXES or p.name in _SEXP_TABLE_NAMES:
                try:
                    SexpDocument.load(p)
                except Exception as exc:
                    raise TransactionError(f"invalid KiCad file {p.name}: {exc}") from exc
            elif p.suffix in (".json", ".kicad_pro"):
                # A .kicad_pro is JSON: a malformed one must abort + roll back exactly
                # like a bad .json record, never commit a project file KiCad can't read.
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise TransactionError(f"invalid JSON {p.name}: {exc}") from exc

    def commit(self, message: str) -> str:
        self.validate()
        sha = self.repo.commit(message, self._paths)
        self._committed = True
        return sha

    def commit_staged(self, message: str) -> str:
        """Commit what the body of this transaction STAGED, rather than re-deriving the commit from
        the tracked paths' working-tree contents. Needed when a change cannot be expressed as "the
        current state of these files": staging a `git rm --cached` while deliberately keeping the
        file on disk is one (see GitRepo.commit_staged). Rollback is unchanged: the same tracked
        paths are restored if this is never reached."""
        self.validate()
        sha = self.repo.commit_staged(message)
        self._committed = True
        return sha

    def __enter__(self) -> "Transaction":
        # The whole window is exclusive, not just the commit. Locking only `GitRepo.commit` would
        # stop two commits colliding on `.git/index.lock` and still let two transactions interleave
        # their WRITES - so one could stage a file the other had already half-rewritten, or roll
        # back paths the other had just committed. The atomicity contract is per transaction, so
        # the lock has to span the transaction. Re-entrant, so `commit` taking it again is free.
        self._lock = self.repo._write_lock()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self._body(exc_type, exc, tb)
        finally:
            # Released even if rollback itself raises: leaking this lock would wedge every later
            # write to the repo with no error to explain it.
            if self._lock is not None:
                self._lock.release()
                self._lock = None
        return False  # never suppress exceptions

    def _body(self, exc_type, exc, tb) -> None:
        if not self._committed:
            self.repo.restore_paths(self._paths)
            # prune freshly-created dirs that rollback left empty (deepest first), so a
            # failed mutation leaves zero trace even for a brand-new category.
            for d in sorted(self._dirs, key=lambda p: len(p.parts), reverse=True):
                try:
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                except OSError:
                    pass
