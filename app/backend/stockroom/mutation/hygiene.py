"""Apply the EDA registry's workspace hygiene to a real git repo, as one atomic commit.

This closes the gap the punch list recorded as "the registry generates the rules and nothing writes
them", which was the MEASURED cause of the owner's KiCad peer-sync failures. It is deliberately a
two-part operation, because measuring it showed one part alone does nothing:

  1. Refresh the Stockroom managed block in `.gitignore` and `.gitattributes` (see eda/workspace.py).
     Content outside the markers is preserved: Stockroom registers projects, it does not own them.
  2. UNTRACK every already-committed path those ignore rules now cover. Verified against git: an
     ignore rule has no effect on a tracked file, and the owner's `.kicad_prl` / `fp-info-cache` are
     already committed, which is exactly why two peers conflict on them. `git rm --cached` leaves the
     working copy on disk, so nobody loses their local editor state.

Both parts land in ONE commit or neither does, through the same Transaction every other Stockroom
mutation uses.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.eda import workspace
from stockroom.eda.registry import _resolve, workspace_gitattributes, workspace_gitignore
from stockroom.mutation.transaction import Transaction
from stockroom.text import counted
from stockroom.vcs import lfs as lfs_backend
from stockroom.vcs.repo import GitRepo

IGNORE_FILE = ".gitignore"
ATTRIBUTES_FILE = ".gitattributes"


def _rules_for(tool_keys) -> list[str]:
    """Every ignore PATTERN the given tools contribute, flat. Read from the resolved tools rather
    than re-parsed out of the rendered file, so the untrack decision and the written rules cannot
    disagree about what is covered."""
    out: list[str] = []
    for tool in _resolve(tool_keys, ()):
        # `ignored_patterns`, not `ignore`: a DERIVED artifact that is already committed (the
        # Altium `stockroom-parts.db`, which shipped tracked until 2026-07-25) must be untracked
        # too, or the generated rules would claim it is ignored while git keeps sharing it.
        out.extend(tool.ignored_patterns())
    return out


def detect_lfs(root) -> tuple[bool, bool]:
    """Whether this workspace has already adopted git-lfs, and whether it uses `lockable`, read
    from its own `.gitattributes`.

    Adoption is a property OF THE REPO, not a setting stored somewhere else that could disagree
    with it. Reading it back means a routine hygiene sync PRESERVES an adoption instead of silently
    reverting the attributes to the non-LFS form the next time anything re-syncs, which is the
    quiet way a feature gets turned off for someone.
    """
    path = Path(root) / ATTRIBUTES_FILE
    if not path.exists():
        return False, False
    text = path.read_text(encoding="utf-8")
    return ("filter=lfs" in text), ("lockable" in text)


def _planned(root: Path, tool_keys, repo: GitRepo, lfs: bool = False, lockable: bool = False):
    """(writes, untrack, rendered) without touching anything.

    `writes` names the files whose content would change, `untrack` the tracked paths the ignore rules
    now cover, `rendered` maps file name to its full new text.
    """
    root = Path(root)
    rendered = {
        IGNORE_FILE: workspace_gitignore(tool_keys),
        ATTRIBUTES_FILE: workspace_gitattributes(tool_keys, lfs=lfs, lockable=lockable),
    }
    writes: list[str] = []
    merged: dict[str, str] = {}
    for name, body in rendered.items():
        path = root / name
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        # merge_block raises on an unterminated marker; let it propagate BEFORE any write, so a
        # hand-edited file is never half-repaired.
        text = workspace.merge_block(existing, body)
        merged[name] = text
        if text != existing:
            writes.append(name)

    tracked = [line for line in repo._run("ls-files").stdout.splitlines() if line.strip()]
    # Never offer to untrack the hygiene files themselves; they are meant to be committed.
    candidates = [p for p in tracked if p not in (IGNORE_FILE, ATTRIBUTES_FILE)]
    untrack = workspace.matching(candidates, _rules_for(tool_keys))
    return sorted(writes), sorted(untrack), merged


def _lfs_flags(root, lfs, lockable) -> tuple[bool, bool]:
    """Resolve the LFS flags, defaulting to whatever this workspace has ALREADY adopted."""
    detected_lfs, detected_lockable = detect_lfs(root)
    return (detected_lfs if lfs is None else lfs,
            detected_lockable if lockable is None else lockable)


def hygiene_preview(root, tool_keys, repo: GitRepo | None = None, lfs=None, lockable=None) -> dict:
    """What `apply_hygiene` would do: {writes, untracked}. Read-only, no git, no writes."""
    root = Path(root)
    repo = repo or GitRepo(root)
    use_lfs, use_lockable = _lfs_flags(root, lfs, lockable)
    writes, untrack, _merged = _planned(root, tool_keys, repo, use_lfs, use_lockable)
    return {"writes": writes, "untracked": untrack}


def apply_hygiene(root, tool_keys, repo: GitRepo | None = None, lfs=None, lockable=None) -> dict:
    """Write the managed blocks and untrack the per-user files, as ONE commit on `repo`.

    Returns {writes, untracked, committed}. A run that would change nothing is an honest no-commit
    no-op ({committed: None}), so re-syncing does not churn history.

    `lfs` / `lockable` default to whatever this workspace has ALREADY adopted (read back from its
    own `.gitattributes`), so a routine sync never silently un-adopts LFS. Passing `lfs=True` is
    what ADOPTS it, and that path also runs `git lfs install --local` in the same operation:
    attributes naming `filter=lfs` with no filter configured are INERT, and git stores the file
    normally while reporting nothing, so writing one without the other would look like success and
    do nothing.

    Raises ValueError for a tree with uncommitted changes (a hygiene commit stages whole paths, so an
    in-progress user edit must never be swept into it), for a hygiene file whose managed block was
    left unterminated by a hand edit, or when `lockable` is asked for without `lfs`.
    """
    root = Path(root)
    repo = repo or GitRepo(root)
    use_lfs, use_lockable = _lfs_flags(root, lfs, lockable)
    # Two PRECISE guards rather than one blunt "is the tree clean".
    #
    # A blunt clean check would be wrong in both directions. Too strict: the library repo always has
    # regenerated and in-progress files lying around, so hygiene could never run on a real library.
    # Too lax in the one place it matters: `commit_staged` commits the whole INDEX, so anything
    # already staged really would be swept into a commit the user did not make.
    #
    # Untracked and unstaged-modified files elsewhere are harmless here: they are not in the index,
    # and only our own paths get staged.
    if repo._run("diff", "--cached", "--quiet", check=False).returncode != 0:
        raise ValueError(
            "this repository has staged changes; commit or unstage them before syncing workspace "
            "hygiene, so they are not swept into the hygiene commit"
        )
    # The one exception: we MERGE into the current on-disk text of the hygiene files, so committing
    # them would carry an unfinished edit of the user's along with our block.
    # Only the hygiene files that actually exist: `is_clean([])` falls back to checking the WHOLE
    # tree, which would quietly reinstate the blunt guard this replaced.
    hygiene_paths = [p for p in (root / IGNORE_FILE, root / ATTRIBUTES_FILE) if p.exists()]
    if hygiene_paths and not repo.is_clean(hygiene_paths):
        raise ValueError(
            f"{IGNORE_FILE} or {ATTRIBUTES_FILE} has uncommitted changes; commit or discard them "
            "before syncing workspace hygiene"
        )
    writes, untrack, merged = _planned(root, tool_keys, repo, use_lfs, use_lockable)
    # The filter has to exist BEFORE the attributes are committed, or the very commit that adopts
    # LFS stores its own payloads as ordinary blobs. Idempotent, and it only touches this repo's
    # config, never the user's global git.
    #
    # UNCONDITIONAL on purpose, and this was a real bug: `repo_enabled` resolves git config, which
    # includes the GLOBAL file, and `git lfs install` writes there by default. So on any machine
    # where the developer has ever run `git lfs install`, the check passed and the repo-LOCAL
    # config was never written, leaving the adoption dependent on a per-machine global that a
    # clone, a CI runner or a colleague does not have. Caught on 2026-07-25 by looking at
    # `.git/config` after an adoption that reported success.
    if use_lfs:
        lfs_backend.enable(repo)
    if not writes and not untrack:
        return {"writes": [], "untracked": [], "committed": None}

    touched = [root / name for name in (IGNORE_FILE, ATTRIBUTES_FILE)]
    touched += [root / p for p in untrack]
    label = []
    if writes:
        label.append("ignore rules")
    if untrack:
        label.append(f"{counted(len(untrack), 'per-user file')} untracked")
    with Transaction(repo) as txn:
        for path in touched:
            txn.track(path)
        for name in writes:
            (root / name).write_text(merged[name], encoding="utf-8")
        if writes:
            repo._run("add", "--", *[str(root / name) for name in writes])
        # --cached keeps the working copy: this is about what git SHARES, never about deleting
        # somebody's editor state.
        repo.untrack([root / p for p in untrack])
        # commit_staged, NOT commit(paths): a pathspec makes git imply --only, which takes the
        # WORKING TREE content of those paths and would silently re-add the very files just
        # untracked. Safe here only because a dirty tree was refused above, so nothing foreign
        # can be staged.
        sha = txn.commit_staged(f"Sync workspace hygiene: {', '.join(label)}")
    return {"writes": writes, "untracked": untrack, "committed": sha}
