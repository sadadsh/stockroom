#!/usr/bin/env python3
"""Fast-forward the owner's Windows install to this repo's HEAD, and PROVE the code arrived.

The install at `%LOCALAPPDATA%\\Stockroom\\app` is a git checkout, so deploying is a fast-forward.
Doing it by hand is four commands, and two of them lie if you read them casually:

  1. **`git merge --ff-only` prints a success-looking line EVEN WHEN IT ABORTS**, and prints it
     AFTER the error, so `| tail -1` shows `Updating <a>..<b>` on a merge that did not happen.
     Therefore the resulting HEAD is always asserted, never inferred from the merge output.
  2. **Comparing HEAD to HEAD passes trivially when the commit never happened.** A `git add` run
     from the wrong directory once produced a confident "DEPLOY-MATCH" against the OLD commit.
     Therefore `--expect` greps the install for the actual EDIT, which is the only check that can
     tell "deployed" from "both sides are equally stale".

Both traps are recorded in the repo's local instructions because both cost real cycles. This script exists so
the next person does not have to remember them.

    uv run python scripts/deploy.py
    uv run python scripts/deploy.py --expect app/backend/stockroom/altium/dblib.py=KEY_COLUMN
    uv run python scripts/deploy.py --install "/mnt/c/.../Stockroom/app"

Exit code is non-zero when the install did not end up at this HEAD, or when an `--expect` marker is
missing, so this can gate.

No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The install is a per-user path and `%LOCALAPPDATA%` does NOT expand through WSL interop, so the
# default is discovered from the Windows user profile rather than hardcoded to one machine's name.
_FALLBACK = "/mnt/c/Users/{user}/AppData/Local/Stockroom/app"


def default_install() -> Path | None:
    """The install directory, discovered. None when this machine has no Windows side."""
    users = Path("/mnt/c/Users")
    if not users.is_dir():
        return None
    for home in sorted(users.iterdir()):
        candidate = home / "AppData" / "Local" / "Stockroom" / "app"
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            # `/mnt/c/Users` carries service profiles this account cannot stat at all, and one of
            # them raised PermissionError the first time this ran. A directory we cannot read is
            # simply not the install, so it is skipped rather than crashing the deploy.
            continue
    return None


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def check_markers(install: Path, markers: list[str]) -> list[str]:
    """The `path=needle` markers NOT found in the install. Empty means every edit arrived."""
    missing: list[str] = []
    for marker in markers:
        rel, _, needle = marker.partition("=")
        if not needle:
            missing.append(f"{marker} (expected the form path=needle)")
            continue
        target = install / rel
        if not target.exists():
            missing.append(f"{rel} is not present in the install")
        elif needle not in target.read_text(encoding="utf-8", errors="replace"):
            missing.append(f"{rel} does not contain {needle!r}")
    return missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", type=Path, default=None)
    ap.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="PATH=NEEDLE",
        help="assert the install's PATH contains NEEDLE. Repeatable. This is the check that "
        "distinguishes a real deploy from two equally stale checkouts.",
    )
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args(argv)

    install = a.install or default_install()
    if install is None or not (install / ".git").exists():
        print("FAILED: no Stockroom install found. Pass --install with its path.")
        return 2

    mine = head(REPO)
    if not mine:
        print(f"FAILED: {REPO} is not a git repository.")
        return 2

    dirty = git(REPO, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        print("WARNING: this repo has uncommitted tracked changes, which will NOT be deployed:")
        for line in dirty.splitlines()[:5]:
            print(f"    {line}")

    git(install, "fetch", "--quiet", a.remote)
    merge = git(install, "merge", "--ff-only", f"{a.remote}/main")
    theirs = head(install)

    print(f"  repo    HEAD {mine}")
    print(f"  install HEAD {theirs}")
    if theirs != mine:
        # Never trust the merge output: see trap 1 in the module docstring.
        print("FAILED: the install is NOT at this repo's HEAD. The merge did not apply.")
        print((merge.stderr or merge.stdout).strip()[:500])
        return 1

    missing = check_markers(install, a.expect)
    if missing:
        print("FAILED: HEAD matches but the expected code is NOT in the install:")
        for m in missing:
            print(f"    {m}")
        return 1

    proof = f"; {len(a.expect)} content marker(s) verified" if a.expect else ""
    print(f"DEPLOYED: install is at {mine[:12]}{proof}")
    if not a.expect:
        print("  note: HEAD equality alone cannot tell a real deploy from two stale checkouts.")
        print("  Pass --expect path=needle to prove the actual edit arrived.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
