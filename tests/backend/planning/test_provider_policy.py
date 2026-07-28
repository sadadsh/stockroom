from __future__ import annotations

from dataclasses import dataclass, field

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
    ProviderDeclaration,
    ProviderHealth,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyError,
    ProviderPolicyInput,
    ProviderRegistration,
    ProviderRequest,
    TrustDecision,
    UnexecutableProviderPlan,
)


@dataclass(slots=True)
class _SyntheticAdapter:
    provider_key: str
    executable_operations: frozenset[ProviderOperation]
    outcomes: dict[ProviderOperation, list[AdapterOutcome]] = field(default_factory=dict)
    secret: str = "adapter-secret-must-never-be-logged"
    calls: list[tuple[ExactPartIdentity, ProviderOperation]] = field(default_factory=list)

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        self.calls.append((identity, operation))
        queued = self.outcomes.get(operation)
        if queued:
            return queued.pop(0)
        return AdapterOutcome.success(identity)


@dataclass(slots=True)
class _RaisingAdapter:
    provider_key: str
    executable_operations: frozenset[ProviderOperation]
    secret: str = "provider-secret-in-raw-exception"

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        del identity, operation
        raise RuntimeError(self.secret)


def _registration(
    key: str,
    *,
    operations: tuple[ProviderOperation, ...] = ORDINARY_COMPONENT_OPERATIONS,
    outcomes: dict[ProviderOperation, list[AdapterOutcome]] | None = None,
    max_concurrency: int = 2,
) -> tuple[ProviderRegistration, _SyntheticAdapter]:
    adapter = _SyntheticAdapter(
        provider_key=key,
        executable_operations=frozenset(operations),
        outcomes={} if outcomes is None else outcomes,
    )
    registration = ProviderRegistration(
        ProviderDeclaration(
            key=key,
            adapter_version="1.0.0",
            operations=operations,
            max_concurrency=max_concurrency,
        ),
        adapter,
    )
    return registration, adapter


def _policy(
    registrations: tuple[ProviderRegistration, ...],
    *,
    overrides: dict[
        tuple[str, ProviderOperation],
        dict[str, object],
    ]
    | None = None,
) -> tuple[ProviderPolicyInput, ...]:
    changed = {} if overrides is None else overrides
    values = []
    for registration in registrations:
        for operation in registration.declaration.operations:
            fields: dict[str, object] = {
                "trust": TrustDecision.PRIMARY,
                "license": LicenseDecision.ALLOWED,
                "authentication": AuthenticationState.NOT_REQUIRED,
                "health": ProviderHealth.HEALTHY,
                "priority": 100,
            }
            fields.update(changed.get((registration.declaration.key, operation), {}))
            values.append(
                ProviderPolicyInput(
                    provider_key=registration.declaration.key,
                    operation=operation,
                    trust=fields["trust"],  # type: ignore[arg-type]
                    license=fields["license"],  # type: ignore[arg-type]
                    authentication=fields["authentication"],  # type: ignore[arg-type]
                    health=fields["health"],  # type: ignore[arg-type]
                    priority=fields["priority"],  # type: ignore[arg-type]
                )
            )
    return tuple(values)


def _identity(mpn: str = "S1M") -> ExactPartIdentity:
    return ExactPartIdentity("ON Semiconductor", mpn)


def _metadata_request(mpn: str = "S1M") -> ProviderRequest:
    return ProviderRequest(_identity(mpn), (METADATA_OPERATION,))


def test_advertised_operation_requires_a_matching_executable_adapter() -> None:
    adapter = _SyntheticAdapter(
        provider_key="example",
        executable_operations=frozenset({METADATA_OPERATION}),
    )
    declaration = ProviderDeclaration(
        key="example",
        adapter_version="1.0.0",
        operations=(METADATA_OPERATION, DATASHEET_OPERATION),
        max_concurrency=1,
    )

    with pytest.raises(ProviderPolicyError, match="matching executable"):
        ProviderRegistration(declaration, adapter)


def test_metadata_datasheet_and_dual_eda_cad_use_separate_executable_routes() -> None:
    metadata, metadata_adapter = _registration(
        "metadata_api",
        operations=(METADATA_OPERATION,),
    )
    datasheet, datasheet_adapter = _registration(
        "datasheet_api",
        operations=(DATASHEET_OPERATION,),
    )
    cad, cad_adapter = _registration(
        "cad_vendor",
        operations=(KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION),
        max_concurrency=1,
    )
    registrations = (metadata, datasheet, cad)
    planner = ProviderPlanner(registrations)
    policies = _policy(registrations)

    plan = planner.plan(
        (ProviderRequest(_identity()),),
        policies,
    )[0]
    report = planner.execute(plan, policies)

    assert report.complete
    assert [(route.operation, route.attempts[0].provider_key) for route in plan.routes] == [
        (METADATA_OPERATION, "metadata_api"),
        (DATASHEET_OPERATION, "datasheet_api"),
        (KICAD_CAD_OPERATION, "cad_vendor"),
        (ALTIUM_CAD_OPERATION, "cad_vendor"),
    ]
    assert [operation for _identity_value, operation in metadata_adapter.calls] == [
        METADATA_OPERATION
    ]
    assert [operation for _identity_value, operation in datasheet_adapter.calls] == [
        DATASHEET_OPERATION
    ]
    assert [operation for _identity_value, operation in cad_adapter.calls] == [
        KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION,
    ]
    assert planner.concurrency_limits == {
        "cad_vendor": 1,
        "datasheet_api": 2,
        "metadata_api": 2,
    }


def test_plan_order_is_deterministic_across_registry_and_policy_input_order() -> None:
    alpha, _ = _registration("alpha", operations=(METADATA_OPERATION,))
    beta, _ = _registration("beta", operations=(METADATA_OPERATION,))
    zeta, _ = _registration("zeta", operations=(METADATA_OPERATION,))
    registrations = (zeta, beta, alpha)
    overrides = {
        ("alpha", METADATA_OPERATION): {"priority": 10},
        ("beta", METADATA_OPERATION): {
            "priority": 10,
            "trust": TrustDecision.SECONDARY,
        },
        ("zeta", METADATA_OPERATION): {"priority": 20},
    }
    policies = _policy(registrations, overrides=overrides)

    left = ProviderPlanner(registrations).plan(
        (_metadata_request(),),
        policies,
    )[0]
    right = ProviderPlanner(tuple(reversed(registrations))).plan(
        (_metadata_request(),),
        tuple(reversed(policies)),
    )[0]

    expected = ["alpha", "beta", "zeta"]
    assert [attempt.provider_key for attempt in left.routes[0].attempts] == expected
    assert right == left


def test_explicit_policy_filters_and_classifies_every_ineligible_provider() -> None:
    keys = (
        "trust_blocked",
        "trust_unreviewed",
        "license_unknown",
        "license_blocked",
        "auth_missing",
        "auth_expired",
        "auth_invalid",
        "rate_limited",
        "unavailable",
        "circuit_open",
        "healthy",
    )
    registrations = tuple(_registration(key, operations=(METADATA_OPERATION,))[0] for key in keys)
    overrides = {
        ("trust_blocked", METADATA_OPERATION): {"trust": TrustDecision.BLOCKED},
        ("trust_unreviewed", METADATA_OPERATION): {"trust": TrustDecision.UNREVIEWED},
        ("license_unknown", METADATA_OPERATION): {"license": LicenseDecision.UNKNOWN},
        ("license_blocked", METADATA_OPERATION): {"license": LicenseDecision.BLOCKED},
        ("auth_missing", METADATA_OPERATION): {"authentication": AuthenticationState.MISSING},
        ("auth_expired", METADATA_OPERATION): {"authentication": AuthenticationState.EXPIRED},
        ("auth_invalid", METADATA_OPERATION): {"authentication": AuthenticationState.INVALID},
        ("rate_limited", METADATA_OPERATION): {"health": ProviderHealth.RATE_LIMITED},
        ("unavailable", METADATA_OPERATION): {"health": ProviderHealth.UNAVAILABLE},
        ("circuit_open", METADATA_OPERATION): {"health": ProviderHealth.CIRCUIT_OPEN},
    }
    planner = ProviderPlanner(registrations)
    plan = planner.plan(
        (_metadata_request(),),
        _policy(registrations, overrides=overrides),
    )[0]
    route = plan.routes[0]

    assert [attempt.provider_key for attempt in route.attempts] == ["healthy"]
    assert {exclusion.provider_key: exclusion.classification for exclusion in route.exclusions} == {
        "trust_blocked": FailureClassification.TRUST_BLOCKED,
        "trust_unreviewed": FailureClassification.TRUST_BLOCKED,
        "license_unknown": FailureClassification.LICENSE_BLOCKED,
        "license_blocked": FailureClassification.LICENSE_BLOCKED,
        "auth_missing": FailureClassification.AUTH_MISSING,
        "auth_expired": FailureClassification.AUTH_EXPIRED,
        "auth_invalid": FailureClassification.AUTH_INVALID,
        "rate_limited": FailureClassification.RATE_LIMITED,
        "unavailable": FailureClassification.UNAVAILABLE,
        "circuit_open": FailureClassification.UNAVAILABLE,
    }
    with pytest.raises(ProviderPolicyError, match="explicit policy"):
        planner.plan((_metadata_request(),), ())


@pytest.mark.parametrize(
    ("status", "retry_after"),
    [
        (FailureClassification.UNAVAILABLE, None),
        (FailureClassification.RATE_LIMITED, 30.0),
        (FailureClassification.AUTH_MISSING, None),
        (FailureClassification.UNSUPPORTED_FORMAT, None),
        (FailureClassification.NOT_FOUND_EXACT, None),
    ],
)
def test_runtime_classification_automatically_falls_back(
    status: FailureClassification,
    retry_after: float | None,
) -> None:
    first, first_adapter = _registration(
        "first",
        operations=(METADATA_OPERATION,),
        outcomes={
            METADATA_OPERATION: [
                AdapterOutcome.failure(
                    status,
                    retry_after_seconds=retry_after,
                )
            ]
        },
    )
    second, second_adapter = _registration(
        "second",
        operations=(METADATA_OPERATION,),
    )
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    policies = _policy(
        registrations,
        overrides={
            ("first", METADATA_OPERATION): {"priority": 1},
            ("second", METADATA_OPERATION): {"priority": 2},
        },
    )
    plan = planner.plan(
        (_metadata_request(),),
        policies,
    )[0]

    report = planner.execute(plan, policies)
    resolution = report.resolutions[0]

    assert report.complete
    assert resolution.winner is not None
    assert resolution.winner.provider_key == "second"
    assert [record.status for record in resolution.attempts] == [
        status,
        AdapterOutcomeStatus.SUCCESS,
    ]
    assert resolution.attempts[0].retry_after_seconds == retry_after
    assert len(first_adapter.calls) == 1
    assert len(second_adapter.calls) == 1


@pytest.mark.parametrize(
    ("manufacturer", "mpn"),
    [
        ("On Semiconductor", "S1M"),
        ("ON Semiconductor.", "S1M"),
        ("ON  Semiconductor", "S1M"),
        ("ON Semiconductor", "S1M-TR"),
    ],
)
def test_near_match_is_rejected_before_fallback_exact_identity(
    manufacturer: str,
    mpn: str,
) -> None:
    identity = _identity()
    near_match = AdapterOutcome(
        AdapterOutcomeStatus.SUCCESS,
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
    )
    first, _ = _registration(
        "first",
        operations=(METADATA_OPERATION,),
        outcomes={METADATA_OPERATION: [near_match]},
    )
    second, _ = _registration("second", operations=(METADATA_OPERATION,))
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    policies = _policy(
        registrations,
        overrides={
            ("first", METADATA_OPERATION): {"priority": 1},
            ("second", METADATA_OPERATION): {"priority": 2},
        },
    )
    plan = planner.plan(
        (ProviderRequest(identity, (METADATA_OPERATION,)),),
        policies,
    )[0]

    report = planner.execute(plan, policies)

    assert report.complete
    assert report.resolutions[0].attempts[0].status is (FailureClassification.NEAR_MATCH_REJECTED)
    assert report.resolutions[0].winner is not None
    assert report.resolutions[0].winner.provider_key == "second"


@pytest.mark.parametrize(
    ("manufacturer", "mpn"),
    [
        ("", "S1M"),
        (" ON Semiconductor", "S1M"),
        ("ON Semiconductor", "S1M "),
        ("Cafe\u0301", "S1M"),
    ],
)
def test_identity_input_never_normalizes_or_accepts_mpn_only_aliases(
    manufacturer: str,
    mpn: str,
) -> None:
    with pytest.raises(ValueError):
        ExactPartIdentity(manufacturer, mpn)


def test_concurrency_declaration_is_bounded_and_adapter_secrets_are_not_loggable() -> None:
    for value in (0, 65):
        with pytest.raises(ProviderPolicyError, match="max_concurrency"):
            ProviderDeclaration(
                key="example",
                adapter_version="1.0.0",
                operations=(METADATA_OPERATION,),
                max_concurrency=value,
            )

    registration, adapter = _registration(
        "example",
        operations=(METADATA_OPERATION,),
        max_concurrency=4,
    )
    planner = ProviderPlanner((registration,))

    assert planner.concurrency_limits == {"example": 4}
    assert adapter.secret not in repr(registration)
    assert adapter.secret not in repr(planner)
    assert "credential" not in repr(_policy((registration,))[0]).casefold()


def test_one_and_one_thousand_requests_use_the_same_planner_path() -> None:
    registration, adapter = _registration("complete_provider")
    registrations = (registration,)
    planner = ProviderPlanner(registrations)
    policies = _policy(registrations)
    one_request = ProviderRequest(_identity("PART-0000"))
    many_requests = tuple(ProviderRequest(_identity(f"PART-{index:04d}")) for index in range(1_000))

    one = planner.plan((one_request,), policies)[0]
    many = planner.plan(many_requests, policies)

    assert len(many) == 1_000
    assert tuple((route.operation, route.attempts) for route in many[0].routes) == tuple(
        (route.operation, route.attempts) for route in one.routes
    )
    assert all(planner.execute(plan, policies).complete for plan in many)
    assert len(adapter.calls) == 4_000

    route_signature = tuple((route.operation, route.attempts) for route in one.routes)
    assert all(
        tuple((route.operation, route.attempts) for route in plan.routes) == route_signature
        for plan in many
    )


def test_request_count_is_strictly_bounded() -> None:
    registration, _ = _registration("complete_provider")
    planner = ProviderPlanner((registration,))
    policies = _policy((registration,))

    with pytest.raises(ProviderPolicyError, match="between 1 and 1000"):
        planner.plan((), policies)
    with pytest.raises(ProviderPolicyError, match="between 1 and 1000"):
        planner.plan(
            tuple(ProviderRequest(_identity(f"PART-{index:04d}")) for index in range(1_001)),
            policies,
        )


def test_dual_eda_requirement_fails_closed_before_any_adapter_executes() -> None:
    complete_operations = (
        METADATA_OPERATION,
        DATASHEET_OPERATION,
        KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION,
    )
    registration, adapter = _registration(
        "single_vendor",
        operations=complete_operations,
    )
    policies = _policy(
        (registration,),
        overrides={("single_vendor", ALTIUM_CAD_OPERATION): {"health": ProviderHealth.UNAVAILABLE}},
    )
    planner = ProviderPlanner((registration,))

    with pytest.raises(UnexecutableProviderPlan) as raised:
        planner.plan((ProviderRequest(_identity()),), policies)

    assert raised.value.unmet_operations == (ALTIUM_CAD_OPERATION,)
    assert raised.value.exclusions[0].classification is (FailureClassification.UNAVAILABLE)
    assert adapter.calls == []
    with pytest.raises(ProviderPolicyError, match="both KiCad and Altium"):
        ProviderRequest(_identity(), (KICAD_CAD_OPERATION,))


def test_exhausted_runtime_fallback_never_claims_completion() -> None:
    first, _ = _registration(
        "first",
        operations=(METADATA_OPERATION,),
        outcomes={
            METADATA_OPERATION: [AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)]
        },
    )
    second, _ = _registration(
        "second",
        operations=(METADATA_OPERATION,),
        outcomes={
            METADATA_OPERATION: [AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)]
        },
    )
    registrations = (first, second)
    planner = ProviderPlanner(registrations)
    policies = _policy(registrations)
    plan = planner.plan(
        (_metadata_request(),),
        policies,
    )[0]

    report = planner.execute(plan, policies)

    assert not report.complete
    assert report.unmet_operations == (METADATA_OPERATION,)
    assert [record.status for record in report.resolutions[0].attempts] == [
        FailureClassification.NOT_FOUND_EXACT,
        FailureClassification.UNSUPPORTED_FORMAT,
    ]


def test_saved_plan_refuses_a_different_adapter_version() -> None:
    original, _ = _registration("versioned", operations=(METADATA_OPERATION,))
    policies = _policy((original,))
    plan = ProviderPlanner((original,)).plan(
        (_metadata_request(),),
        policies,
    )[0]
    replacement_adapter = _SyntheticAdapter(
        provider_key="versioned",
        executable_operations=frozenset({METADATA_OPERATION}),
    )
    replacement = ProviderRegistration(
        ProviderDeclaration(
            key="versioned",
            adapter_version="2.0.0",
            operations=(METADATA_OPERATION,),
            max_concurrency=2,
        ),
        replacement_adapter,
    )

    replacement_policies = _policy((replacement,))
    with pytest.raises(ProviderPolicyError, match="no longer matches"):
        ProviderPlanner((replacement,)).execute(plan, replacement_policies)

    assert replacement_adapter.calls == []


def test_raw_adapter_exception_fails_closed_without_exposing_secret() -> None:
    adapter = _RaisingAdapter(
        provider_key="raising",
        executable_operations=frozenset({METADATA_OPERATION}),
    )
    registration = ProviderRegistration(
        ProviderDeclaration(
            key="raising",
            adapter_version="1.0.0",
            operations=(METADATA_OPERATION,),
            max_concurrency=1,
        ),
        adapter,
    )
    planner = ProviderPlanner((registration,))
    policies = _policy((registration,))
    plan = planner.plan(
        (_metadata_request(),),
        policies,
    )[0]

    with pytest.raises(ProviderPolicyError) as raised:
        planner.execute(plan, policies)

    assert adapter.secret not in str(raised.value)
    assert adapter.secret not in repr(raised.value)
