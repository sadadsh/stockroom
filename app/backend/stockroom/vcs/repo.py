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


def _parse_porcelain_z(out: str) -> list[str]:
    """Split `git status --porcelain -z` output into repo-relative paths. Each record
    is `XY <path>\\0`; a rename/copy adds the ORIGINAL path as the next NUL field, and
    both sides are returned so the deletion of the old name is committed alongside the
    new one."""
    fields = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        if not entry:
            i += 1
            continue
        xy = entry[:2]
        paths.append(entry[3:])  # skip the 2-char status + its trailing space
        if xy[:1] in ("R", "C") or (len(xy) > 1 and xy[1] in ("R", "C")):
            i += 1
            if i < len(fields) and fields[i]:
                paths.append(fields[i])  # the rename/copy source
        i += 1
    return paths


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

    def dirty_paths(self, scope: Path | None = None) -> list[Path]:
        """Absolute paths of every uncommitted change, optionally scoped to a subtree.

        Uses ``-z`` (NUL-terminated, never octal-quoted or truncated) so non-ASCII and
        special-character paths survive intact, and yields BOTH sides of a rename so a
        caller committing these paths stages the deletion of the old name too. Scoping
        matters because one git repo backs every profile subdirectory, so an unscoped
        status would leak another profile's in-progress edits."""
        args = ["-c", "core.quotepath=false", "status", "--porcelain", "-z"]
        if scope is not None:
            args += ["--", str(scope)]
        out = self._run(*args).stdout
        return [self.root / rel for rel in _parse_porcelain_z(out)]

    def is_clean(self, paths: list[Path] | None = None) -> bool:
        args = ["status", "--porcelain"]
        if paths:
            args.append("--")
            args += [str(p) for p in paths]
        return not [line for line in self._run(*args).stdout.splitlines() if line.strip()]

    def commit(self, message: str, paths: list[Path]) -> str:
        if not message.strip():
            raise GitError("commit message must not be empty")
        # -A so a scoped commit also stages DELETIONS of tracked files that were removed
        # from the working tree (profile/part deletion), not just adds/mods. Only add
        # paths git can still see (present on disk, or still tracked in the index): a path
        # that is neither — e.g. the source of a rename already staged by `git mv` — would
        # abort `git add` with "did not match any files". Its change is already staged, so
        # --only below still carries it into the commit.
        addable = [p for p in paths if Path(p).exists() or self._is_tracked(p)]
        if addable:
            self._run("add", "-A", "--", *[str(p) for p in addable])
        # nothing staged among these paths => no-op, return current head.
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.head()
        self._run("commit", "-m", message, "--only", "--", *[str(p) for p in paths])
        return self.head()

    def _is_tracked(self, path: Path) -> bool:
        return (
            self._run("ls-files", "--error-unmatch", "--", str(path), check=False).returncode == 0
        )

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

    def _rel(self, path: Path | str) -> str:
        """Repo-relative POSIX path for a `<rev>:<path>` pathspec. git addresses blobs
        by a path relative to the repo root with forward slashes on every platform; an
        absolute path under root is relativised, a path already relative is returned as
        POSIX unchanged."""
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.relative_to(self.root)
            except ValueError:
                pass  # outside the tree: let git report it as a miss
        return p.as_posix()

    def show_file(self, rev: str, path: Path | str) -> str | None:
        """The content of `path` at revision `rev`, read straight from the git blob with
        no working-tree checkout (spec section 9). Returns None when the path does not
        exist at that rev (e.g. the part was added later), so a diff caller can treat an
        absent side as empty rather than crash. A malformed rev raises GitError."""
        proc = self._run("show", f"{rev}:{self._rel(path)}", check=False)
        if proc.returncode == 0:
            return proc.stdout
        err = proc.stderr.lower()
        # a path absent at this rev is an expected "miss" (the part was added later), not
        # an error; git phrases it a few ways across versions. Anything else (a bad rev,
        # a corrupt object) is a real failure and raises.
        miss = (
            "does not exist in" in err
            or "exists on disk, but not in" in err
            or "does not exist" in err  # "...(neither on disk nor in the index)"
        )
        if miss:
            return None
        raise GitError(f"git show {rev}:{self._rel(path)} failed: {proc.stderr.strip()}")

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

    def revert(self, sha: str) -> str:
        """Revert commit `sha` as a NEW commit (git-native, non-destructive undo, spec section 9):
        history is preserved and any later commits stand. On a conflict (a later commit changed the
        same lines), abort the half-applied revert and raise GitError so the caller reports honestly
        rather than leaving the tree in a conflicted state. Returns the new HEAD."""
        self._set_test_identity_if_missing()
        proc = self._run("revert", "--no-edit", sha, check=False)
        if proc.returncode != 0:
            self._run("revert", "--abort", check=False)  # best-effort cleanup of a conflicted revert
            raise GitError(f"git revert {sha} failed: {(proc.stderr or proc.stdout).strip()}")
        return self.head()

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

    def has_remote(self) -> bool:
        return bool(self._run("remote", check=False).stdout.strip())

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def has_upstream(self) -> bool:
        return (
            self._run(
                "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False
            ).returncode
            == 0
        )

    def push(self) -> PushResult:
        # first push on a branch with no upstream sets it (-u origin <branch>);
        # afterwards a bare push follows the configured upstream.
        if self.has_upstream():
            proc = self._run("push", check=False)
        else:
            proc = self._run("push", "-u", "origin", self.current_branch(), check=False)
        if proc.returncode != 0:
            return PushResult(ok=False, reason=proc.stderr.strip())
        return PushResult(ok=True, reason="")
