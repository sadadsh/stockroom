"""git-lfs: where a growing binary EDA library's CONTENT actually lives.

Batch 2 item 4. Without it every captured part adds a permanent, un-GC-able copy of its `.PcbLib`,
`.SchLib` and `.step` to history, for every person who will ever clone the repo. Stockroom's own
`.git` was already 72 MB with roughly 460 KB of binaries for a ONE-part library.

PRIOR ART, and what was REJECTED: this module deliberately does NOT implement any file-locking,
pointer format, chunking or transfer logic. All of it exists in git-lfs, which is installed, is the
de-facto standard, and is what the hosting side already speaks. This is a thin, honest wrapper over
the `git lfs` CLI: probe what is true, turn it on, and report what it does not do. A hand-rolled
check-out model was the alternative considered in the 2026-07-24 research and rejected there.

Two things measured on 2026-07-25 that shape the whole design, and that the ecosystem's copy-paste
advice gets wrong:

1. **`merge=lfs` is not a merge driver.** git-lfs registers none, so git text-merges the POINTER
   file and writes conflict markers inside it, leaving a corrupt pointer. Stockroom therefore emits
   `filter=lfs binary`, keeping git's take-ours-and-conflict semantics. That decision lives in
   `eda/registry.workspace_gitattributes`; this module only makes the filter real.
2. **`lockable` checks files out READ-ONLY, and locking is impossible without a remote.**
   `git lfs lock` fails with `missing protocol: ""` on a repo with no remote, so a lockable file
   there can never be made writable again through LFS. Hence `locking_probe`, and hence the
   registry listing only files Stockroom itself never writes as lockable.

**What adopting LFS does NOT do:** it does not shrink existing history. Blobs already committed
stay in the pack files; only NEW commits of a tracked path become pointers. Converting the past
needs `git lfs migrate`, which REWRITES history and therefore requires a force-push, which is
forbidden in this project. `LfsStatus.legacy_blobs` reports how many tracked paths are still stored
the old way so the limitation is visible rather than implied away.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from stockroom.vcs.repo import GitRepo

# CREATE_NO_WINDOW on Windows so a probe never flashes a console window; a harmless 0 on POSIX.
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

# The git config key `git lfs install` writes. Its presence is the only reliable answer to "is the
# filter actually wired up in THIS repo", and the attributes are inert without it: a `filter=lfs`
# line with no filter configured stores the file normally and says nothing.
_CLEAN_KEY = "filter.lfs.clean"


@dataclass(frozen=True)
class LfsStatus:
    """What is true about git-lfs here, with nothing inferred."""

    # Is the `git lfs` binary reachable at all?
    installed: bool = False
    version: str = ""
    # Is the filter wired into THIS repository (`git lfs install --local`)?
    enabled: bool = False
    # Patterns in the repo's .gitattributes that route content through LFS.
    tracked_patterns: tuple[str, ...] = ()
    # Files currently stored as LFS pointers.
    objects: int = 0
    # Tracked files that MATCH an LFS pattern but are still stored as ordinary git blobs, i.e.
    # committed before LFS was adopted. Converting them needs a history rewrite, so this number
    # is reported and never silently "fixed".
    legacy_blobs: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "installed": self.installed,
            "version": self.version,
            "enabled": self.enabled,
            "tracked_patterns": list(self.tracked_patterns),
            "objects": self.objects,
            "legacy_blobs": self.legacy_blobs,
            "reason": self.reason,
        }


def _lfs(repo: GitRepo, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [repo.git, "-C", str(repo.root), "lfs", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=check, creationflags=_NO_WINDOW,
    )


def available() -> tuple[bool, str]:
    """Whether `git lfs` can run here, and its version string.

    Probes by RUNNING it rather than by looking for a binary on PATH: git-lfs is normally installed
    as a git subcommand, so `shutil.which("git-lfs")` can miss a perfectly working install.
    """
    if shutil.which("git") is None:
        return False, ""
    proc = subprocess.run(
        ["git", "lfs", "version"], capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        return False, ""
    return True, proc.stdout.strip()


def repo_enabled(repo: GitRepo) -> bool:
    """Whether the LFS filter is configured for this repo (local or global config).

    This is the check that matters, and the one it is easy to skip: `.gitattributes` can name
    `filter=lfs` all day, and without the filter git stores the file normally and reports nothing.
    """
    return repo._run("config", "--get", _CLEAN_KEY, check=False).returncode == 0


def _parse_tracked_patterns(output: str) -> tuple[str, ...]:
    """Parse only the tracked section of ``git lfs track`` output.

    Git LFS may normalize pattern casing for the host filesystem, so retain the CLI-reported
    pattern verbatim. The command also prints a separate excluded-patterns section; neither its
    heading nor its rows describe content routed through LFS.
    """
    out: list[str] = []
    in_tracked_section = False
    for line in output.splitlines():
        line = line.strip()
        heading = line.casefold()
        if heading.startswith("listing tracked patterns"):
            in_tracked_section = True
            continue
        if heading.startswith("listing excluded patterns"):
            in_tracked_section = False
            continue
        if not line or not in_tracked_section:
            continue
        # Pattern rows are `<pattern> (<attributes source>)`. Split from the right so a literal
        # opening parenthesis in a pattern is not truncated.
        pattern, separator, source = line.rpartition(" (")
        if not separator or not source.endswith(")"):
            continue
        pattern = pattern.strip()
        if pattern:
            out.append(pattern)
    return tuple(out)


def tracked_patterns(repo: GitRepo) -> tuple[str, ...]:
    """The patterns git-lfs believes it is handling, read from git-lfs itself rather than parsed
    out of `.gitattributes`, so an attributes file that does not mean what it looks like cannot
    produce a confident wrong answer."""
    proc = _lfs(repo, "track")
    if proc.returncode != 0:
        return ()
    return _parse_tracked_patterns(proc.stdout)


def _pointer_count(repo: GitRepo) -> int:
    proc = _lfs(repo, "ls-files")
    if proc.returncode != 0:
        return 0
    return len([ln for ln in proc.stdout.splitlines() if ln.strip()])


def _legacy_blob_count(repo: GitRepo, patterns) -> int:
    """Tracked files matching an LFS pattern that are NOT pointers, i.e. committed before LFS was
    adopted. They stay as ordinary blobs until a history rewrite, which this project forbids."""
    if not patterns:
        return 0
    from stockroom.eda import workspace

    tracked = [ln for ln in repo._run("ls-files").stdout.splitlines() if ln.strip()]
    matching = set(workspace.matching(tracked, list(patterns)))
    if not matching:
        return 0
    pointers = {ln.split(" ")[-1] for ln in _lfs(repo, "ls-files").stdout.splitlines() if ln.strip()}
    return len(matching - pointers)


def status(repo: GitRepo) -> LfsStatus:
    """Everything true about LFS in this repo, with NO network access.

    Locking is deliberately not probed here: it is a remote round trip, and a status read that
    silently reaches the network is a status read nobody can afford to call often.
    """
    ok, version = available()
    if not ok:
        return LfsStatus(reason="git-lfs is not installed on this machine")
    if not repo.is_git_repo():
        return LfsStatus(installed=True, version=version, reason="this library is not under git")
    enabled = repo_enabled(repo)
    patterns = tracked_patterns(repo) if enabled else ()
    return LfsStatus(
        installed=True,
        version=version,
        enabled=enabled,
        tracked_patterns=patterns,
        objects=_pointer_count(repo) if enabled else 0,
        legacy_blobs=_legacy_blob_count(repo, patterns) if enabled else 0,
    )


def enable(repo: GitRepo) -> None:
    """Wire the LFS filter into THIS repo (`git lfs install --local`).

    `--local` on purpose: Stockroom must not reconfigure a person's global git for them, and the
    repo-local config is what a clone of this library needs anyway. Idempotent.
    """
    ok, _version = available()
    if not ok:
        raise RuntimeError("git-lfs is not installed on this machine")
    proc = _lfs(repo, "install", "--local")
    if proc.returncode != 0:
        raise RuntimeError(f"git lfs install failed: {(proc.stderr or proc.stdout).strip()}")


def locking_probe(repo: GitRepo) -> tuple[bool, str]:
    """Whether this repo's remote answers the LFS LOCKING API. Reaches the network.

    Called only when someone is deciding whether to turn `lockable` on, because a lockable file on
    a repo that cannot lock is checked out read-only with no way back (measured 2026-07-25:
    `git lfs lock` on a remoteless repo fails with `missing protocol: ""`).
    """
    ok, _version = available()
    if not ok:
        return False, "git-lfs is not installed on this machine"
    if not repo.has_remote():
        return False, (
            "this repository has no remote, so git-lfs has no locking server to talk to and a "
            "locked file could never be unlocked"
        )
    proc = _lfs(repo, "locks", "--limit", "1")
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip() or "the remote did not answer"
    return True, ""
