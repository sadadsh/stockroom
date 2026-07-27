#!/usr/bin/env python3
"""Migrate a library to schema v3 and the decided part-id scheme. DRY RUN BY DEFAULT.

    uv run python scripts/migrate_library_v3.py                        # show the plan, touch nothing
    uv run python scripts/migrate_library_v3.py --verbose              # every record's move
    uv run python scripts/migrate_library_v3.py --apply                # do it

WHY THIS IS NEEDED: the owner's 158 records are `schema_version: 2` on disk and 84 of their ids
contain underscores, which `sourced/` refuses as path components - so the importer cannot file a
single raw payload against the real library, and the whole sourced/derived split is unreachable.
See `stockroom.migrate.v3_ids` for the full measured inventory of what moves and what does not.

SAFETY, and why there is no separate backup step. The library is a git repository, so a clean tree
plus a recorded HEAD is a complete, verified undo - `git checkout .` restores every renamed file.
This refuses to run against a DIRTY library tree, because that is precisely when `git checkout` is
no longer a full undo. It also refuses when a plan has any blocking error (a collision, a record
whose filename disagrees with its id), and it never commits: a bulk rename of someone's library is
exactly the change a person should read before it enters history.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.migrate.v3_ids import (  # noqa: E402
    apply_migration,
    count_orphan_bindings,
    plan_migration,
)


def _git(library_root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(library_root), *args],
        capture_output=True, text=True, check=False,
    )
    return (out.stdout or "").strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", type=Path, default=REPO / "libraries" / "Stockroom",
                    help="library profile root (default: ./libraries/Stockroom)")
    ap.add_argument("--apply", action="store_true",
                    help="actually rename and rewrite. Without it, nothing is touched.")
    ap.add_argument("--verbose", action="store_true", help="one line per record")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="proceed even though git cannot fully undo this. Say why out loud.")
    ap.add_argument("--allow-orphan-bindings", action="store_true",
                    help="proceed even though registered projects hold bindings that will break")
    a = ap.parse_args(argv)

    library = a.library.resolve()
    print(f"library : {library.as_posix()}")

    plan = plan_migration(library)
    print(f"plan    : {plan.summary()}")

    head = _git(library, "rev-parse", "HEAD")
    # SCOPED TO THE LIBRARY PATH, not the whole repo. The library can be a SUBDIRECTORY of a bigger
    # repo (it is, in this checkout: `libraries/Stockroom` lives inside the stockroom repo), so a
    # bare `git status --porcelain` reports every unrelated edit in the tree - which during any
    # development session is nearly always non-empty. That would make --allow-dirty the normal way
    # to run this, and a guard everybody routinely overrides is not a guard.
    dirty = _git(library, "status", "--porcelain", "--", str(library))
    if head:
        print(f"git     : HEAD {head[:8]}{' (DIRTY)' if dirty else ' (clean - this is the backup)'}")
    else:
        print("git     : NOT a git repository - there is no undo for this")

    if a.verbose:
        print()
        for p in plan.parts:
            flag = "RENAME" if p.renames_id else "in place"
            sheet = " +datasheet" if p.datasheet_from else ""
            print(f"  {flag:8s} v{p.old_schema}->v3  {p.old_id:26s} -> {p.new_id:26s}{sheet}")

    if plan.notes:
        print(f"\nnotes ({len(plan.notes)}):")
        for n in plan.notes[:20]:
            print(f"  - {n}")
        if len(plan.notes) > 20:
            print(f"  ... and {len(plan.notes) - 20} more")

    if plan.errors:
        print(f"\nBLOCKING ERRORS ({len(plan.errors)}) - nothing will be migrated:", file=sys.stderr)
        for e in plan.errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    orphans = count_orphan_bindings(library)
    if orphans and not a.allow_orphan_bindings:
        print(
            f"\nREFUSING: {orphans} registered project(s) hold `_sr_bound_part_id` bindings in "
            f"their OWN repos, which this migration cannot reach - renaming part ids here would "
            f"silently break them. Re-run with --allow-orphan-bindings once you have a plan for "
            f"re-binding them.",
            file=sys.stderr,
        )
        return 2

    if not a.apply:
        print("\n  Nothing was written. Re-run with --apply to perform the migration.")
        return 0

    if dirty and not a.allow_dirty:
        print(
            "\nREFUSING to migrate a DIRTY library tree: git could not fully undo this. Commit or "
            "stash the library's changes first, or pass --allow-dirty if you mean it.",
            file=sys.stderr,
        )
        return 2
    if not head and not a.allow_dirty:
        print(
            "\nREFUSING: the library is not a git repository, so there is no undo. Pass "
            "--allow-dirty to proceed anyway.",
            file=sys.stderr,
        )
        return 2

    touched = apply_migration(plan, library)
    print(f"\n  migrated. {len(touched)} path(s) touched.")
    print("  NOT COMMITTED, deliberately. Review it, then commit:")
    print(f"    git -C {library.as_posix()} status")
    if head:
        print(f"  To undo completely: git -C {library.as_posix()} checkout . && git clean -fd")
    print("  Then rebuild the derived index (it is keyed by part id).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
