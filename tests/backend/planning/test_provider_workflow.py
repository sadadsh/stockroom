from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast

import pytest

from stockroom.planning import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    PROVIDER_WORKFLOW_STAGES,
    AdapterOutcome,
    AuthenticationState,
    ExactPartIdentity,
    FailureClassification,
    LicenseDecision,
    ProviderDeclaration,
    ProviderExecutionRuntime,
    ProviderHealth,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyInput,
    ProviderRegistration,
    ProviderRetryBounds,
    TrustDecision,
    build_provider_stage_handlers,
)
from stockroom.workflow import (
    CompletionOutcome,
    DecisionKind,
    DecisionOutcome,
    ExactIdentityOutcome,
    IntakeIdentity,
    ItemRecord,
    ItemStatus,
    PermanentFailureOutcome,
    RetryOutcome,
    StageContext,
    StageName,
    StageRecord,
    StageStatus,
    WorkflowRuntime,
    WorkflowStore,
)
from stockroom.workflow.model import canonical_json

_IDENTITY = ExactPartIdentity("ON Semiconductor", "S1M")
_STAGE_OPERATIONS = {
    StageName.METADATA: (METADATA_OPERATION,),
    StageName.DATASHEET: (DATASHEET_OPERATION,),
    StageName.CAD_ACQUISITION: (
        KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION,
    ),
}


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


@dataclass(slots=True)
class _Adapter:
    provider_key: str
    executable_operations: frozenset[ProviderOperation]
    outcomes: dict[ProviderOperation, list[AdapterOutcome | BaseException]] = field(
        default_factory=dict
    )
    calls: list[ProviderOperation] = field(default_factory=list)

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        self.calls.append(operation)
        queued = self.outcomes.get(operation)
        if queued:
            outcome = queued.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return AdapterOutcome.success(
            identity,
            evidence_digests=(_digest(f"{self.provider_key}:{operation.label}"),),
        )


def _registration(
    adapter: _Adapter,
    *,
    version: str = "1.0.0",
) -> ProviderRegistration:
    return ProviderRegistration(
        ProviderDeclaration(
            key=adapter.provider_key,
            adapter_version=version,
            operations=tuple(
                sorted(
                    adapter.executable_operations,
                    key=lambda operation: operation.sort_key,
                )
            ),
            max_concurrency=1,
        ),
        adapter,
    )


def _policy(
    registrations: tuple[ProviderRegistration, ...],
    *,
    priority: int = 100,
    authentication: AuthenticationState = AuthenticationState.NOT_REQUIRED,
) -> tuple[ProviderPolicyInput, ...]:
    return tuple(
        ProviderPolicyInput(
            provider_key=registration.declaration.key,
            operation=operation,
            trust=TrustDecision.PRIMARY,
            license=LicenseDecision.ALLOWED,
            authentication=authentication,
            health=ProviderHealth.HEALTHY,
            priority=priority,
        )
        for registration in registrations
        for operation in registration.declaration.operations
    )


def _handlers(
    registrations: tuple[ProviderRegistration, ...],
    policies: tuple[ProviderPolicyInput, ...],
    *,
    identity: ExactPartIdentity = _IDENTITY,
    now: float = 100.0,
    retry_bounds: ProviderRetryBounds = ProviderRetryBounds(),
):
    planner = ProviderPlanner(registrations)
    runtime = ProviderExecutionRuntime(planner)
    return build_provider_stage_handlers(
        exact_identity=lambda _context: identity,
        planner=planner,
        runtime=runtime,
        policy_inputs=policies,
        clock=lambda: now,
        retry_bounds=retry_bounds,
    )


def _context(
    stage_name: StageName,
    *,
    attempt_count: int = 1,
    error: dict[str, Any] | None = None,
) -> StageContext:
    item = ItemRecord(
        id="item-1",
        entry_id="entry-1",
        batch_id="batch-1",
        ordinal=0,
        workflow_graph_version=1,
        manufacturer="raw manufacturer",
        mpn="raw mpn",
        manufacturer_key="raw manufacturer",
        mpn_key="raw mpn",
        payload={},
        status=ItemStatus.RUNNING,
        created_at=1.0,
        updated_at=2.0,
    )
    stage = StageRecord(
        id=f"stage-{stage_name.value}",
        item_id=item.id,
        batch_id=item.batch_id,
        entry_id=item.entry_id,
        ordinal=list(StageName).index(stage_name),
        name=stage_name,
        status=StageStatus.RUNNING,
        attempt_count=attempt_count,
        next_attempt_at=None,
        lease_owner="worker",
        lease_expires_at=200.0,
        lease_token="lease-token",
        lease_generation=attempt_count,
        result=None,
        error=error,
        created_at=1.0,
        updated_at=2.0,
    )
    identity_result = MappingProxyType(
        {
            "component_id": "component-1",
            "identity_digest": _digest("identity"),
            "manufacturer_id": "manufacturer-1",
        }
    )
    return StageContext(
        item=item,
        stage=stage,
        prior_results=MappingProxyType({StageName.IDENTITY_DEDUPE: identity_result}),
    )


def _outcome_document(outcome: object) -> dict[str, Any]:
    if isinstance(outcome, CompletionOutcome):
        document = outcome.result
    elif isinstance(outcome, RetryOutcome):
        document = outcome.error
    elif isinstance(outcome, DecisionOutcome):
        document = outcome.prompt
    elif isinstance(outcome, PermanentFailureOutcome):
        document = outcome.error
    else:
        raise AssertionError(type(outcome).__name__)
    assert type(document) is dict
    canonical_json(document)
    return cast(dict[str, Any], document)


@pytest.mark.parametrize("stage_name", PROVIDER_WORKFLOW_STAGES)
def test_handlers_complete_only_with_operation_evidence(stage_name: StageName) -> None:
    adapter = _Adapter(
        "evidence_api",
        frozenset(
            {
                METADATA_OPERATION,
                DATASHEET_OPERATION,
                KICAD_CAD_OPERATION,
                ALTIUM_CAD_OPERATION,
            }
        ),
    )
    registrations = (_registration(adapter),)
    handlers = _handlers(registrations, _policy(registrations))

    outcome = handlers[stage_name](_context(stage_name))

    assert isinstance(outcome, CompletionOutcome)
    result = _outcome_document(outcome)
    assert result["stage"] == stage_name.value
    assert result["policy_semantic_digest"].startswith("sha256:")
    assert result["plan_semantic_digest"].startswith("sha256:")
    assert result["receipt_semantic_digest"].startswith("sha256:")
    operations = result["operations"]
    assert type(operations) is list
    assert [operation["operation"] for operation in operations] == [
        operation.label for operation in _STAGE_OPERATIONS[stage_name]
    ]
    assert all(operation["selected"]["evidence_digests"] for operation in operations)


def test_metadata_fallback_is_ordered_and_raw_exceptions_are_redacted() -> None:
    secret = "token=provider-secret-must-not-persist"
    faulty = _Adapter(
        "faulty_api",
        frozenset({METADATA_OPERATION}),
        outcomes={METADATA_OPERATION: [RuntimeError(secret)]},
    )
    fallback = _Adapter("fallback_api", frozenset({METADATA_OPERATION}))
    registrations = (_registration(faulty), _registration(fallback))
    policies = tuple(
        ProviderPolicyInput(
            provider_key=policy.provider_key,
            operation=policy.operation,
            trust=policy.trust,
            license=policy.license,
            authentication=policy.authentication,
            health=policy.health,
            priority=1 if policy.provider_key == "faulty_api" else 2,
        )
        for policy in _policy(registrations)
    )

    outcome = _handlers(registrations, policies)[StageName.METADATA](_context(StageName.METADATA))

    assert isinstance(outcome, CompletionOutcome)
    document = _outcome_document(outcome)
    attempts = document["operations"][0]["attempts"]
    assert [attempt["provider_key"] for attempt in attempts] == [
        "faulty_api",
        "fallback_api",
    ]
    assert [attempt["status"] for attempt in attempts] == [
        "adapter_fault",
        "success",
    ]
    encoded = canonical_json(document)
    assert secret not in encoded
    assert "queue_wait_ns" not in encoded
    assert "execution_ns" not in encoded
    assert "retry_after_seconds" not in encoded


def test_cad_requires_both_kicad_and_altium_evidence() -> None:
    adapter = _Adapter(
        "cad_vendor",
        frozenset({KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION}),
        outcomes={
            ALTIUM_CAD_OPERATION: [AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)]
        },
    )
    registrations = (_registration(adapter),)

    outcome = _handlers(registrations, _policy(registrations))[StageName.CAD_ACQUISITION](
        _context(StageName.CAD_ACQUISITION)
    )

    assert isinstance(outcome, DecisionOutcome)
    assert outcome.kind is DecisionKind.SAFETY
    document = _outcome_document(outcome)
    evidence = document["details"]["evidence"]
    assert [operation["operation"] for operation in evidence["operations"]] == [
        "cad:kicad",
        "cad:altium",
    ]
    assert set(adapter.calls) == {KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION}


def test_rate_limit_becomes_bounded_absolute_retry_without_timing_evidence() -> None:
    adapter = _Adapter(
        "limited_api",
        frozenset({METADATA_OPERATION}),
        outcomes={
            METADATA_OPERATION: [
                AdapterOutcome.failure(
                    FailureClassification.RATE_LIMITED,
                    retry_after_seconds=5_000,
                )
            ]
        },
    )
    registrations = (_registration(adapter),)
    bounds = ProviderRetryBounds(
        default_delay_seconds=30,
        minimum_delay_seconds=2,
        maximum_delay_seconds=120,
        maximum_attempts=3,
    )

    outcome = _handlers(
        registrations,
        _policy(registrations),
        now=100,
        retry_bounds=bounds,
    )[StageName.METADATA](_context(StageName.METADATA))

    assert isinstance(outcome, RetryOutcome)
    assert outcome.retry_at == 220
    document = _outcome_document(outcome)
    encoded = canonical_json(document)
    assert document["kind"] == "provider_stage_retry"
    assert "retry_after_seconds" not in encoded
    assert "queue_wait_ns" not in encoded
    assert "execution_ns" not in encoded


def test_setup_failure_is_terminal_and_has_no_provider_effect() -> None:
    adapter = _Adapter("credentialed_api", frozenset({METADATA_OPERATION}))
    registrations = (_registration(adapter),)

    outcome = _handlers(
        registrations,
        _policy(
            registrations,
            authentication=AuthenticationState.MISSING,
        ),
    )[StageName.METADATA](_context(StageName.METADATA))

    assert isinstance(outcome, PermanentFailureOutcome)
    assert _outcome_document(outcome)["kind"] == "provider_setup_required"
    assert adapter.calls == []


def test_success_without_immutable_evidence_fails_closed() -> None:
    adapter = _Adapter(
        "empty_api",
        frozenset({DATASHEET_OPERATION}),
        outcomes={DATASHEET_OPERATION: [AdapterOutcome.success(_IDENTITY)]},
    )
    registrations = (_registration(adapter),)

    outcome = _handlers(registrations, _policy(registrations))[StageName.DATASHEET](
        _context(StageName.DATASHEET)
    )

    assert isinstance(outcome, PermanentFailureOutcome)
    assert _outcome_document(outcome)["kind"] == "provider_success_without_evidence"


def test_retry_policy_drift_fails_before_adapter_invocation() -> None:
    first_adapter = _Adapter(
        "drift_api",
        frozenset({METADATA_OPERATION}),
        outcomes={METADATA_OPERATION: [AdapterOutcome.failure(FailureClassification.UNAVAILABLE)]},
    )
    first_registrations = (_registration(first_adapter),)
    first_outcome = _handlers(
        first_registrations,
        _policy(first_registrations, priority=100),
    )[StageName.METADATA](_context(StageName.METADATA))
    assert isinstance(first_outcome, RetryOutcome)

    replacement = _Adapter("drift_api", frozenset({METADATA_OPERATION}))
    replacement_registrations = (_registration(replacement),)
    retry_outcome = _handlers(
        replacement_registrations,
        _policy(replacement_registrations, priority=101),
    )[StageName.METADATA](
        _context(
            StageName.METADATA,
            attempt_count=2,
            error=_outcome_document(first_outcome),
        )
    )

    assert isinstance(retry_outcome, PermanentFailureOutcome)
    assert _outcome_document(retry_outcome)["kind"] == "provider_policy_drift"
    assert replacement.calls == []


def test_adapter_contract_drift_fails_preflight_with_zero_calls() -> None:
    adapter = _Adapter("mutable_api", frozenset({METADATA_OPERATION}))
    registrations = (_registration(adapter),)
    handlers = _handlers(registrations, _policy(registrations))
    adapter.executable_operations = frozenset()

    outcome = handlers[StageName.METADATA](_context(StageName.METADATA))

    assert isinstance(outcome, PermanentFailureOutcome)
    assert _outcome_document(outcome)["kind"] == "provider_contract_drift"
    assert adapter.calls == []


def test_retry_reopens_with_same_plan_and_reuses_the_durable_checkpoint(
    tmp_path,
) -> None:
    database = tmp_path / "Workflow.sqlite3"
    first_store = WorkflowStore(database)
    batch = first_store.submit_batch(
        [IntakeIdentity("raw manufacturer", "raw mpn")],
        now=1,
    )

    def identity_handler(_context: StageContext) -> ExactIdentityOutcome:
        return ExactIdentityOutcome(
            authoritative_manufacturer_key=_IDENTITY.authoritative_manufacturer_key,
            mpn_canonical=_IDENTITY.mpn_canonical,
            registry_revision="registry-v1",
            rule_revision="rule-v1",
            evidence={"source": "test"},
        )

    def resolver(store: WorkflowStore):
        def resolve(context: StageContext) -> ExactPartIdentity:
            binding = store.get_item_component(context.item.id)
            assert binding is not None
            component = store.get_resolved_component(binding.component_id)
            return ExactPartIdentity(
                component.authoritative_manufacturer_key,
                component.mpn_canonical,
            )

        return resolve

    first_adapter = _Adapter(
        "restart_api",
        frozenset({METADATA_OPERATION}),
        outcomes={
            METADATA_OPERATION: [
                AdapterOutcome.failure(
                    FailureClassification.RATE_LIMITED,
                    retry_after_seconds=10,
                )
            ]
        },
    )
    first_registrations = (_registration(first_adapter),)
    policies = _policy(first_registrations)
    first_planner = ProviderPlanner(first_registrations)
    first_provider_handlers = build_provider_stage_handlers(
        exact_identity=resolver(first_store),
        planner=first_planner,
        runtime=ProviderExecutionRuntime(first_planner),
        policy_inputs=policies,
        clock=lambda: 3,
        retry_bounds=ProviderRetryBounds(
            default_delay_seconds=10,
            minimum_delay_seconds=1,
            maximum_delay_seconds=20,
        ),
    )
    first_runtime = WorkflowRuntime(
        first_store,
        {
            StageName.IDENTITY_DEDUPE: identity_handler,
            **first_provider_handlers,
        },
    )

    identity_dispatch = first_runtime.poll_once("worker-a", now=2, lease_seconds=60)
    retry_dispatch = first_runtime.poll_once("worker-a", now=3, lease_seconds=60)

    assert identity_dispatch is not None
    assert identity_dispatch.stage_name is StageName.IDENTITY_DEDUPE
    assert retry_dispatch is not None
    assert retry_dispatch.stage_name is StageName.METADATA
    assert isinstance(retry_dispatch.outcome, RetryOutcome)
    assert retry_dispatch.outcome.retry_at == 13

    reopened_store = WorkflowStore(database)
    replacement = _Adapter("restart_api", frozenset({METADATA_OPERATION}))
    replacement_registrations = (_registration(replacement),)
    replacement_planner = ProviderPlanner(replacement_registrations)
    replacement_handlers = build_provider_stage_handlers(
        exact_identity=resolver(reopened_store),
        planner=replacement_planner,
        runtime=ProviderExecutionRuntime(replacement_planner),
        policy_inputs=_policy(replacement_registrations),
        clock=lambda: 13,
        retry_bounds=ProviderRetryBounds(
            default_delay_seconds=10,
            minimum_delay_seconds=1,
            maximum_delay_seconds=20,
        ),
    )

    resumed = WorkflowRuntime(reopened_store, replacement_handlers).poll_once(
        "worker-b",
        now=13,
        lease_seconds=60,
    )

    assert resumed is not None
    assert resumed.stage_name is StageName.METADATA
    assert isinstance(resumed.outcome, CompletionOutcome)
    item_id = reopened_store.list_items(batch.id)[0].id
    metadata = next(
        stage for stage in reopened_store.list_stages(item_id) if stage.name is StageName.METADATA
    )
    assert metadata.status is StageStatus.COMPLETED
    assert metadata.attempt_count == 2
    assert replacement.calls == [METADATA_OPERATION]


def test_lease_recovered_attempt_without_provider_retry_checkpoint_replans(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "Workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("raw manufacturer", "raw mpn")], now=1)

    def identity_handler(_context: StageContext) -> ExactIdentityOutcome:
        return ExactIdentityOutcome(
            authoritative_manufacturer_key=_IDENTITY.authoritative_manufacturer_key,
            mpn_canonical=_IDENTITY.mpn_canonical,
            registry_revision="registry-v1",
            rule_revision="rule-v1",
            evidence={"source": "test"},
        )

    adapter = _Adapter("lease_recovery_api", frozenset({METADATA_OPERATION}))
    registrations = (_registration(adapter),)
    handlers = _handlers(registrations, _policy(registrations))
    runtime = WorkflowRuntime(
        store,
        {
            StageName.IDENTITY_DEDUPE: identity_handler,
            **handlers,
        },
    )

    identity = runtime.poll_once("identity-worker", now=2, lease_seconds=5)
    assert identity is not None
    assert identity.stage_name is StageName.IDENTITY_DEDUPE

    abandoned = store.claim_ready("crashed-worker", now=3, lease_seconds=5, limit=1)[0]
    assert abandoned.name is StageName.METADATA
    assert abandoned.attempt_count == 1
    assert store.recover_expired_leases(now=8) == 1

    resumed = runtime.poll_once("replacement-worker", now=8, lease_seconds=5)

    assert resumed is not None
    assert resumed.stage_name is StageName.METADATA
    assert isinstance(resumed.outcome, CompletionOutcome)
    item_id = store.list_items(batch.id)[0].id
    metadata = next(
        stage for stage in store.list_stages(item_id) if stage.name is StageName.METADATA
    )
    assert metadata.status is StageStatus.COMPLETED
    assert metadata.attempt_count == 2
    assert adapter.calls == [METADATA_OPERATION]


def test_explicit_provider_retry_checkpoint_still_requires_valid_digests() -> None:
    adapter = _Adapter("malformed_retry_api", frozenset({METADATA_OPERATION}))
    registrations = (_registration(adapter),)

    outcome = _handlers(registrations, _policy(registrations))[StageName.METADATA](
        _context(
            StageName.METADATA,
            attempt_count=2,
            error={"kind": "provider_stage_retry"},
        )
    )

    assert isinstance(outcome, PermanentFailureOutcome)
    assert _outcome_document(outcome)["kind"] == "provider_identity_or_checkpoint_invalid"
    assert adapter.calls == []
