"""Git access for the launcher: prefer the git binary on PATH, else a dulwich
ff-only pull, else a clear failure telling the user to install git
(knowledge-transfer section 3.7). The backend CHOICE is pure and tested here; the
actual dulwich pull and the frozen-exe wiring are verified on Windows (the launcher
task). dulwich is a launcher-only dependency, never imported by the backend."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable


def git_on_path() -> str | None:
    return shutil.which("git")


def _dulwich_available() -> bool:
    try:
        import dulwich  # noqa: F401

        return True
    except Exception:
        return False


def choose_pull_backend(
    which: Callable[[str], str | None] = shutil.which,
    have_dulwich: bool | None = None,
) -> str:
    if which("git"):
        return "git"
    dulwich_ok = _dulwich_available() if have_dulwich is None else have_dulwich
    if dulwich_ok:
        return "dulwich"
    raise RuntimeError(
        "no git on PATH and dulwich is unavailable; install git to enable self-update"
    )


def ensure_ff_pull(repo_root: Path, backend: str | None = None) -> bool:
    repo_root = Path(repo_root)
    backend = backend or choose_pull_backend()
    if backend == "git":
        before = _head(repo_root)
        subprocess.run(
            ["git", "-C", str(repo_root), "pull", "--ff-only"],
            check=True, capture_output=True, text=True,
        )
        return _head(repo_root) != before
    # dulwich ff-only pull (launcher-only path; exercised on Windows)
    from dulwich import porcelain

    before = _head(repo_root)
    porcelain.pull(str(repo_root))  # dulwich pull is ff by default for a clean tree
    return _head(repo_root) != before


def _head(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""
