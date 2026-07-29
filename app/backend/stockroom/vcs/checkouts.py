"""Bounded, read-only detection of canonical and rival Stockroom checkouts."""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from stockroom.vcs.repo import GitError, GitRepo

_PRUNE = {
    "$recycle.bin",
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    "system volume information",
}


@dataclass(frozen=True, slots=True)
class CheckoutRecord:
    path: str
    classification: str
    revision: str
    current: bool
    tracked_dirty: bool
    active_library: bool


def _remote_identity(url: str) -> str:
    value = url.strip().replace("\\", "/").rstrip("/").casefold()
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(.+)", value)
    if scp and "://" not in value:
        value = f"{scp.group(1)}/{scp.group(2)}"
    elif "://" in value and not value.startswith("file://"):
        value = value.split("://", 1)[1]
        if "@" in value.split("/", 1)[0]:
            value = value.split("@", 1)[1]
    return value[:-4] if value.endswith(".git") else value


def default_checkout_roots(canonical: Path) -> tuple[Path, ...]:
    """Cover the canonical drive plus Stockroom's managed LocalAppData area."""
    canonical = Path(canonical).resolve()
    candidates = [Path(canonical.anchor)] if canonical.anchor else [canonical.parent]
    windows_workspace = Path("D:/Workspace")
    if windows_workspace.exists():
        candidates.append(windows_workspace)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Stockroom")
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def scan_stockroom_checkouts(
    canonical_repo: GitRepo,
    *,
    roots: tuple[Path, ...] | None = None,
    active_library: Path | None = None,
    releases_root: Path | None = None,
    max_depth: int = 7,
    max_directories: int = 20000,
) -> dict[str, object]:
    """Find same-remote Git checkouts without following links or scanning forever."""
    canonical = canonical_repo.top_level() or canonical_repo.root.resolve()
    canonical_remote = _remote_identity(canonical_repo.remote_url())
    active = Path(active_library).resolve() if active_library is not None else None
    releases = Path(releases_root).resolve() if releases_root is not None else None
    queue = deque(
        (Path(root).resolve(), 0) for root in (roots or default_checkout_roots(canonical))
    )
    visited: set[Path] = set()
    found: dict[Path, CheckoutRecord] = {}
    scanned = 0
    truncated = False

    while queue:
        directory, depth = queue.popleft()
        if directory in visited:
            continue
        visited.add(directory)
        scanned += 1
        if scanned > max_directories:
            truncated = True
            break
        try:
            is_repo = (directory / ".git").exists()
        except OSError:
            continue
        if is_repo:
            try:
                repo = GitRepo(directory, git_binary=canonical_repo.git)
                top = repo.top_level()
                remote = _remote_identity(repo.remote_url())
            except (GitError, OSError):
                top = None
                remote = ""
            # An unmanaged canonical checkout has no remote identity to compare. Treating an
            # empty identity as a wildcard mislabeled every unrelated local Git repository as a
            # Stockroom rival. The canonical path remains reportable; rivals require a positive,
            # equal remote identity.
            if top is not None and (
                top.resolve() == canonical
                or bool(canonical_remote and remote == canonical_remote)
            ):
                top = top.resolve()
                if top == canonical:
                    classification = "canonical"
                elif releases is not None and top.is_relative_to(releases):
                    classification = "staged_release"
                elif active is not None and top == active:
                    classification = "active_rival"
                else:
                    classification = "rival"
                found[top] = CheckoutRecord(
                    path=str(top),
                    classification=classification,
                    revision=repo.head()[:12],
                    current=repo.head() == canonical_repo.head(),
                    tracked_dirty=repo.has_tracked_changes(),
                    active_library=active == top,
                )
            # A working tree cannot contain another normal checkout except explicit
            # worktrees/submodules; scanning its payload is both expensive and noisy.
            continue
        if depth >= max_depth:
            # A depth limit is an evidence boundary, not proof that the subtree contains no
            # checkout. Only mark the scan truncated when a traversable child actually exists,
            # avoiding a false warning for leaves that happen to sit at the boundary.
            try:
                truncated = truncated or any(
                    child.is_dir(follow_symlinks=False)
                    and not child.is_symlink()
                    and child.name.casefold() not in _PRUNE
                    for child in os.scandir(directory)
                )
            except OSError:
                pass
            continue
        try:
            children = list(os.scandir(directory))
        except OSError:
            continue
        for child in children:
            try:
                if (
                    child.is_dir(follow_symlinks=False)
                    and not child.is_symlink()
                    and child.name.casefold() not in _PRUNE
                ):
                    queue.append((Path(child.path), depth + 1))
            except OSError:
                continue

    if canonical not in found:
        found[canonical] = CheckoutRecord(
            path=str(canonical),
            classification="canonical",
            revision=canonical_repo.head()[:12],
            current=True,
            tracked_dirty=canonical_repo.has_tracked_changes(),
            active_library=active == canonical,
        )
    records = sorted(
        found.values(),
        key=lambda record: (
            0 if record.classification == "canonical" else 1,
            record.path.casefold(),
        ),
    )
    return {
        "state": "truncated" if truncated else "complete",
        "scanned_directories": min(scanned, max_directories),
        "max_directories": max_directories,
        "rival_count": sum(
            record.classification in {"rival", "active_rival"} for record in records
        ),
        "checkouts": [asdict(record) for record in records],
    }
