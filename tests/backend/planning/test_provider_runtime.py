from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError, dataclass, field, replace

import pytest

from stockroom.planning import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    ORDINARY_COMPONENT_OPERATIONS,
    AdapterOutcome,
    AdapterOutcomeStatus,
    AuthenticationState,
    ExactPartIdentity,
    FailureClassification,
    LicenseDecision,
    ProviderAttemptReceipt,
    ProviderDeclaration,
    ProviderExecutionRuntime,
    ProviderHealth,
    ProviderOperation,
    ProviderPlan,
    ProviderPlanner,
    ProviderPolicyError,
    ProviderPolicyInput,
    ProviderRegistration,
    ProviderRequest,
    ProviderRoute,
    ProviderRuntimeError,
    TrustDecision,
)


@dataclass(slots=True)
class _ConcurrentAdapter:
    provider_key: str
    executable_operations: frozenset[ProviderOperation]
    delay_seconds: float = 0
    failure: FailureClassification | None = None
    retry_after_seconds: float | None = None
    near_mpn: str | None = None
    raise_raw: bool = False
    secret: str = "raw-provider-secret"
    calls: list[tuple[ExactPartIdentity, ProviderOperation]] = field(default_factory=list)
    high_water: int = 0
    _active: int = 0
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        with self._lock:
            self._active += 1
            self.high_water = max(self.high_water, self._active)
            self.calls.append((identity, operation))
        try:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            if self.raise_raw:
                raise RuntimeError(self.secret)
            if self.failure is not None:
                return AdapterOutcome.failure(
                    self.failure,
                    retry_after_seconds=self.retry_after_seconds,
                )
            if self.near_mpn is not None:
                return AdapterOutcome(
                    AdapterOutcomeStatus.SUCCESS,
                    authoritative_manufacturer_key=(identity.authoritative_manufacturer_key),
                    mpn_canonical=self.near_mpn,
                )
            return AdapterOutcome.success(identity)
        finally:
            with self._lock:
                self._active -= 1


@dataclass(slots=True)
class _NonCallableAdapter:
    provider_key: str
    executable_operations: frozenset[ProviderOperation]


def _registration(
    adapter: object,
    *,
    key: str,
    operations: tuple[ProviderOperation, ...] = (METADATA_OPERATION,),
    max_concurrency: int = 2,
    version: str = "1.0.0",
) -> ProviderRegistration:
    return ProviderRegistration(
        ProviderDeclaration(
            key=key,
            adapter_version=version,
            operations=operations,
            max_concurrency=max_concurrency,
        ),
        adapter,  # type: ignore[arg-type]
    )


def _policy(
    registrations: tuple[ProviderRegistration, ...],
    *,
    priorities: dict[str, int] | None = None,
) -> tuple[ProviderPolicyInput, ...]:
    priority_by_key = {} if priorities is None else priorities
    return tuple(
        ProviderPolicyInput(
            provider_key=registration.declaration.key,
            operation=operation,
            trust=TrustDecision.PRIMARY,
            license=LicenseDecision.ALLOWED,
            authentication=AuthenticationState.NOT_REQUIRED,
            health=ProviderHealth.HEALTHY,
            priority=priority_by_key.get(registration.declaration.key, 100),
        )
        for registration in registrations
        for operation in registration.declaration.operations
    )


def _request(
    index: int,
    operations: tuple[ProviderOperation, ...] = (METADATA_OPERATION,),
) -> ProviderRequest:
    return ProviderRequest(
        ExactPartIdentity("ON Semiconductor", f"PART-{index:04d}"),
        operations,
    )


def _plans(
    planner: ProviderPlanner,
    registrations: tuple[ProviderRegistration, ...],
    count: int,
    *,
    operations: tuple[ProviderOperation, ...] = (METADATA_OPERATION,),
    priorities: dict[str, int] | None = None,
) -> tuple[ProviderPlan, ...]:
    return planner.plan(
        tuple(_request(index, operations) for index in range(count)),
        _policy(registrations, priorities=priorities),
    )


def test_runtime_enforces_provider_limit_for_one_and_one_thousand_requests() -> None:
    adapter = _ConcurrentAdapter(
        "bounded",
        frozenset({METADATA_OPERATION}),
        delay_seconds=0.001,
    )
    registration = _registration(
        adapter,
        key="bounded",
        max_concurrency=3,
    )
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    runtime = ProviderExecutionRuntime(planner, max_workers=32)
    policies = _policy(registrations)

    one_plan = _plans(planner, registrations, 1)
    one_receipt = runtime.execute(one_plan, policies)
    thousand_plans = _plans(planner, registrations, 1_000)
    thousand_receipts = runtime.execute(thousand_plans, policies)

    assert len(one_receipt) == 1
    assert one_receipt[0].complete
    assert len(thousand_receipts) == 1_000
    assert all(receipt.complete for receipt in thousand_receipts)
    assert [receipt.identity.mpn_canonical for receipt in thousand_receipts] == [
        f"PART-{index:04d}" for index in range(1_000)
    ]
    assert 1 < adapter.high_water <= 3
    assert len(adapter.calls) == 1_001
    assert runtime.concurrency_limits == {"bounded": 3}


def test_shared_runtime_limit_holds_across_simultaneous_execute_calls() -> None:
    adapter = _ConcurrentAdapter(
        "shared",
        frozenset({METADATA_OPERATION}),
        delay_seconds=0.003,
    )
    registration = _registration(
        adapter,
        key="shared",
        max_concurrency=2,
    )
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    runtime = ProviderExecutionRuntime(planner, max_workers=16)
    left = _plans(planner, registrations, 50)
    right = _plans(planner, registrations, 50)
    policies = _policy(registrations)
    errors: list[BaseException] = []

    def run(plans: tuple[ProviderPlan, ...]) -> None:
        try:
            assert all(receipt.complete for receipt in runtime.execute(plans, policies))
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=run, args=(left,))
    second = threading.Thread(target=run, args=(right,))
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert adapter.high_water == 2
    assert len(adapter.calls) == 100


def test_declared_parallelism_has_a_measured_timing_effect() -> None:
    def elapsed_for(limit: int) -> float:
        adapter = _ConcurrentAdapter(
            f"timed_{limit}",
            frozenset({METADATA_OPERATION}),
            delay_seconds=0.02,
        )
        registration = _registration(
            adapter,
            key=f"timed_{limit}",
            max_concurrency=limit,
        )
        registrations = (registration,)
        planner = ProviderPlanner(registrations)
        runtime = ProviderExecutionRuntime(planner, max_workers=16)
        plans = _plans(planner, registrations, 16)
        policies = _policy(registrations)
        started = time.perf_counter()
        receipts = runtime.execute(plans, policies)
        elapsed = time.perf_counter() - started
        assert all(receipt.complete for receipt in receipts)
        assert adapter.high_water == limit
        return elapsed

    serial = elapsed_for(1)
    parallel = elapsed_for(4)

    assert serial >= 0.25
    assert parallel < serial * 0.7


def test_raw_adapter_fault_is_sanitized_and_falls_back() -> None:
    faulty = _ConcurrentAdapter(
        "faulty",
        frozenset({METADATA_OPERATION}),
        raise_raw=True,
    )
    healthy = _ConcurrentAdapter(
        "healthy",
        frozenset({METADATA_OPERATION}),
    )
    first = _registration(faulty, key="faulty")
    second = _registration(healthy, key="healthy")
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    plan = _plans(
        planner,
        registrations,
        1,
        priorities={"faulty": 1, "healthy": 2},
    )
    policies = _policy(
        registrations,
        priorities={"faulty": 1, "healthy": 2},
    )

    receipt = ProviderExecutionRuntime(planner).execute(plan, policies)[0]
    selection = receipt.selections[0]

    assert receipt.complete
    assert selection.selected_attempt is not None
    assert selection.selected_attempt.provider_key == "healthy"
    assert [attempt.status for attempt in selection.attempts] == [
        FailureClassification.ADAPTER_FAULT,
        AdapterOutcomeStatus.SUCCESS,
    ]
    assert faulty.secret not in repr(receipt)
    assert faulty.secret not in receipt.semantic_digest


def test_classified_failure_retry_and_exact_fallback_are_receipted() -> None:
    limited = _ConcurrentAdapter(
        "limited",
        frozenset({METADATA_OPERATION}),
        failure=FailureClassification.RATE_LIMITED,
        retry_after_seconds=12.5,
    )
    exact = _ConcurrentAdapter(
        "exact",
        frozenset({METADATA_OPERATION}),
    )
    first = _registration(limited, key="limited")
    second = _registration(exact, key="exact")
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    plan = _plans(
        planner,
        registrations,
        1,
        priorities={"limited": 1, "exact": 2},
    )
    policies = _policy(
        registrations,
        priorities={"limited": 1, "exact": 2},
    )

    receipt = ProviderExecutionRuntime(planner).execute(plan, policies)[0]
    attempts = receipt.selections[0].attempts

    assert receipt.complete
    assert attempts[0].status is FailureClassification.RATE_LIMITED
    assert attempts[0].retry_after_seconds == 12.5
    assert attempts[1].status is AdapterOutcomeStatus.SUCCESS
    assert receipt.selections[0].selected_attempt is not None
    assert receipt.selections[0].selected_attempt.provider_key == "exact"


def test_near_identity_never_becomes_the_selected_receipt() -> None:
    near = _ConcurrentAdapter(
        "near",
        frozenset({METADATA_OPERATION}),
        near_mpn="PART-0000-TR",
    )
    exact = _ConcurrentAdapter(
        "exact",
        frozenset({METADATA_OPERATION}),
    )
    first = _registration(near, key="near")
    second = _registration(exact, key="exact")
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    plan = _plans(
        planner,
        registrations,
        1,
        priorities={"near": 1, "exact": 2},
    )
    policies = _policy(
        registrations,
        priorities={"near": 1, "exact": 2},
    )

    receipt = ProviderExecutionRuntime(planner).execute(plan, policies)[0]

    assert receipt.complete
    assert receipt.selections[0].attempts[0].status is (FailureClassification.NEAR_MATCH_REJECTED)
    assert receipt.selections[0].selected_attempt is not None
    assert receipt.selections[0].selected_attempt.provider_key == "exact"


def test_receipts_are_immutable_sanitized_and_semantically_reproducible() -> None:
    adapter = _ConcurrentAdapter(
        "reproducible",
        frozenset({METADATA_OPERATION}),
        delay_seconds=0.001,
    )
    registration = _registration(adapter, key="reproducible")
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    runtime = ProviderExecutionRuntime(planner)
    plan = _plans(planner, registrations, 1)
    policies = _policy(registrations)

    first = runtime.execute(plan, policies)[0]
    second = runtime.execute(plan, policies)[0]

    assert first.semantic_digest == second.semantic_digest
    assert first.selections[0].attempts[0].execution_ns >= 0
    assert first.selections[0].attempts[0].queue_wait_ns >= 0
    with pytest.raises(FrozenInstanceError):
        first.semantic_digest = "sha256:tampered"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.selections[0].attempts[0].execution_ns = 0  # type: ignore[misc]


def test_runtime_rejects_partial_dual_eda_plan_before_execution() -> None:
    adapter = _ConcurrentAdapter(
        "dual",
        frozenset(ORDINARY_COMPONENT_OPERATIONS),
    )
    registration = _registration(
        adapter,
        key="dual",
        operations=ORDINARY_COMPONENT_OPERATIONS,
    )
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    complete = _plans(
        planner,
        registrations,
        1,
        operations=ORDINARY_COMPONENT_OPERATIONS,
    )[0]
    kicad_route = next(route for route in complete.routes if route.operation is KICAD_CAD_OPERATION)
    forged = ProviderPlan(
        complete.identity,
        (kicad_route,),
        complete.semantic_digest,
    )
    policies = _policy(registrations)

    with pytest.raises(ProviderRuntimeError, match="both KiCad and Altium"):
        ProviderExecutionRuntime(planner).execute((forged,), policies)

    assert adapter.calls == []


def test_runtime_reports_incomplete_when_one_eda_route_exhausts() -> None:
    class _AltiumMissAdapter(_ConcurrentAdapter):
        def execute(
            self,
            identity: ExactPartIdentity,
            operation: ProviderOperation,
        ) -> AdapterOutcome:
            if operation is ALTIUM_CAD_OPERATION:
                with self._lock:
                    self.calls.append((identity, operation))
                return AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)
            return super().execute(identity, operation)

    adapter = _AltiumMissAdapter(
        "dual",
        frozenset(ORDINARY_COMPONENT_OPERATIONS),
    )
    registration = _registration(
        adapter,
        key="dual",
        operations=ORDINARY_COMPONENT_OPERATIONS,
    )
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    plan = _plans(
        planner,
        registrations,
        1,
        operations=ORDINARY_COMPONENT_OPERATIONS,
    )
    policies = _policy(registrations)

    receipt = ProviderExecutionRuntime(planner).execute(plan, policies)[0]

    assert not receipt.complete
    assert receipt.unmet_operations == (ALTIUM_CAD_OPERATION,)
    assert [selection.operation for selection in receipt.selections] == [
        METADATA_OPERATION,
        DATASHEET_OPERATION,
        KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION,
    ]


def test_capability_cannot_register_without_callable_adapter() -> None:
    adapter = _NonCallableAdapter(
        "not_callable",
        frozenset({METADATA_OPERATION}),
    )

    with pytest.raises(ProviderPolicyError, match="matching executable"):
        _registration(adapter, key="not_callable")


def test_mutated_adapter_capability_is_rejected_before_invocation() -> None:
    adapter = _ConcurrentAdapter(
        "mutable",
        frozenset({METADATA_OPERATION}),
    )
    registration = _registration(adapter, key="mutable")
    planner = ProviderPlanner((registration,))
    plan = _plans(planner, (registration,), 1)
    policies = _policy((registration,))
    adapter.executable_operations = frozenset()

    with pytest.raises(ProviderPolicyError, match="changed after plan"):
        ProviderExecutionRuntime(planner).execute(plan, policies)

    assert adapter.calls == []


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("trust", TrustDecision.SECONDARY),
        ("license", LicenseDecision.BLOCKED),
        ("authentication", AuthenticationState.AVAILABLE),
        ("health", ProviderHealth.DEGRADED),
        ("priority", 101),
    ],
)
def test_saved_plan_replay_rejects_any_policy_drift_before_invocation(
    field_name: str,
    changed_value: object,
) -> None:
    adapter = _ConcurrentAdapter(
        "policy_bound",
        frozenset({METADATA_OPERATION}),
    )
    registration = _registration(adapter, key="policy_bound")
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    planned_policy = _policy(registrations)
    plan = planner.plan((_request(0),), planned_policy)
    current_policy = (
        replace(
            planned_policy[0],
            **{field_name: changed_value},
        ),
    )

    with pytest.raises(ProviderPolicyError, match="current policy or registry"):
        ProviderExecutionRuntime(planner).execute(plan, current_policy)

    assert adapter.calls == []


@pytest.mark.parametrize(
    ("adapter_version", "max_concurrency"),
    [
        ("2.0.0", 2),
        ("1.0.0", 3),
    ],
)
def test_saved_plan_replay_rejects_registry_drift_before_invocation(
    adapter_version: str,
    max_concurrency: int,
) -> None:
    original_adapter = _ConcurrentAdapter(
        "registry_bound",
        frozenset({METADATA_OPERATION}),
    )
    original = _registration(original_adapter, key="registry_bound")
    original_planner = ProviderPlanner((original,))
    original_policy = _policy((original,))
    plan = original_planner.plan((_request(0),), original_policy)

    replacement_adapter = _ConcurrentAdapter(
        "registry_bound",
        frozenset({METADATA_OPERATION}),
    )
    replacement = _registration(
        replacement_adapter,
        key="registry_bound",
        version=adapter_version,
        max_concurrency=max_concurrency,
    )
    replacement_planner = ProviderPlanner((replacement,))
    current_policy = _policy((replacement,))

    with pytest.raises((ProviderPolicyError, ProviderRuntimeError)):
        ProviderExecutionRuntime(replacement_planner).execute(plan, current_policy)

    assert original_adapter.calls == []
    assert replacement_adapter.calls == []


def test_plan_1000_and_late_adapter_drift_fail_before_any_batch_invocation() -> None:
    metadata_adapter = _ConcurrentAdapter(
        "metadata_only",
        frozenset({METADATA_OPERATION}),
    )
    cad_adapter = _ConcurrentAdapter(
        "cad_only",
        frozenset({KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION}),
    )
    metadata = _registration(
        metadata_adapter,
        key="metadata_only",
        operations=(METADATA_OPERATION,),
    )
    cad = _registration(
        cad_adapter,
        key="cad_only",
        operations=(KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION),
    )
    registrations = (metadata, cad)
    planner = ProviderPlanner(registrations)
    policies = _policy(registrations)
    requests = tuple(_request(index) for index in range(999)) + (
        ProviderRequest(
            ExactPartIdentity("ON Semiconductor", "PART-0999"),
            (KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION),
        ),
    )
    plans = planner.plan(requests, policies)
    runtime = ProviderExecutionRuntime(planner)
    forged_last = replace(
        plans[-1],
        semantic_digest=f"sha256:{'0' * 64}",
    )

    with pytest.raises(ProviderPolicyError, match="semantic digest"):
        runtime.execute((*plans[:-1], forged_last), policies)

    assert metadata_adapter.calls == []
    assert cad_adapter.calls == []

    cad_adapter.executable_operations = frozenset({KICAD_CAD_OPERATION})
    with pytest.raises(ProviderPolicyError, match="capability changed"):
        runtime.execute(plans, policies)

    assert metadata_adapter.calls == []
    assert cad_adapter.calls == []


def test_runtime_bounds_and_route_contract_are_strict() -> None:
    adapter = _ConcurrentAdapter(
        "bounded",
        frozenset({METADATA_OPERATION}),
    )
    registration = _registration(adapter, key="bounded")
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    runtime = ProviderExecutionRuntime(planner)
    plan = _plans(planner, registrations, 1)[0]
    policies = _policy(registrations)

    with pytest.raises(ProviderRuntimeError, match="between 1 and 1000"):
        runtime.execute((), policies)
    with pytest.raises(ProviderRuntimeError, match="between 1 and 1000"):
        runtime.execute((plan,) * 1_001, policies)
    empty_route = ProviderRoute(
        operation=METADATA_OPERATION,
        attempts=(),
        exclusions=(),
    )
    with pytest.raises(ProviderRuntimeError, match="admission declarations"):
        runtime.execute(
            (
                ProviderPlan(
                    plan.identity,
                    (empty_route,),
                    plan.semantic_digest,
                ),
            ),
            policies,
        )


def test_attempt_receipt_rejects_secret_bearing_freeform_status() -> None:
    adapter = _ConcurrentAdapter(
        "safe",
        frozenset({METADATA_OPERATION}),
    )
    registration = _registration(adapter, key="safe")
    planner = ProviderPlanner((registration,))
    attempt = _plans(planner, (registration,), 1)[0].routes[0].attempts[0]

    with pytest.raises(TypeError, match="sanitized provider status"):
        ProviderAttemptReceipt(
            attempt=attempt,
            status="token=secret",  # type: ignore[arg-type]
            retry_after_seconds=None,
            queue_wait_ns=0,
            execution_ns=0,
        )
