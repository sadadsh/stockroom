from __future__ import annotations

import hashlib
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

import pytest

from stockroom.service import (
    CoordinatorConflict,
    MutexAcquireResult,
    ServiceControl,
    ServiceMode,
    WorkflowCoordinator,
    WorkflowCoordinatorLifecycleError,
    WorkflowCoordinatorState,
)
from stockroom.workflow import (
    CompletionOutcome,
    ExactIdentityOutcome,
    IntakeIdentity,
    PublicationProposalOutcome,
    StageContext,
    StageName,
    StageStatus,
    WorkflowRuntime,
    WorkflowStore,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows thread tests")

_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"


@dataclass
class _Identity:
    def current_sid(self) -> str:
        return _SID


class _AllowTestStorage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class _MutexHandle:
    def __init__(self, registry: _MutexRegistry):
        self._registry = registry
        self._held = False

    def try_acquire(self) -> MutexAcquireResult:
        if self._registry.owner is not None:
            return MutexAcquireResult.BUSY
        self._registry.owner = self
        self._held = True
        return MutexAcquireResult.ACQUIRED

    def release(self) -> None:
        if not self._held or self._registry.owner is not self:
            raise AssertionError("fake mutex release without ownership")
        self._registry.owner = None
        self._held = False


class _MutexRegistry:
    def __init__(self):
        self.owner: _MutexHandle | None = None

    def open_current_user(self, *, name: str, sid: str) -> _MutexHandle:
        assert name
        assert sid == _SID
        return _MutexHandle(self)


def _control(tmp_path: Path) -> tuple[ServiceControl, _MutexRegistry]:
    mutexes = _MutexRegistry()
    control = ServiceControl(
        tmp_path / "Control.sqlite",
        mode=ServiceMode.COORDINATOR,
        identity=_Identity(),
        mutex_factory=mutexes,
        storage_policy=_AllowTestStorage(),
    )
    return control, mutexes


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _handlers(*, delay_identity: float = 0.0):
    active = 0
    peak = 0
    lock = Lock()

    def handle(context: StageContext):
        nonlocal active, peak
        if context.stage.name is StageName.IDENTITY_DEDUPE:
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if delay_identity:
                    time.sleep(delay_identity)
            finally:
                with lock:
                    active -= 1
            return ExactIdentityOutcome(
                authoritative_manufacturer_key=context.item.manufacturer,
                mpn_canonical=context.item.mpn,
                registry_revision="registry-v1",
                rule_revision="rule-v1",
                evidence={"source": "coordinator-test"},
            )
        if context.stage.name is StageName.PUBLISH:
            return PublicationProposalOutcome(
                candidate_digest=_digest(f"candidate:{context.item.id}"),
                manifest_digest=_digest(f"manifest:{context.item.id}"),
                expected_base_commit="base-commit",
            )
        return CompletionOutcome({"stage": context.stage.name.value})

    return {name: handle for name in StageName}, lambda: peak


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


@pytest.mark.serial_only
def test_background_polling_is_bounded_fair_clean_and_payload_free(
    tmp_path: Path,
) -> None:
    control, _ = _control(tmp_path)
    fence = control.acquire()
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    secret = "secret-component-payload"
    store.submit_batch(
        [IntakeIdentity("ACME", f"P-{index}", {"private": secret}) for index in range(12)]
    )
    handlers, observed_peak = _handlers(delay_identity=0.03)
    runtime = WorkflowRuntime(store, handlers)
    coordinator = WorkflowCoordinator(
        control,
        fence,
        store,
        runtime,
        worker_count=3,
        minimum_idle_backoff_seconds=0.005,
        maximum_idle_backoff_seconds=0.02,
    )

    coordinator.start()
    _wait_until(lambda: coordinator.status().dispatch_count >= 12)
    coordinator.stop()

    status = coordinator.status()
    assert status.state is WorkflowCoordinatorState.STOPPED
    assert status.thread_alive is False
    assert status.in_flight == 0
    assert 2 <= status.peak_in_flight <= status.worker_limit == 3
    assert 2 <= observed_peak() <= 3
    assert status.maximum_worker_polls - status.minimum_worker_polls <= 1
    assert status.poll_count == (status.dispatch_count + status.idle_poll_count)
    assert status.poll_round_count * status.worker_limit == status.poll_count
    assert status.last_error_code is None

    public_status = repr(asdict(status))
    public_events = repr([event.payload for event in control.events()])
    assert secret not in public_status
    assert secret not in public_events
    assert fence.owner_id not in public_status
    assert fence.owner_id not in public_events
    control.release(fence)


def test_submission_is_generation_fenced_and_idempotent(tmp_path: Path) -> None:
    control, _ = _control(tmp_path)
    fence = control.acquire()
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    handlers, _ = _handlers()
    coordinator = WorkflowCoordinator(
        control,
        fence,
        store,
        WorkflowRuntime(store, handlers),
        worker_count=1,
        minimum_idle_backoff_seconds=0.005,
        maximum_idle_backoff_seconds=0.02,
    )
    identity = IntakeIdentity("ACME", "P-SUBMIT", {"part_id": "p-submit"})

    coordinator.start()
    _wait_until(lambda: coordinator.status().thread_alive)
    first = coordinator.submit_batch(
        [identity],
        idempotency_key="coordinator-submit-1",
    )
    retry = coordinator.submit_batch(
        [identity],
        idempotency_key="coordinator-submit-1",
    )

    assert retry.id == first.id
    assert store.count_batches() == 1
    assert [event.kind for event in store.events(first.id)].count("batch_submitted") == 1

    control.release(fence)
    current_fence = control.acquire()
    _wait_until(
        lambda: (
            coordinator.status().state is WorkflowCoordinatorState.STALE
            and not coordinator.status().thread_alive
        )
    )
    with pytest.raises(WorkflowCoordinatorLifecycleError, match="not accepting"):
        coordinator.submit_batch(
            [IntakeIdentity("ACME", "P-STALE")],
            idempotency_key="coordinator-submit-stale",
        )
    assert store.count_batches() == 1
    coordinator.stop()
    control.release(current_fence)


def test_reopen_recovers_an_expired_claim_before_background_dispatch(
    tmp_path: Path,
) -> None:
    control, _ = _control(tmp_path)
    fence = control.acquire()
    database = tmp_path / "Workflow.sqlite"
    initial_store = WorkflowStore(database)
    batch = initial_store.submit_batch(
        [IntakeIdentity("ACME", "P-RECOVER", {"private": "reopen-secret"})],
        now=1.0,
    )
    item = initial_store.list_items(batch.id)[0]
    claimed = initial_store.claim_ready(
        "crashed-worker",
        now=2.0,
        lease_seconds=1.0,
        limit=1,
    )
    assert len(claimed) == 1
    assert claimed[0].status is StageStatus.RUNNING

    reopened_store = WorkflowStore(database)
    handlers, _ = _handlers()
    coordinator = WorkflowCoordinator(
        control,
        fence,
        reopened_store,
        WorkflowRuntime(reopened_store, handlers),
        worker_count=2,
        minimum_idle_backoff_seconds=0.005,
        maximum_idle_backoff_seconds=0.02,
    )

    coordinator.start()
    _wait_until(
        lambda: (
            next(
                stage
                for stage in reopened_store.list_stages(item.id)
                if stage.name is StageName.IDENTITY_DEDUPE
            ).status
            is StageStatus.COMPLETED
        )
    )
    coordinator.stop()

    status = coordinator.status()
    assert status.recovered_claim_count == 1
    assert status.state is WorkflowCoordinatorState.STOPPED
    assert any(
        event.kind == "stage_lease_expired" for event in reopened_store.events(batch_id=batch.id)
    )
    assert "reopen-secret" not in repr(asdict(status))
    control.release(fence)


def test_start_refuses_a_stale_generation_without_polling(tmp_path: Path) -> None:
    control, _ = _control(tmp_path)
    stale_fence = control.acquire()
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    handlers, _ = _handlers()
    coordinator = WorkflowCoordinator(
        control,
        stale_fence,
        store,
        WorkflowRuntime(store, handlers),
    )
    control.release(stale_fence)
    current_fence = control.acquire()

    with pytest.raises(CoordinatorConflict, match="stale"):
        coordinator.start()

    status = coordinator.status()
    assert status.state is WorkflowCoordinatorState.STALE
    assert status.thread_alive is False
    assert status.poll_count == 0
    assert status.dispatch_count == 0
    assert status.last_error_code == "stale_generation"
    control.release(current_fence)


def test_running_coordinator_stops_when_its_generation_is_superseded(
    tmp_path: Path,
) -> None:
    control, _ = _control(tmp_path)
    stale_fence = control.acquire()
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    handlers, _ = _handlers()
    coordinator = WorkflowCoordinator(
        control,
        stale_fence,
        store,
        WorkflowRuntime(store, handlers),
        worker_count=2,
        minimum_idle_backoff_seconds=0.005,
        maximum_idle_backoff_seconds=0.02,
    )

    coordinator.start()
    _wait_until(lambda: coordinator.status().idle_round_count >= 2)
    running = coordinator.status()
    assert 0.005 <= running.current_backoff_seconds <= 0.02
    assert running.maximum_worker_polls - running.minimum_worker_polls <= 1
    control.release(stale_fence)
    current_fence = control.acquire()
    _wait_until(
        lambda: (
            coordinator.status().state is WorkflowCoordinatorState.STALE
            and not coordinator.status().thread_alive
        )
    )
    coordinator.stop()

    stopped = coordinator.status()
    polls_after_fence = stopped.poll_count
    time.sleep(0.03)
    assert coordinator.status().poll_count == polls_after_fence
    assert stopped.last_error_code == "stale_generation"
    assert stale_fence.owner_id not in repr(asdict(stopped))
    control.release(current_fence)


@pytest.mark.serial_only
def test_a_slow_stage_does_not_fault_the_coordinator(tmp_path: Path) -> None:
    control, _ = _control(tmp_path)
    fence = control.acquire()
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-SLOW")])
    item = store.list_items(batch.id)[0]
    identity_calls = 0
    lock = Lock()

    def handle(context: StageContext):
        nonlocal identity_calls
        if context.stage.name is StageName.IDENTITY_DEDUPE:
            with lock:
                identity_calls += 1
            time.sleep(1.0)
            return ExactIdentityOutcome(
                authoritative_manufacturer_key=context.item.manufacturer,
                mpn_canonical=context.item.mpn,
                registry_revision="registry-v1",
                rule_revision="rule-v1",
                evidence={"source": "slow-stage-test"},
            )
        if context.stage.name is StageName.PUBLISH:
            return PublicationProposalOutcome(
                candidate_digest=_digest(f"candidate:{context.item.id}"),
                manifest_digest=_digest(f"manifest:{context.item.id}"),
                expected_base_commit="base-commit",
            )
        return CompletionOutcome({"stage": context.stage.name.value})

    coordinator = WorkflowCoordinator(
        control,
        fence,
        store,
        WorkflowRuntime(
            store,
            {name: handle for name in StageName},
            heartbeat_seconds=0.1,
        ),
        worker_count=4,
        lease_seconds=0.3,
        minimum_idle_backoff_seconds=0.005,
        maximum_idle_backoff_seconds=0.02,
    )

    coordinator.start()
    _wait_until(
        lambda: (
            next(
                stage
                for stage in store.list_stages(item.id)
                if stage.name is StageName.IDENTITY_DEDUPE
            ).status
            is StageStatus.COMPLETED
        ),
        timeout=10.0,
    )
    coordinator.stop()

    status = coordinator.status()
    assert identity_calls == 1
    assert status.state is WorkflowCoordinatorState.STOPPED
    assert status.lease_lost_count == 0
    assert status.last_error_code is None
    control.release(fence)
