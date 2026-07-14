"""Where the library lives on THIS machine, and whether first-run onboarding is needed (M9a).

The library location is a per-machine choice (`MachineConfig.libraries_root`), never baked
into the app: a frozen exe ships no library, so on first run it is unset and the app must
onboard (open / clone / create a library repo) before any library feature works. A source
or dev checkout falls back to the in-repo `libraries/` dir when that exists. Pure, Qt-free.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.store.machine_config import MachineConfig

# The in-repo dev library: used ONLY for a source-checkout run (never present beside a
# frozen exe, which ships code only). Same path serve.build_context used as its former
# hardcoded default: <repo>/libraries.
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
