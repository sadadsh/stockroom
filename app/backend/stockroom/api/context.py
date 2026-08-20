"""The request-scoped engine bundle. Built once per app from the surveyed M1 to M4
constructors; NOT a re-implementation of any of them (spec sections 2.1, 4). The
derived index is kept warm and rebuilt on load, on profile switch, and after a pull
(spec section 2.2)."""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from stockroom.api.jobs import JobRunner
from stockroom.enrich.cache import ensure_cache_dir
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.config import kicad_config_dir
from stockroom.mutation.library_ops import LibraryOps
from stockroom.mutation.project_ops import ProjectOps
from stockroom.projects.assembly import AssemblyRunStore
from stockroom.projects.collaboration_store import WorkSessionStore
from stockroom.store.index import LibraryIndex
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile, ProfileStore
from stockroom.store.project_index import ProjectIndex
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine

if TYPE_CHECKING:
    from stockroom.service import WorkflowCoordinator
    from stockroom.stm.db import StmIndex


class BackgroundSyncHandle(threading.Event):
    """Cancellation plus thread-completion ownership for periodic reconciliation.

    ``set``/``is_set``/``wait`` retain the former Event-shaped API for standalone
    hosts, while managed service handoff can now prove the worker actually left
    its generation instead of merely setting a flag and releasing authority.
    """

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None

    def bind(self, thread: threading.Thread) -> None:
        if self._thread is not None:
            raise RuntimeError("background sync handle is already bound")
        self._thread = thread

    def cancel(self) -> None:
        self.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()


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
    assembly_store: AssemblyRunStore
    work_session_store: WorkSessionStore
    # The STM32 pinout/spec index (stm-viewer workstream, Phase 3). LAZY, unlike `index`
    # above: no CubeMX source is synced at launch, so build_context only ATTEMPTS a load of
    # whatever is already on disk (default_index_path()) and accepts None (first run, a
    # stamp mismatch, or a missing/corrupt file are all legitimate, non-fatal outcomes).
    # `switch_library` deliberately leaves this untouched - the CubeMX source is a
    # machine-global setting, not library-scoped.
    stm_index: "StmIndex | None" = None
    # Read-only observability seam for the durable workflow owner. The desktop
    # context does not acquire generation authority or start/stop this resource;
    # the future persistent service process owns that lifecycle.
    workflow_coordinator: "WorkflowCoordinator | None" = None
    # The production host/worker binds these live authority fields. Source
    # development remains standalone unless the guard is explicitly enabled.
    service_authority_required: bool = False
    service_control: object | None = None
    service_fence: object | None = None
    service_generation: int = 0
    service_mode: str = "standalone"
    release_id: str = ""
    # Independent one-launch credential used only for the packaged worker readiness proof.
    startup_proof_token: str = ""
    # Sanitized fail-closed state for a packaged host whose signed built-in
    # release is intact but whose coordinator/update bootstrap could not start.
    # Never store the raw exception here: health is intentionally unauthenticated.
    service_degraded_reason: str = ""
    # The last ERC/DRC run per project id (M7b), cached in-memory (never committed to
    # the library repo: an external project's check results are not library records, and
    # a git commit per check run is churn). Read by the checks GET, Overview, and the
    # Buildability verdict (M7g) so those surfaces can never disagree; cleared on delete.
    checks_cache: dict = field(default_factory=dict)
    # The last built BOM per project id (M7c), cached in-memory like checks_cache (never
    # committed: a BOM is derived, and pricing is network-bound, so the cache lets a
    # re-open render instantly). Read by the BOM GET; cleared on delete.
    bom_cache: dict = field(default_factory=dict)
    # Native review checks are expensive and exact-commit immutable. Cache the
    # digest-bound result per candidate; a restart simply requires a new run.
    review_validation_cache: dict = field(default_factory=dict)
    # Process-local proof that a persisted session's remote claims were acquired
    # or reverified in this run. An app restart deliberately empties this set and
    # surfaces one explicit Resume step without polling the LFS server every 15s.
    work_session_verified: set[str] = field(default_factory=set)
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
    # Most recent automatic library convergence outcome. None means no attempt
    # has completed yet; failures remain observable instead of being swallowed.
    last_sync: object | None = None
    # Most recent automatic sourced -> derived refresh. Application/ruleset updates run this
    # without credentials, and the report stays observable even when one record cannot rebuild.
    last_derivation: dict | None = None
    # The explicitly injected kicad_dir (tests, embeddings), when one was given: a
    # settings change must never silently repoint it at the real machine config
    # (the review-confirmed footgun that let the test suite write into ~/.config).
    # Clearing an override returns HERE, not to autodetection.
    kicad_dir_pinned: Path | None = None
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        """Release the derived indexes owned by this context.

        A context built by the desktop host can outlive the window because its background-sync
        thread retains it.  Relying on garbage collection therefore leaves the SQLite files open,
        which is observable on Windows when an isolated app directory cannot be removed after the
        window closes.  Keep shutdown explicit and idempotent so host/test harness ownership is
        unambiguous.
        """
        if self._closed:
            return
        errors: list[Exception] = []
        for resource in (self.stm_index, self.index, self.project_index):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as exc:  # noqa: BLE001 - attempt every owned close before surfacing one
                errors.append(exc)
        if errors:
            raise errors[0]
        self.stm_index = None
        self._closed = True

    def rebuild_index(self) -> None:
        """Bring the index in line with the records. INCREMENTAL since 2026-07-27.

        This used to close the connection and rebuild from scratch, which re-read AND re-PARSED
        every record in the library. It runs after EVERY library write (eight call sites), so a
        one-field edit on a 10k-part library paid for 10k parses. `sync()` hashes each file's bytes
        and parses only what actually moved; on a single-part edit that is one parse, not n.
        """
        self.index.sync(self.profile.library.parts_dir)

    def refresh_stale_derivations(self) -> dict:
        """Bring older sourced records onto this build's ruleset and refresh the live index.

        This is the automatic half of the derivation stamp: an application update that changes
        description or normalization rules must not leave the old presentation in place until a
        person finds a Maintenance button. It is credential-free and fail-soft; unreadable or
        evidence-free records remain explicitly reported, and a newer peer's stamp is never
        downgraded.
        """
        from datetime import datetime, timezone

        from stockroom.model.derived import DERIVED_BY

        try:
            report = self.ops.rederive_library(
                now_iso=datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                only_outdated=True,
            )
        except Exception as exc:  # noqa: BLE001 - a derivation issue must not kill the desktop
            report = {
                "ruleset": DERIVED_BY,
                "checked": 0,
                "rewritten": 0,
                "failed": [{"id": "", "error": str(exc)}],
            }
        self.last_derivation = report
        if report.get("rewritten", 0):
            self.rebuild_index()
            # A derivation commit is a normal library write. Push when this machine is configured
            # to do so; otherwise the commit remains local and the next Sync carries it.
            self.auto_push()
        return report

    def rebuild_stm_index(self, source: Path | None = None, progress=None) -> None:
        """Build the STM index from `source` (falling back to the configured
        stm_cubemx_source, then stm.source's own env-var/candidate-path discovery)
        into the per-machine index path, closing any existing stm_index and
        swapping the new one in. Mirrors rebuild_index/rebuild_project_index's
        close-then-rebuild-then-swap shape. A build error propagates to the caller
        (the JobRunner work closure surfaces it as an SSE error event) - never
        swallowed here."""
        from stockroom.stm.db import StmIndex
        from stockroom.stm.source import (
            default_cubemx_source,
            default_index_path,
            normalize_cubemx_source,
        )

        resolved_source = (
            source
            or (Path(self.config.stm_cubemx_source) if self.config.stm_cubemx_source else None)
            or default_cubemx_source()
        )
        if resolved_source is None:
            raise ValueError(
                "No STM32CubeMX source folder is configured or discoverable. "
                "Choose the CubeMX data folder in Stockroom."
            )
        resolved_source = normalize_cubemx_source(Path(resolved_source))
        old_stm_index = self.stm_index
        self.stm_index = StmIndex.build(resolved_source, default_index_path(), progress=progress)
        if old_stm_index is not None:
            old_stm_index.close()

    def auto_push(self) -> None:
        """Converge a committed library write and retain the honest result for the UI.

        The write itself remains successful when the network, credentials, or remote history
        blocks synchronization.  Unlike the retired best-effort path, the failure is not swallowed:
        :meth:`reconcile` records it in ``last_sync`` and rebuilds derived indexes after a pull.
        """

        self.reconcile()

    def reconcile(self) -> bool:
        """Sync with the remote and REBUILD the derived indexes when a pull brought anything in.

        The rebuild is the half that makes a pull visible: part records and project registrations
        are both committed into this same library repo, so new files on disk mean a stale SQLite
        index and a UI that shows the old library. `POST /api/sync` has always done this; the
        automatic paths call THIS so they cannot drift from the button.

        Returns True when something was pulled. Never raises: offline, no remote, no credential and
        a rejected fast-forward are all ordinary outcomes.
        """
        if not getattr(self.config, "sync_enabled", True):
            return False
        try:
            result = self.sync.sync()
        except Exception as exc:  # noqa: BLE001 - never break launch or the running app
            from stockroom.vcs.sync import SyncResult, SyncState

            self.last_sync = SyncResult(state=SyncState.DIVERGED, detail=str(exc))
            return False
        self.last_sync = result
        if getattr(result, "pulled", False):
            # A peer may have contributed records from the previous application ruleset. Refresh
            # those before exposing the pulled tree through the derived index.
            self.refresh_stale_derivations()
            self.rebuild_index()
            self.rebuild_project_index()
            return True
        return False

    def start_background_sync(
        self,
        interval_seconds: float = 120.0,
    ) -> BackgroundSyncHandle:
        """Keep reconciling for as long as the app runs, not only at launch.

        Owner, 2026-07-26: "it shouldnt need to relaunch". A launch-only pull still leaves a window
        that has been open for an hour showing a library from an hour ago, which is the same
        staleness in slower motion. Mirrors the update check the rail already runs on an interval
        for exactly this reason.

        The returned handle owns both cancellation and completion. The per-repo
        write lock makes a background pull safe against a concurrent local write;
        generation handoff additionally joins this worker before releasing its
        durable fence.
        """
        if (
            type(interval_seconds) not in {int, float}
            or not math.isfinite(float(interval_seconds))
            or float(interval_seconds) <= 0
        ):
            raise ValueError("interval_seconds must be positive and finite")
        handle = BackgroundSyncHandle()

        def loop() -> None:
            while not handle.wait(interval_seconds):
                self.reconcile()

        thread = threading.Thread(
            target=loop,
            name="stockroom-sync-loop",
            daemon=False,
        )
        handle.bind(thread)
        thread.start()
        return handle

    def sync_on_launch(self) -> None:
        """Reconcile this machine's library with the remote once, at startup.

        `auto_push` above only ever runs AFTER a local write, so a device that has not added a part
        never pulls at all. That is not theoretical: this owner's library existed as TWO diverged
        checkouts on ONE machine, and the one the app actually READ sat ten commits behind, showing
        a single part and looking complete. Nothing had failed; nothing had pulled.

        Reuses `LibrarySync.sync()` - pull fast-forward, then push when ahead - rather than
        reimplementing it, so this and the Sync button cannot drift apart. Fast-forward only, so a
        launch never rebases or merges anything behind the user's back; a genuine divergence still
        surfaces on the Sync surface where it can be read and decided.

        Deliberately not gated on an app-owned GitHub token. Git's credential helper owns both
        pull and push authentication, so every Windows user signs into their own account and a
        public read still needs no credential.

        Best-effort and silent about failure, for the same reason auto_push is: offline, no remote,
        no credential and a rejected fast-forward are all ordinary, and none of them may stop the
        window opening.
        """
        self.reconcile()

    def rebuild_project_index(self) -> None:
        # Projects live repo-level (profile-independent), so this rebuilds from the same
        # <libraries_root>/.projects dir the store writes to; called after register/delete.
        self.project_index.close()
        self.project_index = ProjectIndex.build(self.libraries_root / ".projects")

    def ensure_derived_artifacts(self) -> None:
        """Rebuild the per-tool DERIVED artifacts this library needs on disk, committing nothing.

        Today that is Altium's SQLite data source, which stopped being committed on 2026-07-25 (see
        `eda.registry` `_ALTIUM.derived`). Committing it had bought "a fresh clone is placeable with
        no regenerate step"; rebuilding it here buys the same thing without sharing a binary two
        peers can never merge. Called on boot and on every profile/library switch, so the file is
        already there and current before anyone opens Altium.

        Never raises: a library that cannot produce a data source (an unreadable record, a
        read-only disk) must not stop the app from booting. The Altium surface reports the file's
        absence honestly, which is a better failure than a dead launch.
        """
        # An empty canonical library is a valid, intentional state during vNext rebuild and first
        # run. Emitting an empty SQLite/DbLib pair into it just because the app was opened is still
        # a write to canonical data, and it recreated files immediately after the owner deleted
        # the old library. Publication owns materialization; read/boot does not.
        if next(self.profile.library.parts_dir.glob("*.json"), None) is None:
            return
        try:
            self.ops.ensure_altium_datasource()
        except Exception:  # noqa: BLE001 - best-effort; the surface reports the gap instead
            pass

    def configure_repository_auth(self) -> None:
        """Apply the configured GitHub credential to this library repository.

        This can update ``.git/config``. Managed hosts therefore call it only from
        the coordinator lifecycle after acquiring the exact service generation.
        """

        try:
            from stockroom.vcs import github_auth

            legacy_token = getattr(self.config, "github_token", "")
            if legacy_token:
                github_auth.configure(self.repo, legacy_token)
            else:
                # Scrub only the unsafe historical config header. Do not reject GCM's migrated
                # credential on every later boot merely because Stockroom's compatibility field
                # is intentionally blank.
                self.repo.unset_config(github_auth.EXTRAHEADER_KEY)
            if legacy_token:
                # One-way migration only. GCM now owns the exact-repository credential; Stockroom
                # immediately erases its compatibility copy and never accepts a replacement PAT.
                self.config.github_token = ""
                self.config.save()
        except Exception:  # noqa: BLE001 - auth config is best-effort at boot
            pass

    def load_stm_index(self, *, restore_baked: bool) -> None:
        """Load the machine STM index, optionally restoring the packaged seed.

        Opening an existing index is read-only in intent, while restoring the seed
        writes machine state. Managed cold construction does neither; the promoted
        coordinator performs this bounded initialization instead.
        """

        if self.stm_index is not None:
            return
        try:
            from stockroom.stm.db import StmIndex
            from stockroom.stm.source import default_index_path

            path = default_index_path()
            self.stm_index = StmIndex.load(path)
            if self.stm_index is None and restore_baked:
                from stockroom.stm.seed import restore_baked_index

                if restore_baked_index(path):
                    self.stm_index = StmIndex.load(path)
        except Exception:  # noqa: BLE001 - missing/stale/corrupt STM data is non-fatal
            pass

    def reconcile_managed_boot(self) -> None:
        """Rehydrate current machine/library truth and reconcile it under authority.

        A release candidate is intentionally constructed cold before the previous
        owner drains. Settings, profiles, parts, and projects can all change in
        that interval. The acquired generation fence is therefore the boundary at
        which persisted configuration is reloaded and every root-derived engine
        is rebound in place before background work becomes reachable.
        """

        latest_config = self.config.reload(migrate_credentials=False)
        configured_root = latest_config.libraries_root.strip()
        latest_root = (
            Path(configured_root).expanduser()
            if configured_root
            else self.libraries_root
        )
        latest_repo = GitRepo(latest_root)
        latest_profiles = ProfileStore(latest_root, latest_repo)
        profile_names = latest_profiles.list()
        if not profile_names:
            raise RuntimeError("managed library has no usable profiles")
        repaired_profile = latest_config.active_profile not in profile_names
        if repaired_profile:
            latest_config.active_profile = profile_names[0]

        fresh = build_context(
            latest_root,
            kicad_dir=self.kicad_dir_pinned,
            config=latest_config,
            token=self.token,
            perform_boot_reconciliation=False,
        )
        old_index = self.index
        old_project_index = self.project_index
        self.__dict__.update(
            {
                name: getattr(fresh, name)
                for name in (
                    "libraries_root",
                    "repo",
                    "config",
                    "profile_store",
                    "profile",
                    "ops",
                    "index",
                    "sync",
                    "kicad_dir",
                    "cli",
                    "enrich_cache_dir",
                    "project_store",
                    "project_index",
                    "project_ops",
                    "assembly_store",
                    "work_session_store",
                )
            }
        )
        old_index.close()
        old_project_index.close()
        self.checks_cache.clear()
        self.bom_cache.clear()
        self.review_validation_cache.clear()
        self.work_session_verified.clear()

        self.config.migrate_legacy_credentials()
        config_source = self.config.source_path
        if repaired_profile and config_source is not None:
            self.config.save(config_source)
        ensure_cache_dir(self.enrich_cache_dir)
        self.configure_repository_auth()
        self.refresh_stale_derivations()
        # These scans are intentionally unconditional. The cold preflight indexes
        # may predate writes completed by the previous generation during drain.
        self.index.sync(self.profile.library.parts_dir)
        self.rebuild_project_index()
        self.ensure_derived_artifacts()
        self.load_stm_index(restore_baked=True)
        self.rewire_kicad()

    def rewire_kicad(self) -> None:
        """Repoint KiCad at the active profile (SR_LIB + table rows + category libs),
        never raising: auto_wire skips when KiCad is absent and captures failures
        into the report. Called on boot, on every switch, and on a KiCad settings
        change - the fix for SR_LIB going stale when the profile/library switched."""
        from stockroom.kicad.wiring import auto_wire

        explicit = self.kicad_dir_pinned is not None or bool(self.config.kicad_config_override)
        self.last_wiring = auto_wire(self.kicad_dir, self.profile, cli=self.cli, explicit=explicit)

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
        self.refresh_stale_derivations()
        self.rebuild_index()
        self.rewire_kicad()
        # Each profile has its own parts and therefore its own derived data source; without this
        # a switch would leave Altium reading the PREVIOUS profile's parts.
        self.ensure_derived_artifacts()

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
            "libraries_root",
            "repo",
            "profile_store",
            "profile",
            "ops",
            "index",
            "sync",
            "enrich_cache_dir",
            "project_store",
            "project_index",
            "project_ops",
            "assembly_store",
            "work_session_store",
            "last_derivation",
        ):
            setattr(self, name, getattr(fresh, name))
        old_index.close()
        old_project_index.close()
        self.checks_cache.clear()
        self.bom_cache.clear()
        self.config.libraries_root = str(new_root)
        self.config.save()
        self.rewire_kicad()
        self.ensure_derived_artifacts()


def build_context(
    libraries_root: Path,
    kicad_dir: Path | None = None,
    config: MachineConfig | None = None,
    token: str | None = None,
    *,
    perform_boot_reconciliation: bool = True,
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
    library_workflow_key = hashlib.sha256(
        str(libraries_root.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]
    assembly_store = AssemblyRunStore(
        libraries_root.parent / ".stockroom-project-workflows" / "assemblies" / library_workflow_key
    )
    work_session_store = WorkSessionStore(
        libraries_root.parent
        / ".stockroom-project-workflows"
        / "work-sessions"
        / library_workflow_key
    )
    kdir = (
        Path(kicad_dir)
        if kicad_dir is not None
        else kicad_config_dir(override=config.kicad_config_override)
    )
    enrich_cache = libraries_root.parent / ".stockroom-enrich-cache"
    if perform_boot_reconciliation:
        ensure_cache_dir(enrich_cache)
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
        assembly_store=assembly_store,
        work_session_store=work_session_store,
        app_repo=app_repo,
        kicad_dir_pinned=Path(kicad_dir) if kicad_dir is not None else None,
    )
    if perform_boot_reconciliation:
        # Mutable boot work is retained for standalone development callers. Managed
        # hosts pass False and invoke reconcile_managed_boot only after fencing.
        ctx.configure_repository_auth()
        ctx.refresh_stale_derivations()
        ctx.ensure_derived_artifacts()
        ctx.load_stm_index(restore_baked=True)
    return ctx
