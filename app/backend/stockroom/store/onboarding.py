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

from stockroom.store import library_location as _libloc
from stockroom.store.library_location import library_is_initialized, resolve_libraries_root
from stockroom.store.machine_config import MachineConfig, config_dir
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

_DEFAULT_PROFILE = "Main"


def default_library_dir() -> Path:
    """The USER-FACING default location for a fresh / cloned library when the user gives no
    explicit path: a `library` dir beside the per-machine config (writable + portable on every
    OS, and it travels with STOCKROOM_CONFIG_DIR so tests and portable installs stay
    self-contained). Kept DISTINCT from the boot placeholder below, so a first-run clone or
    create into the default is never blocked by the auto-created placeholder library."""
    return config_dir() / "library"


def _bootstrap_dir() -> Path:
    """A dedicated INTERNAL location for the auto-created boot placeholder library (so the
    server can start and serve the onboarding UI). Distinct from default_library_dir() on
    purpose: if bootstrap occupied the user default, a first-run clone/create into that
    default would always collide with it and fail."""
    return config_dir() / ".bootstrap-library"


def _same_path(a, b) -> bool:
    """Whether two paths point at the same location, resolving symlinks / separators. Falls back
    to a string compare if resolve() cannot stat (a nonexistent or malformed path)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def _ensure_git(root: Path) -> GitRepo:
    """A git repo at `root` (init its OWN repo if it has no `.git`; idempotent). An ONBOARDED
    library (open / create / clone) is its own repo even when its dir happens to sit inside an
    unrelated git checkout, so its part commits + sync never leak into that unrelated repo. The
    library committed inside the app repo is a DIFFERENT path (bootstrap_library's already-usable
    branch): it is backed by the enclosing app repo and never reaches _ensure_git, so it never
    gets a nested repo."""
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
    usable configured / in-repo library if there is one, else creates a placeholder library
    (at the configured path if one was set, else the internal boot dir) so the app can serve
    the onboarding UI."""
    # The library committed inside the app repo wins over an UNSET or bootstrap-PLACEHOLDER config
    # when onboarding was never completed: a fresh clone (config unset), or a machine whose config
    # only holds the auto-created placeholder, repoints at the shipped libraries/ and skips the
    # setup screen, so the app opens straight on whatever parts were committed to the repo. A REAL
    # configured library, or a COMPLETED onboarding choice, is never overridden. Referenced via the
    # module so a test that monkeypatches IN_REPO_DEFAULT (to simulate no in-repo library) is honored.
    if not config.onboarded and library_is_initialized(_libloc.IN_REPO_DEFAULT):
        chosen = (config.libraries_root or "").strip()
        in_repo = str(_libloc.IN_REPO_DEFAULT)
        if (not chosen or _same_path(chosen, _bootstrap_dir())) and chosen != in_repo:
            config.libraries_root = in_repo
            config.save()
    resolved = resolve_libraries_root(config)
    if library_is_initialized(resolved):
        # An already-usable library: repair a drifted active_profile (a cloned / pulled
        # library, or a config copied from another machine, may not carry this machine's
        # active-profile name) so the immediately-following build_context never 404s the
        # profile. Persist the resolved path when it was implicit. Never onboard here.
        store = ProfileStore(Path(resolved), GitRepo(Path(resolved)))
        names = store.list()
        changed = False
        if names and config.active_profile not in names:
            config.active_profile = names[0]
            changed = True
        if not (config.libraries_root or "").strip():
            config.libraries_root = str(resolved)
            changed = True
        if changed:
            config.save()
        return Path(resolved)
    # Not usable yet. If a PREVIOUSLY configured library is what went missing, re-show
    # onboarding rather than silently handing back a fresh empty library as if the user's
    # parts were never there; a genuine first run (no path set) uses the internal placeholder.
    was_configured = bool((config.libraries_root or "").strip())
    target = Path((config.libraries_root or "").strip() or _bootstrap_dir())
    target.mkdir(parents=True, exist_ok=True)
    lib = _finalize(target, config, onboarded=False)
    if was_configured and config.onboarded:
        config.onboarded = False
        config.save()
    return lib


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
        # Create means a FRESH library: refuse a path that is a file, or a non-empty directory
        # (which is likely a user's existing library or repo we must not commit into). This is
        # symmetric with clone's emptiness guard, and turns an opaque mkdir crash into a 400.
        if root.exists():
            if not root.is_dir():
                raise ValueError(f"not a directory: {root}")
            if any(root.iterdir()):
                raise ValueError(
                    f"directory is not empty: {root} (use Open to adopt an existing library)"
                )
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
