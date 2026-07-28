from __future__ import annotations

import hashlib
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
