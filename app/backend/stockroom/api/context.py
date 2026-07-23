"""The request-scoped engine bundle. Built once per app from the surveyed M1 to M4
constructors; NOT a re-implementation of any of them (spec sections 2.1, 4). The
derived index is kept warm and rebuilt on load, on profile switch, and after a pull
(spec section 2.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from stockroom.api.jobs import JobRunner
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.config import kicad_config_dir
from stockroom.mutation.library_ops import LibraryOps
from stockroom.mutation.project_ops import ProjectOps
from stockroom.store.index import LibraryIndex
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile, ProfileStore
from stockroom.store.project_index import ProjectIndex
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine

if TYPE_CHECKING:
    from stockroom.stm.db import StmIndex


@dataclass
class AppContext:
    libraries_root: Path
    repo: GitRepo
    config: MachineConfig
    profile_store: ProfileStore
    profile: Profile
    ops: LibraryOps
    index: LibraryIndex
    sync: SyncEngine
    kicad_dir: Path
    cli: KiCadCli
    enrich_cache_dir: Path
    token: str
    # Registered external KiCad projects (M7). They live REPO-LEVEL under
    # <libraries_root>/.projects (dot-prefixed so ProfileStore.list never treats it
    # as a profile) and are profile-independent, so switch_profile never touches them;
    # the derived project index is rebuilt on register/delete via rebuild_project_index.
    project_store: ProjectStore
    project_index: ProjectIndex
    project_ops: ProjectOps
    # The STM32 pinout/spec index (stm-viewer workstream, Phase 3). LAZY, unlike `index`
    # above: no CubeMX source is synced at launch, so build_context only ATTEMPTS a load of
    # whatever is already on disk (default_index_path()) and accepts None (first run, a
    # stamp mismatch, or a missing/corrupt file are all legitimate, non-fatal outcomes).
    # `switch_library` deliberately leaves this untouched - the CubeMX source is a
    # machine-global setting, not library-scoped.
    stm_index: "StmIndex | None" = None
    # The last ERC/DRC run per project id (M7b), cached in-memory (never committed to
    # the library repo: an external project's check results are not library records, and
    # a git commit per check run is churn). Read by the checks GET, Overview, and the
    # Buildability verdict (M7g) so those surfaces can never disagree; cleared on delete.
    checks_cache: dict = field(default_factory=dict)
    # The last built BOM per project id (M7c), cached in-memory like checks_cache (never
    # committed: a BOM is derived, and pricing is network-bound, so the cache lets a
    # re-open render instantly). Read by the BOM GET; cleared on delete.
    bom_cache: dict = field(default_factory=dict)
    jobs: JobRunner = field(default_factory=JobRunner)
    rendered_dom_fetcher: object | None = None  # RenderedDomFetcher; set by the host on Windows
    # App-repo self-update (updater.py): the CODE/UI/DATA repo (distinct from the
    # library repo above), a `uv sync` runner, and the host restart hook. All three
    # default to safe values so the fixture context imports and the routes mount
    # without a host present; serve.py (Task 14) attaches the real uv_sync + restart.
    app_repo: GitRepo | None = None
    uv_sync: Callable[[], None] = lambda: None
    request_restart: Callable[[], None] = lambda: None
    # The most recent automatic KiCad wiring outcome (a WiringReport: boot, profile
    # or library switch, or a KiCad settings change), so Doctor/Settings can surface
    # honestly what happened without re-running it. None until the first attempt.
    last_wiring: object | None = None
    # The explicitly injected kicad_dir (tests, embeddings), when one was given: a
    # settings change must never silently repoint it at the real machine config
    # (the review-confirmed footgun that let the test suite write into ~/.config).
    # Clearing an override returns HERE, not to autodetection.
    kicad_dir_pinned: Path | None = None

    def rebuild_index(self) -> None:
        self.index.close()
        self.index = LibraryIndex.build(self.profile.library.parts_dir)

    def auto_push(self) -> None:
        """After a library write, push it to the remote when a GitHub token is configured and sync
        is enabled, first rebasing to pick up any collaborator changes. Non-fatal: an offline /
        no-remote / auth / conflict failure never breaks the write (the change is already committed
        locally, and the next launch's pull + a Sync push it). So a part add lands in git
        immediately and reaches every collaborator on their next launch."""
        if not getattr(self.config, "sync_enabled", True):
            return
        if not (getattr(self.config, "github_token", "") or "").strip():
            return  # no credential yet; the commit stands locally, Sync pushes once a token is set
        try:
            if not self.repo.has_remote():
                return
            self.repo.pull_rebase()  # reconcile local commits with collaborators' changes first
            self.repo.push()
        except Exception:  # noqa: BLE001 - auto-push is best-effort; never break the write
            pass

    def rebuild_project_index(self) -> None:
        # Projects live repo-level (profile-independent), so this rebuilds from the same
        # <libraries_root>/.projects dir the store writes to; called after register/delete.
        self.project_index.close()
        self.project_index = ProjectIndex.build(self.libraries_root / ".projects")

    def rewire_kicad(self) -> None:
        """Repoint KiCad at the active profile (SR_LIB + table rows + category libs),
        never raising: auto_wire skips when KiCad is absent and captures failures
        into the report. Called on boot, on every switch, and on a KiCad settings
        change - the fix for SR_LIB going stale when the profile/library switched."""
        from stockroom.kicad.wiring import auto_wire

        explicit = self.kicad_dir_pinned is not None or bool(self.config.kicad_config_override)
        self.last_wiring = auto_wire(
            self.kicad_dir, self.profile, cli=self.cli, explicit=explicit
        )

    def apply_kicad_settings(self) -> None:
        """Rebuild every engine piece derived from the KiCad overrides LIVE (no
        restart): the cli, the ops that captured it, the effective config dir - then
        rewire so the new KiCad sees the active library immediately. A pinned
        (explicitly injected) kicad_dir is only ever moved by an explicit override,
        never silently repointed at the real machine config."""
        self.cli = KiCadCli(self.config.kicad_cli_override or None)
        self.ops = LibraryOps(self.profile, self.repo, self.cli)
        self.project_ops = ProjectOps(self.project_store, self.cli)
        if self.config.kicad_config_override:
            self.kicad_dir = kicad_config_dir(override=self.config.kicad_config_override)
        elif self.kicad_dir_pinned is not None:
            self.kicad_dir = self.kicad_dir_pinned
        else:
            self.kicad_dir = kicad_config_dir()
        self.rewire_kicad()

    def switch_profile(self, name: str) -> None:
        self.profile = self.profile_store.get(name)
        self.ops = LibraryOps(self.profile, self.repo, self.cli)
        self.config.active_profile = name
        self.config.save()
        self.rebuild_index()
        self.rewire_kicad()

    def switch_library(self, new_root: Path) -> None:
        """Repoint the whole engine at a different library root (M9b onboarding / switch),
        rebuilding every root-derived field IN PLACE while preserving the token, the
        host-wired hooks (request_restart, uv_sync, app_repo, rendered_dom_fetcher), and the
        job runner. The old library's per-project caches are dropped (they belong to the old
        library). Mirrors switch_profile but at the library root, so app.state.ctx keeps
        pointing at THIS same object: no pointer swap, no in-flight-request race, and the
        require_token closure (which captured this token) keeps authenticating.

        The target library must already be usable (a git-backed dir with the active profile);
        onboarding.set_library guarantees that before calling this."""
        new_root = Path(new_root)
        fresh = build_context(
            new_root, kicad_dir=self.kicad_dir, config=self.config, token=self.token
        )
        old_index, old_project_index = self.index, self.project_index
        for name in (
            "libraries_root", "repo", "profile_store", "profile", "ops", "index", "sync",
            "enrich_cache_dir", "project_store", "project_index", "project_ops",
        ):
            setattr(self, name, getattr(fresh, name))
        old_index.close()
        old_project_index.close()
        self.checks_cache.clear()
        self.bom_cache.clear()
        self.config.libraries_root = str(new_root)
        self.config.save()
        self.rewire_kicad()


def build_context(
    libraries_root: Path,
    kicad_dir: Path | None = None,
    config: MachineConfig | None = None,
    token: str | None = None,
) -> AppContext:
    from stockroom.api.security import mint_token

    libraries_root = Path(libraries_root)
    repo = GitRepo(libraries_root)
    config = config or MachineConfig.load()
    profile_store = ProfileStore(libraries_root, repo)
    profile = profile_store.get(config.active_profile)
    cli = KiCadCli(config.kicad_cli_override or None)
    ops = LibraryOps(profile, repo, cli)
    index = LibraryIndex.build(profile.library.parts_dir)
    # Registered external KiCad projects live repo-level (profile-independent) under a
    # dot-prefixed .projects dir so ProfileStore.list never sees it as a profile.
    projects_root = libraries_root / ".projects"
    project_store = ProjectStore(projects_root, repo)
    project_index = ProjectIndex.build(projects_root)
    project_ops = ProjectOps(project_store, cli)
    kdir = Path(kicad_dir) if kicad_dir is not None else kicad_config_dir(
        override=config.kicad_config_override
    )
    enrich_cache = libraries_root.parent / ".stockroom-enrich-cache"
    # The app repo is the git repo containing THIS package (the CODE/UI/DATA repo),
    # used only by the self-update route (updater.py). GitRepo needs git on PATH; if
    # it is absent we leave app_repo None so the update route surfaces the state
    # honestly rather than crash the whole context build. serve.py (Task 14) swaps in
    # the real uv_sync + restart hooks.
    from stockroom.vcs.repo import GitError

    app_repo_root = Path(__file__).resolve().parents[4]
    try:
        app_repo = GitRepo(app_repo_root)
    except GitError:
        app_repo = None
    ctx = AppContext(
        libraries_root=libraries_root,
        repo=repo,
        config=config,
        profile_store=profile_store,
        profile=profile,
        ops=ops,
        index=index,
        sync=SyncEngine(repo),
        kicad_dir=kdir,
        cli=cli,
        enrich_cache_dir=enrich_cache,
        token=token or mint_token(),
        project_store=project_store,
        project_index=project_index,
        project_ops=project_ops,
        app_repo=app_repo,
        kicad_dir_pinned=Path(kicad_dir) if kicad_dir is not None else None,
    )
    # Apply the configured GitHub credential to the library repo so push/pull authenticate
    # non-interactively (a recovery re-clone resets .git/config, so re-applying on every boot
    # keeps it live). Non-fatal: a non-git library or a git error never blocks the boot.
    try:
        from stockroom.vcs import github_auth

        github_auth.configure(repo, getattr(config, "github_token", ""))
    except Exception:  # noqa: BLE001 - auth config is best-effort; never crash the context build
        pass
    # Lazy STM index load: unlike `index`, no source is synced at launch, so this only picks
    # up whatever derived index already sits on disk (default_index_path()). None is a
    # legitimate result (first run, a stamp mismatch, or a missing/corrupt file) - never
    # treated as an error, and never blocks the boot.
    try:
        from stockroom.stm.db import StmIndex
        from stockroom.stm.source import default_index_path

        ctx.stm_index = StmIndex.load(default_index_path())
    except Exception:  # noqa: BLE001 - a missing/stale/corrupt STM index must never break the boot
        pass
    return ctx
