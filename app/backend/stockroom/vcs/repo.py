"""Thin wrapper over the git binary (subprocess), mirroring the KiCadCli shape.

Only the operations Stockroom needs: init/clone, scoped commit, status,
fast-forward-only pull, push, per-path log, and a rollback primitive that git
gives us for free (git is the undo system, spec section 9). A bundled portable
git or dulwich fallback for machines without git is an M5 launcher concern; the
backend requires git on PATH (present in dev and CI).
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

# CREATE_NO_WINDOW on Windows so a git subprocess never flashes a console window (the frozen
# exe is windowed); a harmless 0 on POSIX. Mirrors kicad/checks.py's _NO_WINDOW.
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

# ONE write lock per repository, shared by every GitRepo object pointing at it.
#
# Git takes an exclusive `.git/index.lock` for the duration of any index write, so two of our own
# writes arriving together fail with "Unable to create '.git/index.lock': File exists" - a hard
# error surfaced to the user as a failed mutation. That is not exotic here: FastAPI runs sync route
# handlers in a threadpool, so Prepare, Sync Hygiene, Library Pin and Restore can all be in flight
# at once against one project, and every library mutation shares the library repo the same way.
#
# Keyed by RESOLVED root, so two GitRepo instances for the same repo share a lock while two
# different repos still write in parallel (the library must not block a project).
#
# RLock, not Lock: `Transaction` holds this for its whole stage/validate/commit window and then
# calls `repo.commit`, which takes it again on the same thread. A plain Lock would deadlock the app
# on its own most common write path - a trap to disarm here rather than discover in a hung window.
#
# Process-local, and honestly so: this serializes THIS process against itself. A second Stockroom
# or a git command the user runs by hand is still outside it, which is what git's own index.lock is
# for. Every construction site passes a repo ROOT (`rec.git_root`, `libraries_root`), so the key is
# the repo; a GitRepo built on a SUBDIRECTORY would key separately and is not a supported shape.
_WRITE_LOCKS: dict[str, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


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


def _serialized(method):
    """Run `method` holding this repository's write lock, so two of our own index writes queue
    instead of colliding on `.git/index.lock`. See `_WRITE_LOCKS` above for why it is per-repo and
    re-entrant. Applied to every method that WRITES the index, working tree or refs; read-only
    methods are deliberately left unlocked so status, log and diff never queue behind a commit."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._write_lock():
            return method(self, *args, **kwargs)

    return wrapper


class GitRepo:
    def __init__(self, root: Path, git_binary: str | None = None):
        resolved = shutil.which(git_binary or "git")
        if resolved is None:
            raise GitError(f"git not found: {git_binary or 'git'}")
        self.git = resolved
        self.root = Path(root)

    def _write_lock(self) -> threading.RLock:
        """The write lock for THIS repository. See `_WRITE_LOCKS` above."""
        # `str()` of the resolved path, not the Path object: Path hashes by its parts, which is
        # fine, but a string key is what the dict is documented to hold and survives a Path
        # subclass. Resolution normalizes symlinks and, on Windows, case.
        key = str(Path(self.root).resolve())
        with _WRITE_LOCKS_GUARD:
            lock = _WRITE_LOCKS.get(key)
            if lock is None:
                lock = threading.RLock()
                _WRITE_LOCKS[key] = lock
            return lock

    def _run(
        self,
        *args: str,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.git, "-C", str(self.root), *args],
            capture_output=True,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
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

    @_serialized
    def init(self, *, bare: bool = False) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        args = ["init", "-b", "main"]
        if bare:
            args.append("--bare")
        subprocess.run([self.git, "-C", str(self.root), *args], capture_output=True, text=True,
                       check=True, creationflags=_NO_WINDOW)
        if not bare:
            self._set_test_identity_if_missing()

    @_serialized
    def clone_from(self, origin: Path) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [self.git, "clone", str(origin), str(self.root)],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise GitError(f"git clone failed: {proc.stderr.strip()}")
        self._set_test_identity_if_missing()

    def is_git_repo(self) -> bool:
        return self._run("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def head(self) -> str:
        proc = self._run("rev-parse", "HEAD", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def has_commit(self, sha: str) -> bool:
        """Whether this repo holds `sha` as a real commit object. `cat-file -e <sha>^{commit}`
        is the cheap existence probe, and the `^{commit}` peel matters: without it a 40-hex string
        that happens to name a blob or a tag would answer yes and then break every ancestry query
        built on top of it."""
        if not (sha or "").strip():
            return False
        return self._run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether `ancestor` is reachable from `descendant`. Exit 0 means yes, 1 means no, and
        anything else is a real error (a missing object), which must NOT read as "no" -- callers
        check `has_commit` first so an unknown commit gets its own honest status instead of being
        silently reported as a divergence."""
        return self._run(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        ).returncode == 0

    def count_commits(self, base: str, tip: str) -> int:
        """How many commits `tip` has that `base` does not (`git rev-list --count base..tip`).
        Returns 0 when either end is unknown, so a count can never invent distance."""
        proc = self._run("rev-list", "--count", f"{base}..{tip}", check=False)
        if proc.returncode != 0:
            return 0
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return 0

    def remote_url(self, name: str = "origin") -> str:
        """The configured URL for `name`, or "" when there is no such remote. This is the only
        machine-independent IDENTITY a git repo has; a filesystem path is different on every peer."""
        proc = self._run("remote", "get-url", name, check=False)
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

    @_serialized
    def commit(self, message: str, paths: list[Path], force: bool = False) -> str:
        if not message.strip():
            raise GitError("commit message must not be empty")
        # Guarantee a commit identity for EVERY commit, not only after init()/clone_from(): the
        # library committed inside the app repo is cloned by the launcher's raw `git clone` (never
        # GitRepo.clone_from), so on a fresh machine with no global git identity its first part
        # commit would otherwise fail with "Please tell me who you are". A real global identity
        # still wins; this only fills a MISSING one.
        self._set_test_identity_if_missing()
        # -A so a scoped commit also stages DELETIONS of tracked files that were removed
        # from the working tree (profile/part deletion), not just adds/mods. Only add
        # paths git can still see (present on disk, or still tracked in the index): a path
        # that is neither (e.g. the source of a rename already staged by `git mv`) would
        # abort `git add` with "did not match any files". Its change is already staged, so
        # --only below still carries it into the commit.
        addable = [p for p in paths if Path(p).exists() or self._is_tracked(p)]
        if not force:
            # A path that is IGNORED and no longer tracked must not be handed to `git add`: git
            # aborts the whole invocation with "The following paths are ignored by one of your
            # .gitignore files", which would fail a commit whose real content is elsewhere. This is
            # the workspace-hygiene case: the same commit adds the new ignore rules AND untracks the
            # per-user files those rules now cover, so by the time we stage, the untracked paths are
            # ignored but still present on disk. They stay in `committable` below, which is what
            # carries their already-staged deletion into the commit. `force=True` keeps its old
            # meaning (commit a path an ignore rule would skip) and is left alone.
            addable = [p for p in addable if not (self._is_ignored(p) and not self._is_tracked(p))]
        if addable:
            # force=True (-f) commits paths a .gitignore would skip. Used for engine bookkeeping
            # that MUST be tracked regardless of a user/library ignore rule (a profile's structural
            # .gitkeep scaffold): without it `git add` errors on the ignored keepfiles and the
            # profile lands on disk but never in git (the phantom-profile bug).
            add_args = ["add", "-A"] + (["-f"] if force else []) + ["--"]
            self._run(*add_args, *[str(p) for p in addable])
        # nothing staged among these paths => no-op, return current head.
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.head()
        # After staging, a path can have vanished from git's knowledge entirely: a file STAGED by
        # an interrupted earlier run (in the index, never in HEAD) then deleted from disk - `add
        # -A` above erases its index entry, leaving it in neither HEAD, index, nor working tree.
        # Its net change is nothing, but `commit --only` ABORTS on a pathspec git does not know
        # (the winverify regenerate failure, 2026-07-23), so carry only the paths git still knows.
        committable = [
            p for p in paths if Path(p).exists() or self._is_tracked(p) or self._in_head(p)
        ]
        if not committable:
            # every path was a ghost; the staged diff seen above belongs to FOREIGN work outside
            # these paths, which a bare `commit --only --` must never sweep into a scoped commit.
            return self.head()
        self._run("commit", "-m", message, "--only", "--", *[str(p) for p in committable])
        return self.head()

    @_serialized
    def commit_staged(self, message: str) -> str:
        """Commit exactly what is in the INDEX, with no pathspec. Returns the new head, or the
        current head when nothing is staged.

        `commit(message, paths)` cannot express this. Git implies `--only` whenever a pathspec is
        given, and `--only` takes the WORKING TREE content of those paths, so a file whose deletion
        was staged by `git rm --cached` but which still exists on disk is silently RE-ADDED. That is
        exactly the workspace-hygiene case: the same commit adds ignore rules and untracks the
        per-user files those rules cover, while deliberately leaving those files on disk.

        The caller MUST have verified the tree was clean before staging, or this sweeps foreign work
        into what is supposed to be a scoped commit. `mutation/hygiene.apply_hygiene` enforces that
        with an explicit refuse.
        """
        if not message.strip():
            raise GitError("commit message must not be empty")
        self._set_test_identity_if_missing()
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.head()
        self._run("commit", "-m", message)
        return self.head()

    @_serialized
    def untrack(self, paths) -> None:
        """Stop tracking `paths` while LEAVING them on disk (`git rm --cached`).

        This is what actually stops two peers conflicting on a per-user file. Verified against git:
        adding an ignore rule has no effect on a file that is already tracked, so the rule alone
        changes nothing observable. Staged only; the caller commits.
        """
        rel = [str(p) for p in (paths or [])]
        if rel:
            self._run("rm", "--cached", "--quiet", "--", *rel)

    def _is_ignored(self, path: Path) -> bool:
        """Whether a .gitignore rule covers this path. `check-ignore` exits 0 on a match, 1 on no
        match, and >1 on a real error; only an exact 0 counts, so an error can never be read as
        "ignored" and silently drop a path out of a commit."""
        return self._run("check-ignore", "-q", "--", str(path), check=False).returncode == 0

    def _is_tracked(self, path: Path) -> bool:
        return (
            self._run("ls-files", "--error-unmatch", "--", str(path), check=False).returncode == 0
        )

    def _in_head(self, path: Path) -> bool:
        """Whether HEAD holds this path (unlike _is_tracked, which reads the INDEX - a
        staged-but-never-committed file is tracked there yet unknown to HEAD). check=False
        also covers the empty repo, where there is no HEAD to read."""
        out = self._run("ls-tree", "--name-only", "HEAD", "--", str(path), check=False)
        return out.returncode == 0 and out.stdout.strip() != ""

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

    @_serialized
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

    @_serialized
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

    @_serialized
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

    # Where a local file is moved when an incoming commit wants to add the same path. Inside the
    # repo but git-ignored, so it travels nowhere and is trivially findable by the person whose
    # file it was -- as opposed to a system temp dir, which is where data goes to be forgotten.
    _RESCUE_DIR = ".stockroom-kept"

    def _clear_untracked_blockers(self, target: str) -> list[str]:
        """Move aside untracked files that `target` would add, so a pull cannot be blocked by one.

        THE OWNER'S REAL FAILURE, 2026-07-27: their laptop could not update at all, because the app
        had created ten `SR-<Category>.kicad_sym` files locally (untracked) and the incoming commits
        add those exact paths. Git refuses to clobber an untracked file and aborts the whole
        operation -- so one machine simply could not receive another's updates, which is the
        *"same update, same files, same info"* rule broken outright.

        NEVER destructive. A file whose bytes already match the incoming one is just removed (there
        is nothing to keep, and a backup would be clutter in the user's library). Anything that
        DIFFERS is moved under `_RESCUE_DIR`, keeping its path, so the person still has it.

        Returns the repo-relative paths that were moved or removed, so the caller can report them.
        """
        merge_base = self._run("merge-base", "HEAD", target, check=False).stdout.strip()
        if not merge_base:
            return []
        # Exactly the paths the incoming commits ADD. Narrow on purpose: this must never touch an
        # untracked file the update has no opinion about.
        added = self._run(
            "diff", "--name-only", "--diff-filter=A", merge_base, target, check=False
        ).stdout.split("\n")
        cleared: list[str] = []
        for rel in (p.strip() for p in added):
            if not rel:
                continue
            local = self.root / rel
            if not local.is_file():
                continue
            # Tracked already? Then git handles it normally and this has no business here.
            if self._run("ls-files", "--error-unmatch", rel, check=False).returncode == 0:
                continue
            # Compare by git's OWN object hash rather than by reading bytes: `_run` is text-mode,
            # and a `.step` or `.PcbLib` is binary, so a byte comparison through it would corrupt
            # the very comparison it is making. `hash-object` also costs one small process instead
            # of loading a 3 MB model into memory.
            theirs = self._run("rev-parse", f"{target}:{rel}", check=False)
            mine = self._run("hash-object", str(local), check=False)
            same = (
                theirs.returncode == 0
                and mine.returncode == 0
                and theirs.stdout.strip() == mine.stdout.strip()
            )
            if not same:
                kept = self.root / self._RESCUE_DIR / rel
                kept.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(local), str(kept))
            else:
                local.unlink()
            cleared.append(rel)
        return cleared

    @_serialized
    def pull_rebase(self) -> PullResult:
        """Pull, REBASING local commits onto the upstream. For the in-repo library (which shares
        one repo with the app code), a local part commit + a remote app-code commit touch DISJOINT
        paths, so a rebase replays the part commit on top of the update cleanly, reconciling what a
        fast-forward could not. A real conflict aborts the half-applied rebase and reports honestly."""
        before = self.head()
        # Fetch FIRST so the blocker check can see what is actually incoming. Without a fetch the
        # upstream ref is whatever was last seen, so a brand-new file would not be found and the
        # pull would abort exactly as before.
        fetched = self._run("fetch", check=False)
        if fetched.returncode != 0:
            # Let the pull below produce the authoritative error. A failed fetch is usually
            # offline, and duplicating that judgement here would be a second place to keep right.
            return PullResult(ok=False, updated=False, reason=fetched.stderr.strip())
        upstream = self._run(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False
        ).stdout.strip()
        if upstream:
            self._clear_untracked_blockers(upstream)
        proc = self._run("pull", "--rebase", check=False)
        if proc.returncode != 0:
            self._run("rebase", "--abort", check=False)  # leave the tree clean on a conflict
            text = (proc.stderr + proc.stdout).lower()
            reason = "not fast-forwardable (diverged)" if "conflict" in text else proc.stderr.strip()
            return PullResult(ok=False, updated=False, reason=reason)
        return PullResult(ok=True, updated=self.head() != before, reason="")

    def set_config(self, key: str, value: str) -> None:
        """Set a LOCAL git config key on this repo (in .git/config, never committed)."""
        self._run("config", key, value)

    def unset_config(self, key: str) -> None:
        """Remove a local git config key (idempotent: absent is not an error)."""
        self._run("config", "--unset-all", key, check=False)

    def has_remote(self) -> bool:
        return bool(self._run("remote", check=False).stdout.strip())

    def fetch(self) -> tuple[bool, str]:
        """Update the remote-tracking refs (no working-tree change). Returns
        (ok, reason) so a caller can report an unreachable remote honestly."""
        proc = self._run("fetch", "--prune", check=False)
        return proc.returncode == 0, proc.stderr.strip()

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
