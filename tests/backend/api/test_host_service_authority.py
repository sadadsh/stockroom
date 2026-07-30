from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.global_windows_mutex

from stockroom.api.jobs import JobRunner, JobRunnerUnavailable
from stockroom.host.service_authority import (
    ContextServiceAuthority,
    ContextServiceLifecycle,
    ServiceDemotionError,
    ServicePromotionError,
)
from stockroom.service import (
    CoordinatorBusy,
    CoordinatorStatus,
    MutexAcquireResult,
    ServiceControl,
    ServiceMode,
)
from stockroom.workflow import (
    BatchStatus,
    CompletionOutcome,
    ExactIdentityOutcome,
    PublicationProposalOutcome,
    StageName,
    WorkflowStore,
)
from stockroom.workflow.store import SCHEMA_VERSION

_SID = "S-1-5-21-111111111-222222222-333333333-1001"


class _Identity:
    def current_sid(self) -> str:
        return _SID


class _Storage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class _ThreadAffineMutex:
    """Test mutex that rejects cross-thread release like Win32 does."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held = False
        self._owner_thread_id: int | None = None
        self.owner_history: list[int] = []
        self.release_history: list[int] = []

    def try_acquire(self) -> MutexAcquireResult:
        thread_id = threading.get_ident()
        with self._lock:
            if self._held:
                return MutexAcquireResult.BUSY
            self._held = True
            self._owner_thread_id = thread_id
            self.owner_history.append(thread_id)
            return MutexAcquireResult.CREATED

    def release(self) -> None:
        thread_id = threading.get_ident()
        with self._lock:
            if not self._held or self._owner_thread_id != thread_id:
                raise RuntimeError("named mutex release crossed its owner thread")
            self._held = False
            self._owner_thread_id = None
            self.release_history.append(thread_id)


class _MutexFactory:
    def __init__(self, mutex: _ThreadAffineMutex) -> None:
        self._mutex = mutex

    def open_current_user(self, *, name: str, sid: str) -> _ThreadAffineMutex:
        del name, sid
        return self._mutex


def _control_factories(database: Path):
    mutex = _ThreadAffineMutex()
    mutex_factory = _MutexFactory(mutex)

    def shadow() -> ServiceControl:
        return ServiceControl(
            database,
            mode=ServiceMode.SHADOW,
            identity=_Identity(),
            storage_policy=_Storage(),
        )

    def coordinator() -> ServiceControl:
        return ServiceControl(
            database,
            mode=ServiceMode.COORDINATOR,
            identity=_Identity(),
            mutex_factory=mutex_factory,
            storage_policy=_Storage(),
        )

    return mutex, shadow, coordinator


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


class _CompletingRegistry(dict):
    """Complete test registry with a real durable publication executor."""

    def __init__(self, store: WorkflowStore) -> None:
        self.store = store

        def handle(context):
            if context.stage.name is StageName.IDENTITY_DEDUPE:
                return ExactIdentityOutcome(
                    authoritative_manufacturer_key=(
                        context.item.manufacturer_key or "unknown-manufacturer"
                    ),
                    mpn_canonical=context.item.mpn,
                    registry_revision="host-integration-registry-v1",
                    rule_revision="host-integration-rules-v1",
                    evidence={"source": "host-integration"},
                )
            if context.stage.name is StageName.PUBLISH:
                return PublicationProposalOutcome(
                    candidate_digest=_digest(f"candidate:{context.item.id}"),
                    manifest_digest=_digest(f"manifest:{context.item.id}"),
                    expected_base_commit="host-integration-base",
                )
            return CompletionOutcome({"stage": context.stage.name.value})

        super().__init__({stage: handle for stage in StageName})

    def execute_publication(self, lease, *, now=None):
        del now
        credentials = {
            "lease_token": lease.lease_token,
            "lease_generation": lease.lease_generation,
        }
        self.store.arm_publication_commit(
            lease.publication_id,
            lease.worker_id,
            **credentials,
        )
        self.store.record_git_commit(
            lease.publication_id,
            lease.worker_id,
            git_commit_oid="host-integration-commit",
            verified_tree_digest=_digest("host-integration-tree"),
            **credentials,
        )
        self.store.record_catalog_activation(
            lease.publication_id,
            lease.worker_id,
            catalog_revision="host-integration-catalog",
            catalog_semantic_digest=_digest("host-integration-catalog"),
            **credentials,
        )
        return self.store.complete_publication(
            lease.publication_id,
            lease.worker_id,
            {"activated": True},
            **credentials,
        )


class _BlockingActivity:
    """A cancellation-aware activity that withholds completion until released."""

    def __init__(self, *, start_thread: bool = True) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()
        self.thread: threading.Thread | None = None
        if start_thread:
            self.thread = threading.Thread(target=self._run, daemon=False)
            self.thread.start()

    def _run(self) -> None:
        self.started.set()
        self.release.wait()

    def cancel(self) -> None:
        self.cancelled.set()

    set = cancel

    def join(self, timeout: float | None = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


def test_service_transitions_keep_win32_mutex_on_one_owner_thread(
    tmp_path: Path,
) -> None:
    database = (tmp_path / "Control.sqlite").resolve()
    mutex, shadow_factory, coordinator_factory = _control_factories(database)
    context = type("Context", (), {})()
    lifecycle_threads: list[tuple[str, int]] = []

    class Lifecycle:
        def start(self, control, fence):
            del control
            lifecycle_threads.append(("start", threading.get_ident()))
            return fence

        def stop(self, handle, *, timeout):
            del handle, timeout
            lifecycle_threads.append(("stop", threading.get_ident()))

    authority = ContextServiceAuthority(
        context,
        release_id="release-current",
        control_database=database,
        lifecycle=Lifecycle(),
        start_as_coordinator=True,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        first = authority.snapshot()
        assert first.mode is ServiceMode.COORDINATOR
        assert first.generation == 1

        released = authority.demote(expected_generation=first.generation)
        assert released.mode is ServiceMode.SHADOW
        assert released.generation == first.generation
        assert getattr(context, "service_fence") is None

        second = authority.promote(expected_generation=released.generation)
        assert second.mode is ServiceMode.COORDINATOR
        assert second.generation == 2
    finally:
        authority.close()
        authority.close()

    assert len(set(mutex.owner_history + mutex.release_history)) == 1
    assert mutex.owner_history == mutex.release_history
    assert len({thread_id for _, thread_id in lifecycle_threads}) == 1
    assert mutex.owner_history[0] != threading.get_ident()


@pytest.mark.parametrize("blocked_activity", ["launch", "background"])
def test_demote_retains_fence_until_every_sync_activity_is_joined(
    tmp_path: Path,
    blocked_activity: str,
) -> None:
    database = (tmp_path / blocked_activity / "Control.sqlite").resolve()
    workflow_database = (
        tmp_path / blocked_activity / "Workflow.sqlite"
    ).resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)
    activity = _BlockingActivity(
        start_thread=blocked_activity == "background"
    )

    class Context:
        workflow_coordinator = None

        def sync_on_launch(self) -> None:
            if blocked_activity == "launch":
                activity.started.set()
                activity.release.wait()

        @staticmethod
        def start_background_sync() -> object:
            if blocked_activity == "background":
                return activity
            return threading.Event()

    context = Context()
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(
            store
        ),
        enable_altium=False,
        require_publication_executor=True,
    )
    authority = ContextServiceAuthority(
        context,
        release_id=f"release-{blocked_activity}",
        control_database=database,
        lifecycle=lifecycle,
        start_as_coordinator=True,
        transition_timeout_seconds=0.05,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        initial = authority.snapshot()
        assert activity.started.wait(2.0)

        with pytest.raises(ServiceDemotionError):
            authority.demote(expected_generation=initial.generation)

        retained = authority.snapshot()
        assert retained.mode is ServiceMode.COORDINATOR
        assert retained.status is CoordinatorStatus.ACTIVE
        assert retained.generation == initial.generation
        assert getattr(context, "service_fence") is None
        if blocked_activity == "background":
            assert activity.cancelled.is_set()
        with pytest.raises(ServicePromotionError):
            authority.promote(expected_generation=initial.generation)

        competing = coordinator_factory()
        with pytest.raises(CoordinatorBusy):
            competing.acquire()
        competing.close()

        activity.release.set()
        released = authority.demote(expected_generation=initial.generation)
        assert released.mode is ServiceMode.SHADOW
        assert released.status is CoordinatorStatus.RELEASED
    finally:
        activity.release.set()
        authority.close()


def test_failed_start_holds_candidate_fence_until_started_sync_is_joined(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = (tmp_path / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Workflow.sqlite").resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)
    activity = _BlockingActivity()
    launch_attempted = threading.Event()

    class Context:
        workflow_coordinator = None

        @staticmethod
        def sync_on_launch() -> None:
            return None

        @staticmethod
        def start_background_sync() -> _BlockingActivity:
            return activity

    context = Context()
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(
            store
        ),
        enable_altium=False,
        require_publication_executor=True,
    )

    def fail_launch(_generation: int):
        launch_attempted.set()
        raise RuntimeError("synthetic launch-thread failure")

    monkeypatch.setattr(lifecycle, "_start_launch_sync", fail_launch)
    errors: list[BaseException] = []

    def construct() -> None:
        try:
            ContextServiceAuthority(
                context,
                release_id="release-failed-start",
                control_database=database,
                lifecycle=lifecycle,
                start_as_coordinator=True,
                transition_timeout_seconds=0.05,
                shadow_factory=shadow_factory,
                coordinator_factory=coordinator_factory,
            )
        except BaseException as exc:
            errors.append(exc)

    constructor = threading.Thread(target=construct, daemon=False)
    constructor.start()
    assert activity.started.wait(2.0)
    assert launch_attempted.wait(2.0)
    assert activity.cancelled.wait(2.0)
    assert constructor.is_alive()

    competing = coordinator_factory()
    with pytest.raises(CoordinatorBusy):
        competing.acquire()

    activity.release.set()
    constructor.join(2.0)
    assert not constructor.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ServicePromotionError)

    fence = competing.acquire()
    competing.release(fence)
    competing.close()


def test_job_generation_blocks_new_work_and_retains_fence_until_executor_join(
    tmp_path: Path,
) -> None:
    database = (tmp_path / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Workflow.sqlite").resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)
    started = threading.Event()
    release = threading.Event()

    class Context:
        workflow_coordinator = None
        jobs = JobRunner(max_workers=1)

        @staticmethod
        def sync_on_launch() -> None:
            return None

        @staticmethod
        def start_background_sync() -> threading.Event:
            return threading.Event()

    context = Context()
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(
            store
        ),
        enable_altium=False,
        require_publication_executor=True,
    )
    with pytest.raises(JobRunnerUnavailable):
        context.jobs.submit(lambda _progress: None)

    authority = ContextServiceAuthority(
        context,
        release_id="release-jobs",
        control_database=database,
        lifecycle=lifecycle,
        start_as_coordinator=True,
        transition_timeout_seconds=0.05,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        initial = authority.snapshot()

        def blocked(_progress):
            started.set()
            release.wait()
            return "finished"

        job_id = context.jobs.submit(blocked, write=True)
        assert started.wait(2.0)
        assert context.jobs.get(job_id).generation == initial.generation

        with pytest.raises(ServiceDemotionError):
            authority.demote(expected_generation=initial.generation)
        assert not context.jobs.accepting
        with pytest.raises(JobRunnerUnavailable):
            context.jobs.submit(lambda _progress: None)

        retained = authority.snapshot()
        assert retained.status is CoordinatorStatus.ACTIVE
        assert retained.generation == initial.generation
        competing = coordinator_factory()
        with pytest.raises(CoordinatorBusy):
            competing.acquire()
        competing.close()

        release.set()
        released = authority.demote(expected_generation=initial.generation)
        assert released.status is CoordinatorStatus.RELEASED

        promoted = authority.promote(
            expected_generation=released.generation
        )
        next_job = context.jobs.run_sync(lambda _progress: "next")
        assert next_job.generation == promoted.generation
        assert next_job.generation == initial.generation + 1
    finally:
        release.set()
        authority.close()


def test_real_app_context_mounts_every_stage_before_authority_and_api_reaches_terminal(
    client,
    app_ctx,
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = (tmp_path / "Service" / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Service" / "Workflow.sqlite").resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)
    registry_holder: list[_CompletingRegistry] = []

    monkeypatch.setattr(app_ctx, "sync_on_launch", lambda: None)
    monkeypatch.setattr(
        app_ctx,
        "start_background_sync",
        lambda: threading.Event(),
    )
    def build_registry(context, workflow_store: WorkflowStore):
        del context
        registry = _CompletingRegistry(workflow_store)
        registry_holder.append(registry)
        return registry

    lifecycle = ContextServiceLifecycle(
        app_ctx,
        workflow_database=workflow_database,
        workflow_registry_factory=build_registry,
        enable_altium=False,
        require_publication_executor=True,
    )
    assert registry_holder == []
    assert not workflow_database.exists()
    authority = ContextServiceAuthority(
        app_ctx,
        release_id="release-current",
        control_database=database,
        lifecycle=lifecycle,
        start_as_coordinator=True,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        initial = authority.snapshot()
        coordinator = app_ctx.workflow_coordinator
        assert initial.mode is ServiceMode.COORDINATOR
        assert len(registry_holder) == 1
        assert set(registry_holder[0]) == set(StageName)
        assert registry_holder[0].store.database == workflow_database
        assert coordinator is not None
        assert coordinator.status().state.value == "running"
        assert coordinator.status().thread_alive

        submitted = client.post(
            "/api/library/completion/run",
            json={"part_ids": ["tps62130"]},
            headers={"Idempotency-Key": "host-authority-integration"},
        )
        assert submitted.status_code == 200
        batch_id = submitted.json()["workflow_batch_id"]
        deadline = time.monotonic() + 5.0
        while (
            coordinator.get_batch(batch_id).status is not BatchStatus.COMPLETED
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert coordinator.get_batch(batch_id).status is BatchStatus.COMPLETED

        released = authority.demote(expected_generation=initial.generation)
        assert released.mode is ServiceMode.SHADOW
        assert app_ctx.workflow_coordinator is None
        assert coordinator.status().state.value == "stopped"
        assert not coordinator.status().thread_alive
        blocked = client.post(
            "/api/library/completion/run",
            json={"part_ids": ["tps62130"]},
        )
        assert blocked.status_code == 503

        promoted = authority.promote(expected_generation=released.generation)
        restarted = app_ctx.workflow_coordinator
        assert promoted.generation == initial.generation + 1
        assert restarted is not None
        assert restarted is not coordinator
        assert len(registry_holder) == 2
        assert registry_holder[1].store is not registry_holder[0].store
        assert registry_holder[1].store.database == workflow_database
        assert restarted.status().state.value == "running"
        assert restarted.status().thread_alive
    finally:
        running = app_ctx.workflow_coordinator
        authority.close()
    assert app_ctx.service_fence is None
    assert running is not None
    assert running.status().state.value == "stopped"
    assert not running.status().thread_alive


def test_managed_shadow_keeps_context_git_config_and_machine_config_cold(
    library_root: Path,
    tmp_path: Path,
) -> None:
    from stockroom.api.serve import build_context
    from stockroom.store.machine_config import config_dir

    machine_config_path = config_dir() / "config.json"
    machine_config_path.parent.mkdir(parents=True, exist_ok=True)
    machine_config_path.write_text(
        json.dumps(
            {
                "active_profile": "Main",
                "github_token": "legacy-plaintext-token",
                "libraries_root": str(library_root),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git_config = library_root / ".git" / "config"
    config_before = machine_config_path.read_bytes()
    git_config_before = git_config.read_bytes()
    worktree_before = {
        path.relative_to(library_root).as_posix(): path.read_bytes()
        for path in library_root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(library_root).parts
    }
    kicad_dir = tmp_path / "Candidate KiCad"
    control_database = (tmp_path / "Service" / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Service" / "Workflow.sqlite").resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(control_database)
    current = coordinator_factory()
    current_fence = current.acquire()

    context = build_context(kicad_dir=kicad_dir, cold=True)
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(store),
        enable_altium=False,
        require_publication_executor=True,
    )
    candidate = ContextServiceAuthority(
        context,
        release_id="release-candidate",
        control_database=control_database,
        lifecycle=lifecycle,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        assert candidate.snapshot().mode is ServiceMode.SHADOW
        assert not workflow_database.exists()
        assert machine_config_path.read_bytes() == config_before
        assert git_config.read_bytes() == git_config_before
        assert not kicad_dir.exists()
        assert {
            path.relative_to(library_root).as_posix(): path.read_bytes()
            for path in library_root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(library_root).parts
        } == worktree_before
    finally:
        candidate.close()
        context.close()
        current.release(current_fence)
        current.close()


def test_promotion_rehydrates_latest_config_profile_parts_and_projects(
    library_root: Path,
    tmp_path: Path,
) -> None:
    from stockroom.api.serve import build_context
    from stockroom.model.part import PartRecord
    from stockroom.model.project import ProjectRecord
    from stockroom.store.machine_config import config_dir
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    machine_config_path = config_dir() / "config.json"
    machine_config_path.parent.mkdir(parents=True, exist_ok=True)
    machine_config_path.write_text(
        json.dumps(
            {
                "active_profile": "Main",
                "libraries_root": str(library_root),
                "rescan_ttl_days": 7,
                "sync_enabled": False,
                "ui": {"theme": "dark"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    database = (tmp_path / "Service" / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Service" / "Workflow.sqlite").resolve()
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)
    current = coordinator_factory()
    current_fence = current.acquire()
    current_released = False

    context = build_context(kicad_dir=tmp_path / "Candidate KiCad", cold=True)
    assert context.profile.name == "Main"
    assert context.index.get("late-part") is None
    assert context.project_index.get("late-project") is None
    lifecycle = ContextServiceLifecycle(
        context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(
            store
        ),
        enable_altium=False,
        require_publication_executor=True,
    )
    candidate = ContextServiceAuthority(
        context,
        release_id="release-candidate",
        control_database=database,
        lifecycle=lifecycle,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        # These mutations occur after candidate preflight but before the previous
        # generation releases. Promotion must not resurrect the earlier snapshot.
        latest_root = tmp_path / "Latest Libraries"
        latest_root.mkdir()
        latest_repo = GitRepo(latest_root)
        latest_repo.init()
        profile = ProfileStore(latest_root, latest_repo).create("Alt")
        part = PartRecord(
            id="late-part",
            display_name="Late Part",
            category="ICs",
            description="persisted during handoff",
            mpn="LATE-1",
            manufacturer="Transfer Labs",
        )
        (profile.library.parts_dir / "late-part.json").write_text(
            part.dumps(),
            encoding="utf-8",
        )
        projects_dir = latest_root / ".projects"
        projects_dir.mkdir(parents=True, exist_ok=True)
        project = ProjectRecord(
            id="late-project",
            name="Late Project",
            root=str(tmp_path / "Late Project"),
            registered_at="2026-07-29T12:00:00Z",
        )
        (projects_dir / "late-project.json").write_text(
            project.dumps(),
            encoding="utf-8",
        )
        machine_config_path.write_text(
            json.dumps(
                {
                    "active_profile": "Alt",
                    "libraries_root": str(latest_root),
                    "rescan_ttl_days": 31,
                    "sync_enabled": False,
                    "ui": {"theme": "light", "density": "compact"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        current.release(current_fence)
        current_released = True
        promoted = candidate.promote(
            expected_generation=current_fence.generation
        )

        assert promoted.generation == current_fence.generation + 1
        assert context.config.active_profile == "Alt"
        assert context.config.rescan_ttl_days == 31
        assert context.config.ui == {
            "theme": "light",
            "density": "compact",
        }
        assert context.libraries_root == latest_root
        assert context.repo.root == latest_root
        assert context.profile.name == "Alt"
        assert context.profile.root == profile.root
        assert context.index.get("late-part") is not None
        assert context.project_index.get("late-project") is not None
        assert context.jobs.managed_generation == promoted.generation
        assert context.jobs.accepting
    finally:
        candidate.close()
        context.close()
        if not current_released:
            current.release(current_fence)
        current.close()


def test_shadow_defers_workflow_schema_and_registry_markers_until_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import stockroom.host.service_authority as authority_module

    database = (tmp_path / "Service" / "Control.sqlite").resolve()
    workflow_database = (tmp_path / "Service" / "Workflow.sqlite").resolve()
    registry_marker = tmp_path / "Registry Marker"
    reconcile_marker = tmp_path / "Reconcile Marker"
    _mutex, shadow_factory, coordinator_factory = _control_factories(database)

    class Context:
        workflow_coordinator = None

        @staticmethod
        def sync_on_launch() -> None:
            return None

        @staticmethod
        def start_background_sync() -> threading.Event:
            return threading.Event()

    current_context = Context()
    current_lifecycle = ContextServiceLifecycle(
        current_context,
        workflow_database=workflow_database,
        workflow_registry_factory=lambda _context, store: _CompletingRegistry(store),
        enable_altium=False,
        require_publication_executor=True,
    )
    current = ContextServiceAuthority(
        current_context,
        release_id="release-current",
        control_database=database,
        lifecycle=current_lifecycle,
        start_as_coordinator=True,
        shadow_factory=shadow_factory,
        coordinator_factory=coordinator_factory,
    )
    try:
        with sqlite3.connect(workflow_database) as connection:
            assert (
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                == SCHEMA_VERSION
            )

        original_store = authority_module.WorkflowStore

        class NextSchemaWorkflowStore(original_store):
            def __init__(self, path: str | Path) -> None:
                super().__init__(path)
                with self._writing() as connection:
                    connection.execute(
                        "CREATE TABLE shadow_promotion_marker "
                        "(value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) "
                        "VALUES (?, ?)",
                        (SCHEMA_VERSION + 1, time.time()),
                    )

        monkeypatch.setattr(
            authority_module,
            "WorkflowStore",
            NextSchemaWorkflowStore,
        )

        candidate_context = Context()
        candidate_context.reconcile_managed_boot = (
            lambda: reconcile_marker.write_text(
                "promoted",
                encoding="utf-8",
            )
        )

        def candidate_registry(_context, store):
            registry_marker.mkdir()
            return _CompletingRegistry(store)

        candidate_lifecycle = ContextServiceLifecycle(
            candidate_context,
            workflow_database=workflow_database,
            workflow_registry_factory=candidate_registry,
            enable_altium=False,
            require_publication_executor=True,
        )
        candidate = ContextServiceAuthority(
            candidate_context,
            release_id="release-next",
            control_database=database,
            lifecycle=candidate_lifecycle,
            shadow_factory=shadow_factory,
            coordinator_factory=coordinator_factory,
        )
        try:
            assert candidate.snapshot().mode is ServiceMode.SHADOW
            assert not registry_marker.exists()
            assert not reconcile_marker.exists()
            with sqlite3.connect(workflow_database) as connection:
                assert (
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    == SCHEMA_VERSION
                )
                assert (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type='table' "
                        "AND name='shadow_promotion_marker'"
                    ).fetchone()
                    is None
                )

            released = current.demote(
                expected_generation=current.snapshot().generation
            )
            promoted = candidate.promote(
                expected_generation=released.generation
            )
            assert promoted.mode is ServiceMode.COORDINATOR
            assert registry_marker.is_dir()
            assert (
                reconcile_marker.read_text(encoding="utf-8")
                == "promoted"
            )
            with sqlite3.connect(workflow_database) as connection:
                assert (
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    == SCHEMA_VERSION + 1
                )
                assert connection.execute(
                    "SELECT 1 FROM shadow_promotion_marker"
                ).fetchall() == []
        finally:
            candidate.close()
    finally:
        current.close()
