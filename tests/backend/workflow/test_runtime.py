from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from stockroom.workflow import (
    BatchStatus,
    CompletionOutcome,
    DecisionKind,
    DecisionOutcome,
    DecisionStatus,
    ExactIdentityOutcome,
    IntakeIdentity,
    InvalidStageOutcome,
    PermanentFailureOutcome,
    PublicationMembershipState,
    PublicationProposalOutcome,
    RetryOutcome,
    StageContext,
    StageHandlerError,
    StageLeaseLost,
    StageName,
    StageOutcome,
    StageStatus,
    WorkflowConflict,
    WorkflowRuntime,
    WorkflowStore,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _identity(_: StageContext) -> ExactIdentityOutcome:
    return ExactIdentityOutcome(
        authoritative_manufacturer_key="ACME",
        mpn_canonical="P-1",
        registry_revision="registry-v1",
        rule_revision="rule-v1",
        evidence={"source": "fixture"},
    )


def test_dispatches_the_real_dag_and_only_joins_publication(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch(
        [IntakeIdentity("raw manufacturer", "raw mpn", {"row": 7})],
        now=1,
    )
    seen: dict[StageName, StageContext] = {}

    def handle(context: StageContext):
        seen[context.stage.name] = context
        if context.stage.name is StageName.IDENTITY_DEDUPE:
            return _identity(context)
        if context.stage.name is StageName.PUBLISH:
            return PublicationProposalOutcome(
                candidate_digest=_digest("candidate"),
                manifest_digest=_digest("manifest"),
                expected_base_commit="base-commit",
            )
        return CompletionOutcome(
            {
                "nested": {"values": [context.stage.name.value]},
                "stage": context.stage.name.value,
            }
        )

    runtime = WorkflowRuntime(store, {name: handle for name in StageName})
    timestamp = 2.0
    while StageName.PUBLISH not in seen:
        dispatched = runtime.poll_once(
            "worker",
            now=timestamp,
            lease_seconds=100,
        )
        assert dispatched is not None
        timestamp += 1

    assert set(seen) == set(StageName)
    item = store.list_items(batch.id)[0]
    assert all(context.item.id == item.id for context in seen.values())
    assert all(context.item.payload == {"row": 7} for context in seen.values())
    assert all(context.stage.name is name for name, context in seen.items())
    assert seen[StageName.IDENTITY_DEDUPE].prior_results == {}
    assert set(seen[StageName.RECONCILE].prior_results) == {
        StageName.IDENTITY_DEDUPE,
        StageName.METADATA,
        StageName.DATASHEET,
        StageName.EXISTING_EVIDENCE,
    }
    assert StageName.CAD_ACQUISITION not in seen[StageName.RECONCILE].prior_results

    prior = seen[StageName.RECONCILE].prior_results
    with pytest.raises(TypeError):
        cast(Any, prior)[StageName.METADATA] = {}
    metadata = cast(Mapping[str, Any], prior[StageName.METADATA])
    assert not isinstance(metadata, dict)
    with pytest.raises(TypeError):
        cast(Any, metadata)["stage"] = "changed"
    nested = cast(Mapping[str, Any], metadata["nested"])
    with pytest.raises(TypeError):
        cast(Any, nested)["changed"] = True
    assert nested["values"] == (StageName.METADATA.value,)

    stages = store.list_stages(item.id)
    assert all(
        stage.status is StageStatus.COMPLETED
        for stage in stages
        if stage.name is not StageName.PUBLISH
    )
    publish = next(stage for stage in stages if stage.name is StageName.PUBLISH)
    assert publish.status is StageStatus.BLOCKED
    membership = store.get_publication_membership(item.id)
    assert membership is not None
    assert membership.state is PublicationMembershipState.WAITING
    operation = store.get_publication_operation(membership.publication_id)
    assert operation.git_commit_oid is None
    assert operation.catalog_revision is None
    assert store.get_batch(batch.id).status is BatchStatus.BLOCKED


def test_missing_handler_fails_closed_instead_of_stranding_the_lease(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)

    dispatched = WorkflowRuntime(store, {}).poll_once(
        "worker",
        now=2,
        lease_seconds=100,
    )

    assert dispatched is not None
    assert isinstance(dispatched.outcome, PermanentFailureOutcome)
    stage = store.list_stages(store.list_items(batch.id)[0].id)[0]
    assert stage.status is StageStatus.FAILED
    assert stage.lease_owner is None
    assert stage.error == {
        "kind": "missing_stage_handler",
        "stage": StageName.IDENTITY_DEDUPE.value,
    }
    assert store.get_batch(batch.id).status is BatchStatus.FAILED


@pytest.mark.parametrize(
    ("outcome_factory", "expected_status"),
    [
        (
            lambda: RetryOutcome(
                error={"kind": "provider_timeout"},
                retry_at=10,
            ),
            StageStatus.WAITING_RETRY,
        ),
        (
            lambda: DecisionOutcome(
                kind=DecisionKind.IDENTITY,
                prompt={"question": "Which exact identity?"},
            ),
            StageStatus.BLOCKED,
        ),
        (
            lambda: PermanentFailureOutcome(error={"kind": "malformed_evidence"}),
            StageStatus.FAILED,
        ),
    ],
)
def test_dispatches_typed_retry_decision_and_failure(
    tmp_path,
    outcome_factory: Callable[[], StageOutcome],
    expected_status: StageStatus,
):
    store = WorkflowStore(tmp_path / f"{expected_status.value}.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)

    def handle(_: StageContext) -> StageOutcome:
        return outcome_factory()

    runtime = WorkflowRuntime(store, {StageName.IDENTITY_DEDUPE: handle})

    dispatched = runtime.poll_once("worker", now=2, lease_seconds=100)

    assert dispatched is not None
    stage = store.list_stages(store.list_items(batch.id)[0].id)[0]
    assert stage.status is expected_status
    assert stage.lease_owner is None
    if expected_status is StageStatus.WAITING_RETRY:
        assert stage.next_attempt_at == 10
        assert stage.error == {"kind": "provider_timeout"}
    elif expected_status is StageStatus.BLOCKED:
        decision = store.list_decisions(batch.id)[0]
        assert decision.kind is DecisionKind.IDENTITY
        assert decision.status is DecisionStatus.OPEN
        assert decision.prompt == {"question": "Which exact identity?"}
    else:
        assert stage.error == {"kind": "malformed_evidence"}


def test_unexpected_handler_exception_is_failed_and_surfaced(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)

    def explode(_: StageContext):
        raise RuntimeError("broken adapter")

    runtime = WorkflowRuntime(store, {StageName.IDENTITY_DEDUPE: explode})
    with pytest.raises(StageHandlerError, match="identity_dedupe") as raised:
        runtime.poll_once("worker", now=2, lease_seconds=100)

    assert isinstance(raised.value.__cause__, RuntimeError)
    stage = store.list_stages(store.list_items(batch.id)[0].id)[0]
    assert stage.status is StageStatus.FAILED
    assert stage.error == {
        "exception_type": "RuntimeError",
        "kind": "stage_handler_exception",
        "message": "broken adapter",
        "stage": StageName.IDENTITY_DEDUPE.value,
    }


def test_invalid_outcome_is_failed_and_surfaced(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: lambda _: CompletionOutcome({"wrong": True})},
    )

    with pytest.raises(InvalidStageOutcome, match="identity_dedupe"):
        runtime.poll_once("worker", now=2, lease_seconds=100)

    stage = store.list_stages(store.list_items(batch.id)[0].id)[0]
    assert stage.status is StageStatus.FAILED
    assert stage.error == {
        "kind": "invalid_stage_outcome",
        "outcome": "CompletionOutcome",
        "stage": StageName.IDENTITY_DEDUPE.value,
    }


def test_exact_replay_is_idempotent_and_a_stale_claim_never_calls_the_handler(tmp_path):
    replay_store = WorkflowStore(tmp_path / "replay.sqlite3")
    replay_store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    replay_claim = replay_store.claim_ready(
        "worker",
        now=2,
        lease_seconds=100,
        limit=1,
    )[0]
    replay_runtime = WorkflowRuntime(
        replay_store,
        {StageName.IDENTITY_DEDUPE: _identity},
    )

    first = replay_runtime.dispatch_claim(replay_claim, "worker", now=3)
    replay = replay_runtime.dispatch_claim(replay_claim, "worker", now=4)

    assert first == replay
    assert [event.kind for event in replay_store.events(replay_claim.batch_id)].count(
        "identity_resolved"
    ) == 1

    stale_store = WorkflowStore(tmp_path / "stale.sqlite3")
    stale_store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    stale_claim = stale_store.claim_ready(
        "old-worker",
        now=2,
        lease_seconds=1,
        limit=1,
    )[0]
    fresh_claim = stale_store.claim_ready(
        "new-worker",
        now=4,
        lease_seconds=100,
        limit=1,
    )[0]
    calls = 0

    def counted(context: StageContext):
        nonlocal calls
        calls += 1
        return _identity(context)

    stale_runtime = WorkflowRuntime(
        stale_store,
        {StageName.IDENTITY_DEDUPE: counted},
    )
    with pytest.raises(WorkflowConflict, match="stale"):
        stale_runtime.dispatch_claim(stale_claim, "old-worker", now=4)
    assert calls == 0

    stale_runtime.dispatch_claim(fresh_claim, "new-worker", now=5)
    assert calls == 1


@pytest.mark.serial_only
def test_a_stage_running_past_its_lease_is_not_reclaimed(tmp_path):
    # The lease stays sub-second but is deliberately ten heartbeats long: a
    # single synchronous=FULL commit on Windows can stall a few hundred
    # milliseconds, and this test must prove renewal, not disk latency.
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")])
    claim = store.claim_ready("worker-a", lease_seconds=0.5, limit=1)[0]
    started = threading.Event()
    release = threading.Event()

    def blocking(context: StageContext):
        started.set()
        assert release.wait(5.0)
        return _identity(context)

    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: blocking},
        heartbeat_seconds=0.05,
    )
    dispatched: list[object] = []
    failures: list[BaseException] = []

    def dispatch() -> None:
        try:
            dispatched.append(runtime.dispatch_claim(claim, "worker-a", lease_seconds=0.5))
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            failures.append(exc)

    worker = threading.Thread(target=dispatch, name="dispatch-under-test")
    worker.start()
    try:
        assert started.wait(2.0)
        deadline = time.monotonic() + 0.9
        while time.monotonic() < deadline:
            assert store.claim_ready("worker-b", lease_seconds=30, limit=1) == []
            time.sleep(0.05)
    finally:
        release.set()
        worker.join(5.0)

    assert not failures
    assert worker.is_alive() is False
    assert len(dispatched) == 1
    stage = store.get_stage(claim.id)
    assert stage.status is StageStatus.COMPLETED
    assert stage.attempt_count == 1


def test_lease_renewal_never_rotates_the_fence(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")])
    claim = store.claim_ready("worker", lease_seconds=0.5, limit=1)[0]
    observed: list[Any] = []

    def slow(context: StageContext):
        time.sleep(0.25)
        observed.append(store.get_stage(claim.id))
        return _identity(context)

    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: slow},
        heartbeat_seconds=0.05,
    )

    dispatched = runtime.dispatch_claim(claim, "worker", lease_seconds=0.5)

    assert dispatched is not None
    in_flight = observed[0]
    assert in_flight.status is StageStatus.RUNNING
    assert in_flight.lease_token == claim.lease_token
    assert in_flight.lease_generation == claim.lease_generation
    assert in_flight.lease_expires_at > claim.lease_expires_at
    completed = store.get_stage(claim.id)
    assert completed.status is StageStatus.COMPLETED
    assert completed.attempt_count == 1


def test_lease_renewal_stays_out_of_the_durable_event_journal(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")])
    claim = store.claim_ready("worker", lease_seconds=0.5, limit=1)[0]
    observed: list[Any] = []

    def slow(context: StageContext):
        time.sleep(0.25)
        observed.append(store.get_stage(claim.id))
        return _identity(context)

    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: slow},
        heartbeat_seconds=0.02,
    )

    runtime.dispatch_claim(claim, "worker", lease_seconds=0.5)

    assert observed[0].lease_expires_at > claim.lease_expires_at
    kinds = [event.kind for event in store.events(claim.batch_id)]
    assert kinds.count("stage_lease_renewed") == 0


class _LeaseLosingStore(WorkflowStore):
    """A store whose heartbeat always loses the fence it tries to renew."""

    def __init__(self, database):
        super().__init__(database)
        self.renew_attempts = 0
        self.terminal_calls: list[str] = []

    def renew_lease(self, *args, **kwargs):
        self.renew_attempts += 1
        raise WorkflowConflict("stage lease fence is stale")

    def resolve_exact_identity(self, *args, **kwargs):
        self.terminal_calls.append("resolve_exact_identity")
        return super().resolve_exact_identity(*args, **kwargs)

    def complete_stage(self, *args, **kwargs):
        self.terminal_calls.append("complete_stage")
        return super().complete_stage(*args, **kwargs)

    def fail_stage(self, *args, **kwargs):
        self.terminal_calls.append("fail_stage")
        return super().fail_stage(*args, **kwargs)


def test_a_lost_lease_skips_the_terminal_transition(tmp_path):
    store = _LeaseLosingStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")])
    claim = store.claim_ready("worker", lease_seconds=30, limit=1)[0]
    finished = threading.Event()

    def slow(context: StageContext):
        time.sleep(0.3)
        finished.set()
        return _identity(context)

    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: slow},
        heartbeat_seconds=0.05,
    )

    with pytest.raises(StageLeaseLost):
        runtime.dispatch_claim(claim, "worker", lease_seconds=30)

    assert finished.is_set()
    assert store.renew_attempts >= 1
    assert store.terminal_calls == []
    assert isinstance(StageLeaseLost("x"), WorkflowConflict)
    assert store.get_stage(claim.id).status is StageStatus.RUNNING


def test_a_heartbeat_free_runtime_starts_no_thread(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")])
    claim = store.claim_ready("worker", lease_seconds=30, limit=1)[0]
    live: list[int] = []

    def observe(context: StageContext):
        live.append(
            sum(
                1
                for thread in threading.enumerate()
                if thread.name == "stockroom-workflow-lease-heartbeat"
            )
        )
        return _identity(context)

    WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: observe},
    ).dispatch_claim(claim, "worker")

    assert live == [0]


def test_a_stale_claim_starts_no_heartbeat(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    stale_claim = store.claim_ready("old-worker", now=2, lease_seconds=1, limit=1)[0]
    store.claim_ready("new-worker", now=4, lease_seconds=100, limit=1)
    calls = 0

    def counted(context: StageContext):
        nonlocal calls
        calls += 1
        return _identity(context)

    runtime = WorkflowRuntime(
        store,
        {StageName.IDENTITY_DEDUPE: counted},
        heartbeat_seconds=0.05,
    )

    with pytest.raises(WorkflowConflict, match="stale"):
        runtime.dispatch_claim(stale_claim, "old-worker", now=4)

    time.sleep(0.15)
    assert calls == 0
    assert [
        thread.name
        for thread in threading.enumerate()
        if thread.name == "stockroom-workflow-lease-heartbeat"
    ] == []
