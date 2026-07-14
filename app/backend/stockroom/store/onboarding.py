"""M9b: first-run library onboarding (open / clone / create the library the app uses).

A frozen exe ships no library, so on first run the user must point the app at one: OPEN an
existing local library, CLONE a git URL, or CREATE a fresh empty one. Each path ends the
same way: a git-backed directory carrying at least one profile, its location persisted to
MachineConfig.libraries_root, and config.onboarded set so the welcome screen shows once.

bootstrap_library guarantees the server can ALWAYS boot (auto-creating a default library
when nothing usable is configured yet) so the onboarding UI has a running backend to talk
to, WITHOUT marking onboarding complete (the genuine first-run welcome still shows).

git clone goes through GitRepo.clone_from, which works offline from a local path, so the
whole flow is testable without the network. Qt-free (no host import).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.store.library_location import library_is_initialized, resolve_libraries_root
from stockroom.store.machine_config import MachineConfig, config_dir
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

_DEFAULT_PROFILE = "Main"


def default_library_dir() -> Path:
    """Where a fresh library is created / cloned when the user gives no explicit path: a
    `library` dir beside the per-machine config (writable + portable on every OS, and it
    travels with STOCKROOM_CONFIG_DIR so tests and portable installs stay self-contained)."""
    return config_dir() / "library"


def _ensure_git(root: Path) -> GitRepo:
    """A git repo at `root` (init if absent; idempotent on an existing repo). Sync + the
    project editors need git, so every onboarded library is git-backed."""
    repo = GitRepo(root)
    if not (root / ".git").exists():
        repo.init()
    return repo


def _ensure_profile(root: Path, repo: GitRepo, config: MachineConfig) -> None:
    """Guarantee the library carries a usable profile AND that config.active_profile names
    one that exists here (a library cloned from another machine may not carry this machine's
    active-profile name, which would 404 the profile on the next build_context)."""
    store = ProfileStore(root, repo)
    names = store.list()
    if not names:
        store.create(config.active_profile or _DEFAULT_PROFILE)
        names = store.list()
    if config.active_profile not in names:
        config.active_profile = names[0]


def _finalize(root: Path, config: MachineConfig, *, onboarded: bool) -> Path:
    """Make `root` a usable library (git + a profile), persist it as the library location,
    and (when onboarded) mark first-run complete. Returns the resolved root."""
    root = Path(root)
    repo = _ensure_git(root)
    _ensure_profile(root, repo, config)
    config.libraries_root = str(root)
    if onboarded:
        config.onboarded = True
    config.save()
    return root


def bootstrap_library(config: MachineConfig) -> Path:
    """Guarantee a usable library exists so the server can boot, WITHOUT completing
    onboarding (the welcome screen still shows on genuine first run). Returns the already
    usable configured / in-repo library if there is one, else creates a fresh default (at
    the configured-but-empty path if one was set, else default_library_dir())."""
    resolved = resolve_libraries_root(config)
    if library_is_initialized(resolved):
        # Persist the resolved path so a later switch/read is unambiguous, but do NOT onboard.
        if not (config.libraries_root or "").strip():
            config.libraries_root = str(resolved)
            config.save()
        return Path(resolved)
    target = Path((config.libraries_root or "").strip() or default_library_dir())
    target.mkdir(parents=True, exist_ok=True)
    return _finalize(target, config, onboarded=False)


def set_library(
    config: MachineConfig,
    mode: str,
    *,
    path: str | Path | None = None,
    url: str | None = None,
    dest: str | Path | None = None,
) -> Path:
    """Complete onboarding by pointing the app at a library. Modes:
      - "open":   use an existing local directory (must exist);
      - "create": make a fresh empty library (at `path`, else default_library_dir());
      - "clone":  git clone `url` into `dest` (else default_library_dir(); must be empty).
    Each ends git-backed + with a profile, persists the location, and marks onboarded.
    Raises ValueError on a bad request (mapped to 400 by the router)."""
    if mode == "open":
        if not path:
            raise ValueError("a library directory is required to open")
        root = Path(path)
        if not root.is_dir():
            raise ValueError(f"no such directory: {root}")
    elif mode == "create":
        root = Path(path) if path else default_library_dir()
        root.mkdir(parents=True, exist_ok=True)
    elif mode == "clone":
        if not (url or "").strip():
            raise ValueError("a git URL is required to clone a library")
        root = Path(dest) if dest else default_library_dir()
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"clone destination is not empty: {root}")
        GitRepo(root).clone_from(url.strip())
    else:
        raise ValueError(f"unknown onboarding mode: {mode!r} (expected open / create / clone)")
    return _finalize(root, config, onboarded=True)


def complete_onboarding(config: MachineConfig) -> None:
    """Dismiss the welcome screen keeping the current (e.g. auto-created default) library."""
    config.onboarded = True
    config.save()
