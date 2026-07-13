"""Thin wrapper over the git binary (subprocess), mirroring the KiCadCli shape.

Only the operations Stockroom needs: init/clone, scoped commit, status,
fast-forward-only pull, push, per-path log, and a rollback primitive that git
gives us for free (git is the undo system, spec section 9). A bundled portable
git or dulwich fallback for machines without git is an M5 launcher concern; the
backend requires git on PATH (present in dev and CI).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass
class Commit:
    sha: str
    subject: str
    author: str
    iso_date: str


@dataclass
class PullResult:
    ok: bool
    updated: bool
    reason: str


@dataclass
class PushResult:
    ok: bool
    reason: str


class GitRepo:
    def __init__(self, root: Path, git_binary: str | None = None):
        resolved = shutil.which(git_binary or "git")
        if resolved is None:
            raise GitError(f"git not found: {git_binary or 'git'}")
        self.git = resolved
        self.root = Path(root)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.git, "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    def _set_test_identity_if_missing(self) -> None:
        # CI and fresh dev machines may have no global identity. Set a local one
        # so commits never fail; a real machine's global identity still wins.
        if self._run("config", "user.email", check=False).returncode != 0:
            self._run("config", "user.email", "stockroom@localhost")
            self._run("config", "user.name", "Stockroom")

    def init(self, *, bare: bool = False) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        args = ["init", "-b", "main"]
        if bare:
            args.append("--bare")
        subprocess.run([self.git, "-C", str(self.root), *args], capture_output=True, text=True, check=True)
        if not bare:
            self._set_test_identity_if_missing()

    def clone_from(self, origin: Path) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [self.git, "clone", str(origin), str(self.root)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise GitError(f"git clone failed: {proc.stderr.strip()}")
        self._set_test_identity_if_missing()

    def is_git_repo(self) -> bool:
        return self._run("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def head(self) -> str:
        proc = self._run("rev-parse", "HEAD", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def status_porcelain(self) -> list[str]:
        out = self._run("status", "--porcelain").stdout
        return [line for line in out.splitlines() if line.strip()]

    def is_clean(self, paths: list[Path] | None = None) -> bool:
        args = ["status", "--porcelain"]
        if paths:
            args.append("--")
            args += [str(p) for p in paths]
        return not [line for line in self._run(*args).stdout.splitlines() if line.strip()]

    def commit(self, message: str, paths: list[Path]) -> str:
        if not message.strip():
            raise GitError("commit message must not be empty")
        # -A so a scoped commit also stages DELETIONS of tracked files that were
        # removed from the working tree (profile/part deletion), not just adds/mods.
        self._run("add", "-A", "--", *[str(p) for p in paths])
        # nothing staged among these paths => no-op, return current head.
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.head()
        self._run("commit", "-m", message, "--only", "--", *[str(p) for p in paths])
        return self.head()

    def log_paths(self, paths: list[Path], max_count: int = 50) -> list[Commit]:
        fmt = "%H%x1f%s%x1f%an%x1f%aI"
        out = self._run(
            "log", f"--max-count={max_count}", f"--pretty=format:{fmt}",
            "--", *[str(p) for p in paths],
        ).stdout
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, subject, author, date = line.split("\x1f")
            commits.append(Commit(sha=sha, subject=subject, author=author, iso_date=date))
        return commits

    def restore_paths(self, paths: list[Path]) -> None:
        """Roll back exactly these paths: revert tracked modifications to HEAD,
        and delete anything untracked that was created. This is the transaction
        rollback (spec section 9)."""
        for p in paths:
            rel = str(p)
            tracked = self._run("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0
            if tracked:
                self._run("checkout", "HEAD", "--", rel, check=False)
            else:
                path = Path(p)
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()

    def add_remote(self, name: str, url: str) -> None:
        self._run("remote", "add", name, url)

    def set_upstream(self, branch: str, remote: str) -> None:
        self._run("branch", f"--set-upstream-to={remote}/{branch}", branch)

    def ahead_behind(self) -> tuple[int, int] | None:
        proc = self._run("rev-list", "--left-right", "--count", "@{upstream}...HEAD", check=False)
        if proc.returncode != 0:
            return None
        behind, ahead = proc.stdout.split()
        return int(ahead), int(behind)

    def pull_ff(self) -> PullResult:
        before = self.head()
        proc = self._run("pull", "--ff-only", check=False)
        if proc.returncode != 0:
            text = (proc.stderr + proc.stdout).lower()
            reason = "not fast-forwardable (diverged)" if (
                "fast-forward" in text or "diverg" in text or "non-fast" in text
            ) else proc.stderr.strip()
            return PullResult(ok=False, updated=False, reason=reason)
        return PullResult(ok=True, updated=self.head() != before, reason="")

    def push(self) -> PushResult:
        proc = self._run("push", check=False)
        if proc.returncode != 0:
            return PushResult(ok=False, reason=proc.stderr.strip())
        return PushResult(ok=True, reason="")
