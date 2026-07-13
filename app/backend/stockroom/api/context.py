"""The request-scoped engine bundle. Built once per app from the surveyed M1 to M4
constructors; NOT a re-implementation of any of them (spec sections 2.1, 4). The
derived index is kept warm and rebuilt on load, on profile switch, and after a pull
(spec section 2.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from stockroom.api.jobs import JobRunner
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.config import kicad_config_dir
from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.index import LibraryIndex
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile, ProfileStore
from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine


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
    jobs: JobRunner = field(default_factory=JobRunner)
    rendered_dom_fetcher: object | None = None  # RenderedDomFetcher; set by the host on Windows
    # App-repo self-update (updater.py): the CODE/UI/DATA repo (distinct from the
    # library repo above), a `uv sync` runner, and the host restart hook. All three
    # default to safe values so the fixture context imports and the routes mount
    # without a host present; serve.py (Task 14) attaches the real uv_sync + restart.
    app_repo: GitRepo | None = None
    uv_sync: Callable[[], None] = lambda: None
    request_restart: Callable[[], None] = lambda: None

    def rebuild_index(self) -> None:
        self.index.close()
        self.index = LibraryIndex.build(self.profile.library.parts_dir)

    def switch_profile(self, name: str) -> None:
        self.profile = self.profile_store.get(name)
        self.ops = LibraryOps(self.profile, self.repo, self.cli)
        self.config.active_profile = name
        self.config.save()
        self.rebuild_index()


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
    return AppContext(
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
        app_repo=app_repo,
    )
