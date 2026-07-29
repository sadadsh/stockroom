"""Integrity-checked, side-by-side application release staging.

The live checkout may contain valuable in-progress work.  An application update
therefore never checks out, resets, or rebases that working tree.  A candidate is
materialized as a detached Git worktree beneath Stockroom's private release
directory and is verified against the exact fetched commit before and after
dependency preparation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from stockroom.vcs.repo import GitError, GitRepo

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
_DEFAULT_RUNTIME_FILES = (
    "pyproject.toml",
    "uv.lock",
    "app/backend/stockroom",
    "app/frontend-dist/index.html",
)


class CandidateIntegrityError(RuntimeError):
    """A staged release did not match its claimed Git commit."""


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    revision: str
    root: Path
    tree_digest: str


class GitReleaseStore:
    """Create and re-verify detached release worktrees without touching the live tree."""

    def __init__(
        self,
        repo: GitRepo,
        releases_root: Path,
        *,
        required_runtime_files: tuple[str, ...] = _DEFAULT_RUNTIME_FILES,
    ) -> None:
        self.repo = repo
        self.root = Path(releases_root).resolve()
        self.revisions = self.root / "revisions"
        self.manifests = self.root / "manifests"
        self.required_runtime_files = required_runtime_files

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True):
        proc = subprocess.run(
            [self.repo.git, "-C", str(cwd or self.repo.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=120.0,
        )
        if check and proc.returncode != 0:
            raise CandidateIntegrityError(
                f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}"
            )
        return proc

    def _candidate_path(self, revision: str) -> Path:
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision.lower()):
            raise CandidateIntegrityError("candidate revision must be an exact 40-character SHA")
        return self.revisions / revision.lower()

    def _assert_owned(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.revisions.resolve())
        except ValueError as exc:
            raise CandidateIntegrityError(
                "refusing to alter a path outside the release store"
            ) from exc
        if resolved == self.revisions.resolve():
            raise CandidateIntegrityError("refusing to alter the release-store root")
        return resolved

    def _discard_candidate(self, path: Path) -> None:
        """Remove one known-invalid candidate, never the live checkout or release root."""
        owned = self._assert_owned(path)
        self._git("worktree", "remove", "--force", str(owned), check=False)
        if owned.exists():
            shutil.rmtree(owned)
        self._git("worktree", "prune", check=False)

    def _tree_digest(self, candidate_root: Path, revision: str) -> str:
        tree = self._git("ls-tree", "-r", "--full-tree", revision).stdout.encode("utf-8")
        digest = hashlib.sha256()
        digest.update(revision.encode("ascii"))
        digest.update(b"\0")
        digest.update(tree)
        return digest.hexdigest()

    def verify(
        self, candidate: ReleaseCandidate | Path, revision: str | None = None
    ) -> ReleaseCandidate:
        root = candidate.root if isinstance(candidate, ReleaseCandidate) else Path(candidate)
        expected = revision or (
            candidate.revision if isinstance(candidate, ReleaseCandidate) else root.name
        )
        root = self._assert_owned(root)
        actual = self._git("rev-parse", "HEAD", cwd=root).stdout.strip()
        if actual.casefold() != expected.casefold():
            raise CandidateIntegrityError(
                f"candidate revision mismatch: expected {expected[:12]}, found {actual[:12]}"
            )
        # Both index and working tree must still be exactly the claimed commit.  This
        # catches dependency tooling or a partial copy modifying tracked runtime bytes.
        if self._git("diff-index", "--quiet", expected, "--", cwd=root, check=False).returncode:
            raise CandidateIntegrityError("candidate tracked files differ from the claimed commit")
        for relative in self.required_runtime_files:
            if not (root / relative).exists():
                raise CandidateIntegrityError(f"candidate is missing runtime asset: {relative}")
        tree_digest = self._tree_digest(root, expected)
        return ReleaseCandidate(expected.lower(), root, tree_digest)

    def stage(self, revision: str) -> ReleaseCandidate:
        """Materialize and verify ``revision`` without changing the live working tree."""
        revision = revision.strip().lower()
        if not self.repo.has_commit(revision):
            raise CandidateIntegrityError("the fetched candidate commit is unavailable locally")
        path = self._candidate_path(revision)
        self.revisions.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                return self.verify(path, revision)
            except CandidateIntegrityError:
                self._discard_candidate(path)
        self._git("worktree", "add", "--detach", str(path), revision)
        try:
            candidate = self.verify(path, revision)
        except Exception:
            self._discard_candidate(path)
            raise
        manifest = {
            "revision": candidate.revision,
            "tree_digest": candidate.tree_digest,
            "staged_at": time.time(),
        }
        self._write_json_atomic(self.manifests / f"{revision}.json", manifest)
        return candidate

    def prune(self, keep_revisions: set[str]) -> None:
        """Bound release storage to revisions still serving as active/fallback."""
        keep = {revision.casefold() for revision in keep_revisions if revision}
        if not self.revisions.exists():
            return
        for path in list(self.revisions.iterdir()):
            if not path.is_dir() or path.name.casefold() in keep:
                continue
            self._discard_candidate(path)
            manifest = self.manifests / f"{path.name}.json"
            if manifest.is_file():
                manifest.unlink()

    def promote(self, candidate: ReleaseCandidate, base_url: str) -> None:
        """Atomically record the health-checked active release.

        The pointer is observational and recoverable; process adoption happens
        first, so a crash can never advertise an unstarted candidate as active.
        """
        verified = self.verify(candidate)
        self._write_json_atomic(
            self.root / "active.json",
            {
                "revision": verified.revision,
                "tree_digest": verified.tree_digest,
                "base_url": base_url,
                "activated_at": time.time(),
            },
        )

    def active_candidate(self) -> ReleaseCandidate | None:
        """Return the persisted active candidate only when it still passes integrity checks."""
        path = self.root / "active.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            revision = str(document["revision"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if revision == self.repo.head():
            return None
        candidate_path = self._candidate_path(revision)
        if not candidate_path.exists():
            return None
        return self.verify(candidate_path, revision)

    def record_rollback(self, revision: str, base_url: str, failed_revision: str) -> None:
        self._write_json_atomic(
            self.root / "active.json",
            {
                "revision": revision,
                "base_url": base_url,
                "rolled_back_from": failed_revision,
                "activated_at": time.time(),
            },
        )

    @property
    def convergence_status_path(self) -> Path:
        return self.root / "convergence.json"

    def write_convergence_status(self, payload: Mapping[str, object]) -> None:
        self._write_json_atomic(self.convergence_status_path, payload)

    @property
    def checkout_inventory_path(self) -> Path:
        return self.root / "checkout-inventory.json"

    def write_checkout_inventory(self, payload: Mapping[str, object]) -> None:
        self._write_json_atomic(self.checkout_inventory_path, payload)

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
