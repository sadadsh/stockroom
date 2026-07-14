"""Where the library lives on THIS machine, and whether first-run onboarding is needed (M9a).

The library lives INSIDE the app repo, at `<repo>/libraries`, committed and cloned with the
app: a frozen exe's launcher clones the app repo (code + the `libraries/` dir together), so a
fresh machine already carries the library and no first-run onboarding is needed. A completed
onboarding choice (`MachineConfig.libraries_root` + `onboarded`) still wins and repoints the app
at a different library on that machine. Pure, Qt-free.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.store.machine_config import MachineConfig

# The library committed inside the app repo: <repo>/libraries. The launcher clones the whole app
# repo, so this dir is present in every install (dev checkout AND frozen-exe managed checkout),
# and a clone of the app carries whatever parts have been committed to it.
IN_REPO_DEFAULT = Path(__file__).resolve().parents[4] / "libraries"


def resolve_libraries_root(config: MachineConfig) -> Path | None:
    """The effective library root: the persisted choice if set, else the in-repo dev
    library when it exists, else None (a frozen first run with nothing chosen yet, which
    the caller turns into onboarding rather than a crash)."""
    chosen = (config.libraries_root or "").strip()
    if chosen:
        return Path(chosen)
    if IN_REPO_DEFAULT.exists():
        return IN_REPO_DEFAULT
    return None


def library_is_initialized(root: Path | None) -> bool:
    """A usable library: an existing directory carrying at least one profile, i.e. a non-dot
    subdirectory (matching ProfileStore.list, which treats `.git` and any dot dir as never a
    profile). A missing, empty, or bare-git-only directory is NOT yet usable."""
    if root is None:
        return False
    root = Path(root)
    if not root.is_dir():
        return False
    return any(p.is_dir() and not p.name.startswith(".") for p in root.iterdir())


def needs_onboarding(config: MachineConfig) -> bool:
    """True when the app has no usable library yet and must run first-run onboarding: the
    location is unset (and no in-repo fallback) or points at a directory with no profile."""
    return not library_is_initialized(resolve_libraries_root(config))


def ships_in_repo(root: Path | None) -> bool:
    """True when `root` IS the library committed inside the app repo (`IN_REPO_DEFAULT`) and it
    carries a profile. This is the signal that the library came WITH the app (a clone of the repo
    already has it), so first-run onboarding is unnecessary and the app opens straight on it. A
    bootstrap placeholder or a user-chosen external library is NOT this, so onboarding still
    governs those."""
    if root is None:
        return False
    try:
        return Path(root).resolve() == IN_REPO_DEFAULT.resolve() and library_is_initialized(root)
    except OSError:
        return False
